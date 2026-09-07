#Created by Meron, utilizing claude

import os
import time
import httpx

GITHUB_API_BASE = "https://api.github.com"


class GitHubAPIError(Exception):
    """When GitHub's API returns an error response."""
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(message)


#for allowing errors to handle rate limits
class RateLimitError(GitHubAPIError):
    """When GitHub signals we've hit a rate limit."""
    def __init__(self, retry_after: int):
        super().__init__(503, f"GitHub rate limit exceeded. Retry after {retry_after} seconds.")
        self.retry_after = retry_after


def _raise_for_status(resp: httpx.Response) -> None:
    """Inspect a GitHub response and raise the appropriate error, if any.
    Returns no exception when successful response."""
    if resp.status_code == 403 and resp.headers.get("X-RateLimit-Remaining") == "0":
        reset_epoch = resp.headers.get("X-RateLimit-Reset")
        retry_after = 60
        if reset_epoch:
            retry_after = max(1, int(reset_epoch) - int(time.time()))
        raise RateLimitError(retry_after)

    if resp.status_code == 429:
        retry_after = int(resp.headers.get("Retry-After", "60"))
        raise RateLimitError(retry_after)

    if resp.status_code >= 400:
        raise GitHubAPIError(resp.status_code, resp.json().get("message", "GitHub API error"))

    # status_code < 400: success, do nothing


def _headers() -> dict:
    token = os.environ["GITHUB_TOKEN"]
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _repo_path() -> str:
    owner = os.environ["GITHUB_OWNER"]
    repo = os.environ["GITHUB_REPO"]
    return f"/repos/{owner}/{repo}"


async def create_issue(title: str, body: str | None = None, labels: list[str] | None = None) -> dict:
    payload = {"title": title}
    if body is not None:
        payload["body"] = body
    if labels is not None:
        payload["labels"] = labels

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{GITHUB_API_BASE}{_repo_path()}/issues",
            headers=_headers(),
            json=payload,
        )

    _raise_for_status(resp)
    return resp.json()


async def list_issues(state: str = "open", labels: str | None = None, page: int = 1, per_page: int = 30, etag: str | None = None) -> tuple[list[dict] | None, str | None, str | None, bool]:
    """Returns (issues_or_None, link_header, new_etag, not_modified)."""
    params = {"state": state, "page": page, "per_page": per_page}
    if labels:
        params["labels"] = labels

    headers = _headers()
    if etag:
        headers["If-None-Match"] = etag

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{GITHUB_API_BASE}{_repo_path()}/issues",
            headers=headers,
            params=params,
        )

    if resp.status_code == 304:
        return None, resp.headers.get("Link"), resp.headers.get("ETag"), True

    _raise_for_status(resp)
    return resp.json(), resp.headers.get("Link"), resp.headers.get("ETag"), False


async def get_issue(number: int) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{GITHUB_API_BASE}{_repo_path()}/issues/{number}",
            headers=_headers(),
        )

    _raise_for_status(resp)
    return resp.json()


async def update_issue(number: int, title: str | None = None, body: str | None = None, state: str | None = None) -> dict:
    payload = {}
    if title is not None:
        payload["title"] = title
    if body is not None:
        payload["body"] = body
    if state is not None:
        payload["state"] = state

    async with httpx.AsyncClient() as client:
        resp = await client.patch(
            f"{GITHUB_API_BASE}{_repo_path()}/issues/{number}",
            headers=_headers(),
            json=payload,
        )

    _raise_for_status(resp)
    return resp.json()


async def create_comment(number: int, body: str) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{GITHUB_API_BASE}{_repo_path()}/issues/{number}/comments",
            headers=_headers(),
            json={"body": body},
        )

    _raise_for_status(resp)
    return resp.json()