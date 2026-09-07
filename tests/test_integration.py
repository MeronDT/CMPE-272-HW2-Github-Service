#Created by Meron, utilizing claude

import os
import time
import pytest
from dotenv import load_dotenv
from fastapi.testclient import TestClient

load_dotenv()

pytestmark = pytest.mark.skipif(
    not os.environ.get("GITHUB_TOKEN"),
    reason="Integration tests require real GITHUB_TOKEN/.env values",
)

from app.main import app

client = TestClient(app)


def test_full_issue_lifecycle():
    #create
    create_resp = client.post(
        "/issues",
        json={
            "title": "[integration-test] full lifecycle",
            "body": "Created by automated integration test.",
        },
    )
    assert create_resp.status_code == 201
    issue = create_resp.json()
    number = issue["number"]
    assert issue["state"] == "open"
    assert create_resp.headers["location"] == f"/issues/{number}"

    #get back
    get_resp = client.get(f"/issues/{number}")
    assert get_resp.status_code == 200
    assert get_resp.json()["title"] == "[integration-test] full lifecycle"

    #update
    patch_resp = client.patch(
        f"/issues/{number}",
        json={
            "title": "[integration-test] full lifecycle (updated)",
            "body": "Body updated by integration test.",
        },
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["title"] == "[integration-test] full lifecycle (updated)"

    #close
    close_resp = client.patch(f"/issues/{number}", json={"state": "closed"})
    assert close_resp.status_code == 200
    assert close_resp.json()["state"] == "closed"

    #reopen
    reopen_resp = client.patch(f"/issues/{number}", json={"state": "open"})
    assert reopen_resp.status_code == 200
    assert reopen_resp.json()["state"] == "open"

    #add comment
    comment_resp = client.post(
        f"/issues/{number}/comments",
        json={"body": "Comment added by integration test."},
    )
    assert comment_resp.status_code == 201
    assert comment_resp.json()["body"] == "Comment added by integration test."

    final_close = client.patch(f"/issues/{number}", json={"state": "closed"})
    assert final_close.status_code == 200


def test_list_issues_reflects_created_issue():
    create_resp = client.post(
        "/issues", json={"title": "[integration-test] list check"}
    )
    number = create_resp.json()["number"]

    #GitHub's list endpoint can lag slightly behind a just-created issue retry instead of asserting immediately.
    numbers = []
    for _ in range(5):
        list_resp = client.get("/issues", params={"state": "all", "per_page": 100})
        assert list_resp.status_code == 200
        numbers = [i["number"] for i in list_resp.json()]
        if number in numbers:
            break
        time.sleep(1)

    assert number in numbers, f"issue {number} not found in list after retries: {numbers}"

    client.patch(f"/issues/{number}", json={"state": "closed"})


def test_get_nonexistent_issue_returns_404():
    #using very high issue number that assuming doesnt exist
    resp = client.get("/issues/999999")
    assert resp.status_code == 404


def test_events_endpoint_returns_recent_events():
    resp = client.get("/events")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)