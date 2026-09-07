#Created by Meron, utilizing claude

#Outbound and Inbound service: outbound uses the REST API wrap for Github's API
#Inbound gets updates on issues from the repo and stores them

import os
import hmac
import hashlib
import json
import time
import uuid
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Response, Request
from pydantic import BaseModel
from app.github_client import (
    create_issue,
    list_issues,
    get_issue,
    update_issue,
    create_comment,
    GitHubAPIError,
    RateLimitError,
)
from app.logging_config import setup_logging, logger

load_dotenv()
setup_logging()
app = FastAPI(title="GitHub Issues Gateway")
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
GITHUB_OWNER = os.environ["GITHUB_OWNER"]
GITHUB_REPO = os.environ["GITHUB_REPO"]
WEBHOOK_SECRET = os.environ["WEBHOOK_SECRET"]

#in-memory event store
events_store: list[dict] = []
seen_deliveries: set[str] = set()


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    logger.info(f"request_id={request_id} method={request.method} path={request.url.path}")
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


class CreateIssueRequest(BaseModel):
    title: str
    body: str | None = None
    labels: list[str] | None = None


def _reshape_issue(issue: dict) -> dict:
    return {
        "number": issue["number"],
        "html_url": issue["html_url"],
        "state": issue["state"],
        "title": issue["title"],
        "body": issue["body"],
        "labels": [l["name"] for l in issue["labels"]],
        "created_at": issue["created_at"],
        "updated_at": issue["updated_at"],
    }


@app.post("/issues", status_code=201)
async def post_issue(req: CreateIssueRequest, response: Response):
    try:
        issue = await create_issue(title=req.title, body=req.body, labels=req.labels)
    except RateLimitError as e:
        raise HTTPException(status_code=503, detail=e.message, headers={"Retry-After": str(e.retry_after)})
    except GitHubAPIError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)

    response.headers["Location"] = f"/issues/{issue['number']}"
    return _reshape_issue(issue)


#in memory ETag cache for conditional GET
issues_etag_cache: dict[str, tuple[str, list[dict], str | None]] = {}

@app.get("/issues")
async def get_issues(
    state: str = "open",
    labels: str | None = None,
    page: int = 1,
    per_page: int = 30,
    response: Response = None,
):
    cache_key = f"{state}:{labels}:{page}:{per_page}"
    cached = issues_etag_cache.get(cache_key)
    cached_etag = cached[0] if cached else None

    try:
        issues, link_header, new_etag, not_modified = await list_issues(
            state=state, labels=labels, page=page, per_page=per_page, etag=cached_etag
        )
    except RateLimitError as e:
        raise HTTPException(status_code=503, detail=e.message, headers={"Retry-After": str(e.retry_after)})
    except GitHubAPIError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)

    if not_modified:
        #GitHub says nothing changed since the last poll, so use our cached list
        _, cached_issues, cached_link = cached
        if cached_link:
            response.headers["Link"] = cached_link
        return cached_issues

    reshaped = [
        {
            "number": i["number"],
            "title": i["title"],
            "state": i["state"],
            "labels": [l["name"] for l in i["labels"]],
        }
        for i in issues
    ]

    if new_etag:
        issues_etag_cache[cache_key] = (new_etag, reshaped, link_header)
    if link_header:
        response.headers["Link"] = link_header

    return reshaped


@app.get("/issues/{number}")
async def get_single_issue(number: int):
    try:
        issue = await get_issue(number)
    except RateLimitError as e:
        raise HTTPException(status_code=503, detail=e.message, headers={"Retry-After": str(e.retry_after)})
    except GitHubAPIError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)

    return _reshape_issue(issue)


class UpdateIssueRequest(BaseModel):
    title: str | None = None
    body: str | None = None
    state: str | None = None


@app.patch("/issues/{number}")
async def patch_issue(number: int, req: UpdateIssueRequest):
    if req.state is not None and req.state not in ("open", "closed"):
        raise HTTPException(status_code=400, detail="state must be 'open' or 'closed'")

    try:
        issue = await update_issue(number, title=req.title, body=req.body, state=req.state)
    except RateLimitError as e:
        raise HTTPException(status_code=503, detail=e.message, headers={"Retry-After": str(e.retry_after)})
    except GitHubAPIError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)

    return _reshape_issue(issue)


class CreateCommentRequest(BaseModel):
    body: str


@app.post("/issues/{number}/comments", status_code=201)
async def post_comment(number: int, req: CreateCommentRequest):
    try:
        comment = await create_comment(number, req.body)
    except RateLimitError as e:
        raise HTTPException(status_code=503, detail=e.message, headers={"Retry-After": str(e.retry_after)})
    except GitHubAPIError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)

    return {
        "id": comment["id"],
        "body": comment["body"],
        "user": comment["user"]["login"],
        "created_at": comment["created_at"],
        "html_url": comment["html_url"],
    }


def verify_signature(payload_body: bytes, signature_header: str | None) -> bool:
    if not signature_header:
        return False

    expected = "sha256=" + hmac.new(
        WEBHOOK_SECRET.encode(), payload_body, hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(expected, signature_header)


@app.post("/webhook", status_code=204)
async def webhook(request: Request):
    raw_body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256")

    if not verify_signature(raw_body, signature):
        raise HTTPException(status_code=401, detail="invalid signature")

    event_type = request.headers.get("X-GitHub-Event")
    delivery_id = request.headers.get("X-GitHub-Delivery")

    if event_type not in ("issues", "issue_comment", "ping"):
        raise HTTPException(status_code=400, detail="unknown event type")

    payload = json.loads(raw_body)
    action = payload.get("action", "n/a")

    logger.info(f"delivery_id={delivery_id} event={event_type} action={action}")

    dedupe_key = f"{delivery_id}:{action}"
    if dedupe_key in seen_deliveries:
        return

    seen_deliveries.add(dedupe_key)

    events_store.append({
        "id": delivery_id,
        "event": event_type,
        "action": action,
        "issue_number": payload.get("issue", {}).get("number"),
        "timestamp": time.time(),
    })

    return


@app.get("/events")
def get_events(limit: int = 20):
    return events_store[-limit:]