#Created by Meron, utilizing claude

import os
os.environ.setdefault("GITHUB_TOKEN", "fake-token")
os.environ.setdefault("GITHUB_OWNER", "fake-owner")
os.environ.setdefault("GITHUB_REPO", "fake-repo")
os.environ.setdefault("WEBHOOK_SECRET", "fake-secret")

import httpx
import respx
from fastapi.testclient import TestClient
import time

from app.main import app

client = TestClient(app)


def test_create_issue_missing_title_returns_422_or_400():
    resp = client.post("/issues", json={})
    assert resp.status_code in (400, 422)


def test_patch_issue_invalid_state_returns_400():
    resp = client.patch("/issues/1", json={"state": "banana"})
    assert resp.status_code == 400
    assert "state" in resp.json()["detail"]


@respx.mock
def test_create_issue_success():
    respx.post("https://api.github.com/repos/fake-owner/fake-repo/issues").mock(
        return_value=httpx.Response(
            201,
            json={
                "number": 42,
                "html_url": "https://github.com/fake-owner/fake-repo/issues/42",
                "state": "open",
                "title": "Test",
                "body": None,
                "labels": [],
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
            },
        )
    )

    resp = client.post("/issues", json={"title": "Test"})
    assert resp.status_code == 201
    assert resp.json()["number"] == 42
    assert resp.headers["location"] == "/issues/42"


@respx.mock
def test_get_issue_not_found_returns_404():
    respx.get("https://api.github.com/repos/fake-owner/fake-repo/issues/999").mock(
        return_value=httpx.Response(404, json={"message": "Not Found"})
    )

    resp = client.get("/issues/999")
    assert resp.status_code == 404


@respx.mock
def test_create_issue_bad_credentials_returns_401():
    respx.post("https://api.github.com/repos/fake-owner/fake-repo/issues").mock(
        return_value=httpx.Response(401, json={"message": "Bad credentials"})
    )

    resp = client.post("/issues", json={"title": "Test"})
    assert resp.status_code == 401


@respx.mock
def test_create_issue_rate_limited_returns_503():
    respx.post("https://api.github.com/repos/fake-owner/fake-repo/issues").mock(
        return_value=httpx.Response(
            403,
            headers={
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(int(time.time()) + 30),
            },
            json={"message": "API rate limit exceeded"},
        )
    )

    resp = client.post("/issues", json={"title": "Test"})
    assert resp.status_code == 503
    assert "Retry-After" in resp.headers