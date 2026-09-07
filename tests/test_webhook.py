#Created by Meron, utilizing claude

import os
os.environ.setdefault("GITHUB_TOKEN", "fake-token")
os.environ.setdefault("GITHUB_OWNER", "fake-owner")
os.environ.setdefault("GITHUB_REPO", "fake-repo")
os.environ.setdefault("WEBHOOK_SECRET", "fake-secret")

import hmac
import hashlib
import json

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

SECRET = "fake-secret"


def sign(body: bytes) -> str:
    return "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()


def test_webhook_valid_signature_ping_returns_204():
    payload = {"zen": "hello"}
    body = json.dumps(payload).encode()
    sig = sign(body)

    resp = client.post(
        "/webhook",
        data=body,
        headers={
            "X-Hub-Signature-256": sig,
            "X-GitHub-Event": "ping",
            "X-GitHub-Delivery": "test-delivery-1",
            "Content-Type": "application/json",
        },
    )
    assert resp.status_code == 204


def test_webhook_invalid_signature_returns_401():
    payload = {"zen": "hello"}
    body = json.dumps(payload).encode()

    resp = client.post(
        "/webhook",
        data=body,
        headers={
            "X-Hub-Signature-256": "sha256=deadbeef",
            "X-GitHub-Event": "ping",
            "X-GitHub-Delivery": "test-delivery-2",
            "Content-Type": "application/json",
        },
    )
    assert resp.status_code == 401


def test_webhook_tampered_body_returns_401():
    original_body = json.dumps({"zen": "hello"}).encode()
    sig = sign(original_body)
    tampered_body = json.dumps({"zen": "goodbye"}).encode()

    resp = client.post(
        "/webhook",
        data=tampered_body,
        headers={
            "X-Hub-Signature-256": sig,
            "X-GitHub-Event": "ping",
            "X-GitHub-Delivery": "test-delivery-3",
            "Content-Type": "application/json",
        },
    )
    assert resp.status_code == 401


def test_webhook_unknown_event_returns_400():
    body = json.dumps({"foo": "bar"}).encode()
    sig = sign(body)

    resp = client.post(
        "/webhook",
        data=body,
        headers={
            "X-Hub-Signature-256": sig,
            "X-GitHub-Event": "push",
            "X-GitHub-Delivery": "test-delivery-4",
            "Content-Type": "application/json",
        },
    )
    assert resp.status_code == 400