# GitHub Issues Gateway

A small service that wraps the GitHub REST API for Issues on a single repository. Exposes a simplified HTTP API for issue CRUD and comments, receives and verifies GitHub webhooks, and provides an OpenAPI 3.1 contract, automated tests, and Docker packaging.

## How to run locally

### Option A — Docker

```bash
docker build -t github-issues-gateway .
docker run -p 8000:8000 --env-file .env github-issues-gateway
```

### Option B — Without Docker

```bash
python -m venv venv
venv\Scripts\Activate.ps1        # Windows PowerShell
# source venv/bin/activate       # macOS/Linux

pip install -r requirements.txt

uvicorn app.main:app --reload --port 8000
```

Either way, the service is available at `http://localhost:8000`.

## Environment variables

Create a `.env` file in the project root (never committed — see `.gitignore`):

| Variable | Description |
|---|---|
| `GITHUB_TOKEN` | Fine-grained GitHub PAT, scoped to the target repo with **Issues: Read and Write** permission only |
| `GITHUB_OWNER` | GitHub username/org that owns the target repo |
| `GITHUB_REPO` | Name of the target repo |
| `WEBHOOK_SECRET` | Shared secret used to verify incoming GitHub webhook signatures (HMAC-SHA256) |
| `PORT` | Port the service listens on (e.g. `8000`) |

Example `.env`:
```
GITHUB_TOKEN=github_pat_xxxxxxxxxxxx
GITHUB_OWNER=yourusername
GITHUB_REPO=your-test-repo
WEBHOOK_SECRET=some-random-string
PORT=8000
```

**Scopes used:** the PAT is scoped to a single repository with only the **Issues: Read and Write** repository permission (plus the automatically-added **Metadata: Read-only**). No other permissions are granted, minimizing blast radius if the token is ever leaked.

## API examples

All examples assume the service is running on `http://localhost:8000`.

**Create an issue**
```bash
curl -X POST http://localhost:8000/issues \
  -H "Content-Type: application/json" \
  -d '{"title": "Bug: login fails", "body": "Steps to reproduce...", "labels": ["bug"]}'
```

**List issues**
```bash
curl "http://localhost:8000/issues?state=open&per_page=30"
```

**Get a single issue**
```bash
curl http://localhost:8000/issues/1
```

**Update an issue (rename, edit, close/reopen)**
```bash
curl -X PATCH http://localhost:8000/issues/1 \
  -H "Content-Type: application/json" \
  -d '{"state": "closed"}'
```

**Add a comment**
```bash
curl -X POST http://localhost:8000/issues/1/comments \
  -H "Content-Type: application/json" \
  -d '{"body": "Thanks for reporting this!"}'
```

**View recent webhook events**
```bash
curl http://localhost:8000/events
```

**Health check**
```bash
curl http://localhost:8000/healthz
```

**Simulate a webhook delivery** (for manual testing without a real GitHub event)
```bash
BODY='{"zen": "test", "action": "opened"}'
SECRET="your-webhook-secret"
SIG="sha256=$(echo -n "$BODY" | openssl dgst -sha256 -hmac "$SECRET" | sed 's/^.* //')"

curl -X POST http://localhost:8000/webhook \
  -H "Content-Type: application/json" \
  -H "X-GitHub-Event: ping" \
  -H "X-GitHub-Delivery: manual-test-1" \
  -H "X-Hub-Signature-256: $SIG" \
  -d "$BODY"
```

> Note: on Windows PowerShell, `curl` is aliased to `Invoke-WebRequest`, which does not accept the flags above the same way. Use `curl.exe` explicitly (e.g. `curl.exe -X POST ...`), or use `Invoke-RestMethod` with PowerShell-native syntax, e.g.:
> ```powershell
> Invoke-RestMethod -Uri "http://localhost:8000/issues" -Method Post -ContentType "application/json" -Body '{"title": "Test issue"}'
> ```

### HTTPie equivalents

The same routes using [HTTPie](https://httpie.io/) syntax (`pip install httpie`):

```bash
# Create an issue
http POST localhost:8000/issues title="Bug: login fails" body="Steps to reproduce..." labels:='["bug"]'

# List issues
http GET localhost:8000/issues state==open per_page==30

# Get a single issue
http GET localhost:8000/issues/1

# Update an issue
http PATCH localhost:8000/issues/1 state=closed

# Add a comment
http POST localhost:8000/issues/1/comments body="Thanks for reporting this!"

# View recent webhook events
http GET localhost:8000/events

# Health check
http GET localhost:8000/healthz
```

## Webhook setup

GitHub needs a public URL to deliver webhooks to, so local development requires a tunnel (ngrok, Cloudflared, or smee).

1. Start the service locally (`uvicorn` or Docker, as above).
2. Start a tunnel pointing at your local port, e.g.:
   ```bash
   ngrok http 8000
   ```
   This gives you a public URL like `https://abcd1234.ngrok-free.app`.
3. On GitHub, go to your repo → **Settings → Webhooks → Add webhook**:
   - **Payload URL**: `https://<your-tunnel-url>/webhook`
   - **Content type**: `application/json`
   - **Secret**: the same value as your `.env`'s `WEBHOOK_SECRET`
   - **Events**: select "Let me select individual events" → check **Issues** and **Issue comments**
   - Ensure **Active** is checked
4. Click **Add webhook**. GitHub immediately sends a `ping` event — a green checkmark next to the delivery confirms it succeeded.
5. Trigger a real event (e.g. open an issue on GitHub.com) and confirm it was received:
   ```bash
   curl http://localhost:8000/events
   ```

### Redelivery instructions

If you need to replay a webhook delivery (e.g. after fixing a bug):
1. Go to **Settings → Webhooks** → click your webhook
2. Scroll to **Recent Deliveries**
3. Click the delivery you want to replay → click **Redeliver**

Redeliveries are safe to replay multiple times — the service deduplicates by delivery ID + action, so a redelivered event is acknowledged but not double-processed.

**Note on the tunnel:** keep the same `WEBHOOK_SECRET` on both the tunnel/service side and the GitHub webhook config. If you restart ngrok, the tunnel URL changes and the webhook's Payload URL must be updated in GitHub's settings to match.

## Testing

Two independent test suites — **do not run them together** in a single `pytest` invocation, since unit tests use fake credentials and integration tests use real ones, and Python's module caching can cross-contaminate environment variables if both run in the same process (see design note for details).

**Unit tests** (mocked GitHub, no network calls):
```bash
pytest tests/test_routes.py tests/test_webhook.py -v
```

**Integration tests** (hits the real GitHub API against your configured test repo):
```bash
pytest tests/test_integration.py -v
```

**Coverage report** (combined):
```bash
pytest tests/test_routes.py tests/test_webhook.py --cov=app --cov-report=
pytest tests/test_integration.py --cov=app --cov-append --cov-report=term-missing
```

Current combined coverage: **86%**.

## OpenAPI contract

See [`openapi.yaml`](./openapi.yaml) for the full API contract (OpenAPI 3.1), including schemas, examples, and error responses. Validate it with:
```bash
npx @redocly/cli lint openapi.yaml
```

## Extra credit implemented

- **Conditional GET with ETag** on `GET /issues` — caches GitHub's `ETag` and sends `If-None-Match` on repeat polls to reduce rate-limit usage. See design note for the caching behavior details.
- **CI pipeline** — `.github/workflows/test.yml` runs unit tests (not integration tests, which require real secrets) on every push/PR.
