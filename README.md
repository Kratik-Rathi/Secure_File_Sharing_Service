# Secure File Sharing Service

A REST API for uploading private files and sharing them via time-limited, cryptographically signed download links.

Files are stored outside any publicly served path. The only way bytes leave the service is through a signed link whose signature and expiry are verified on every request. Every link generation, redemption, rejection, and deletion is recorded in a durable audit trail.

Two interfaces are provided: the interactive OpenAPI docs at `/docs` cover the full API surface, and a minimal React client demonstrates the end-to-end flow.

---

## Contents

- [Quick start](#quick-start)
- [Interfaces](#interfaces)
- [Configuration](#configuration)
- [API reference](#api-reference)
- [End-to-end example](#end-to-end-example)
- [How signing works](#how-signing-works)
- [Testing](#testing)
- [Architecture](#architecture)
- [Security notes](#security-notes)
- [Deployment](#deployment)
- [Known limitations](#known-limitations)

---

## Quick start

Requirements: Python 3.11+, PostgreSQL 14+, Node 18+ (frontend only).

### Backend

```bash
# 1. Database
sudo service postgresql start
sudo su - postgres -c "psql -c \"CREATE USER fileshare WITH PASSWORD 'localdev' CREATEDB;\""
sudo su - postgres -c "psql -c \"CREATE DATABASE fileshare OWNER fileshare;\""

# 2. Dependencies
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 3. Configuration
cp .env.example .env        # then edit values

# 4. Run
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev                 # http://localhost:5173
```

Requires the API running on port 8000.

Tables are created on first startup. Demo users are seeded **only** when `ENVIRONMENT=development`.

**Demo credentials** (development only):

| Username | Password |
|---|---|
| `alice` | `alice-password` |
| `bob` | `bob-password` |

Override with `SEED_PASSWORD_ALICE` / `SEED_PASSWORD_BOB`. In any other environment no accounts are created at all — seeding is gated in `app/main.py`, and a `demo_users_seeded` warning is logged whenever it runs, so it is visible if it ever executes somewhere unexpected.

---

## Interfaces

### OpenAPI docs — `http://localhost:8000/docs`

The complete API surface, generated from the route definitions and Pydantic schemas. Click **Authorize**, paste an access token from `POST /auth/login`, and every endpoint is callable directly. This is the authoritative interface and stays in sync with the code automatically.

### React client — `http://localhost:5173`

A deliberately minimal client covering login, upload, file listing, link generation, deletion, and audit inspection. It exists to demonstrate the end-to-end flow visually; it is not a product surface and duplicates only part of the API.

Signed links open in a new tab and carry no credentials — which demonstrates the core property directly: a link works in any browser, including a fresh incognito window, until it expires.

Two client-side decisions worth noting:

- **The access token lives in React state only**, never in `localStorage` or `sessionStorage`. A persisted token is readable by any injected script. The trade-off is that a page refresh requires re-authentication. A production client would use an httpOnly cookie with CSRF protection.
- **CORS origins are allowlisted explicitly** in `CORSMiddleware` rather than using a wildcard. For deployment this should be driven by an environment variable.

Any `401` from the API clears client state and returns to the login screen, so an expired token degrades cleanly rather than producing a broken view.

---

## Configuration

All configuration comes from environment variables. Nothing is hardcoded. The application refuses to start if a required variable is missing.

| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | yes | SQLAlchemy connection string, e.g. `postgresql+psycopg://user:pass@host:5432/db` |
| `SECRET_KEY` | yes | Signing key for both JWTs and download signatures. Generate with `openssl rand -hex 32`. |
| `STORAGE_PATH` | yes | Absolute path to the private upload directory. Must not be served statically. |
| `ENVIRONMENT` | no | `development` gives human-readable logs and seeds demo users; anything else emits JSON and seeds nothing. Default `development`. |
| `JWT_EXPIRE_MINUTES` | no | Access token lifetime. Default `60`. |
| `SEED_PASSWORD_ALICE` | no | Overrides the seeded demo password. Development only. |
| `SEED_PASSWORD_BOB` | no | Overrides the seeded demo password. Development only. |

> **`SECRET_KEY` must be stable across restarts.** It is loaded from the environment rather than generated at boot, which is what keeps previously issued download links valid after a redeploy. Rotating it invalidates every outstanding link and token.

`.env` is gitignored. `.env.example` documents the required keys with placeholder values.

---

## API reference

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/health` | — | Liveness check |
| `POST` | `/auth/login` | — | Exchange credentials for a JWT |
| `POST` | `/files` | Bearer | Upload a file (multipart) |
| `GET` | `/files` | Bearer | List the caller's files |
| `GET` | `/files/{id}` | Bearer | Metadata for one owned file |
| `DELETE` | `/files/{id}` | Bearer | Delete an owned file and its stored bytes |
| `POST` | `/files/{id}/sign` | Bearer | Generate a signed download link |
| `GET` | `/files/{id}/audit` | Bearer | Audit trail for one owned file |
| `GET` | `/download` | **none** | Redeem a signed link |

`/download` is intentionally unauthenticated. The signature *is* the authorization — that is what makes links shareable.

The audit trail is visible to the file's owner only. A download recipient sees nothing beyond the file itself.

### Status codes

| Code | Meaning |
|---|---|
| `201` | File uploaded |
| `204` | File deleted |
| `400` | Empty upload |
| `401` | Missing, malformed, or expired JWT; bad credentials |
| `403` | Invalid download signature |
| `404` | File does not exist, or is not owned by the caller |
| `410` | Download link has expired |
| `422` | Request validation failed (e.g. `ttl_seconds` out of range) |
| `500` | Unhandled error — generic message to client, full trace in logs |

Requesting or deleting a file owned by another user returns `404`, not `403`. A `403` would confirm the file exists.

### Error format

Every error response carries the request ID, which also appears on every related log line:

```json
{
  "detail": "Invalid download signature",
  "request_id": "fc8068e81e7f41a7bcccbe264f963ac1"
}
```

Validation failures additionally include per-field detail:

```json
{
  "detail": "Request validation failed",
  "errors": [{ "field": "body.ttl_seconds", "message": "Input should be greater than or equal to 1" }],
  "request_id": "..."
}
```

---

## End-to-end example

```bash
BASE=http://localhost:8000

# Authenticate
TOKEN=$(curl -s -X POST $BASE/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"alice","password":"alice-password"}' | jq -r .access_token)

# Upload
echo "confidential" > /tmp/report.txt
FILE_ID=$(curl -s -X POST $BASE/files \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@/tmp/report.txt" | jq -r .id)

# Generate a 5-minute link
URL=$(curl -s -X POST $BASE/files/$FILE_ID/sign \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"ttl_seconds":300}' | jq -r .download_url)

# Redeem it — no credentials required
curl -s "$URL"

# Tampering is rejected (403)
curl -s -o /dev/null -w "%{http_code}\n" "${URL:0:-1}0"

# Inspect the audit trail
curl -s $BASE/files/$FILE_ID/audit -H "Authorization: Bearer $TOKEN" | jq

# Delete the file (204)
curl -s -o /dev/null -w "%{http_code}\n" -X DELETE \
  $BASE/files/$FILE_ID -H "Authorization: Bearer $TOKEN"
```

---

## How signing works

A signed link carries three query parameters: `file_id`, `expires` (Unix timestamp), and `signature`.

```
signature = HMAC-SHA256(SECRET_KEY, "{file_id}:{expires}")
```

**The link is signed, not encrypted.** The file ID and expiry are readable by anyone holding the link — they are not secrets. What the signature provides is *unforgeability*: altering either value invalidates the signature, and a valid one cannot be produced without the server-side key. A recipient cannot extend a link's lifetime or repoint it at a different file.

Verification order on `/download`:

1. **Signature** — recomputed and compared with `hmac.compare_digest`. Constant-time comparison prevents timing attacks that would otherwise leak how much of a guessed signature was correct. Failure → `403` + `signature_rejected` audit event.
2. **Expiry** — checked against current UTC time. Failure → `410` + `link_expired` audit event.
3. **Existence** — only now is the database consulted.

The signature is checked *before* any database lookup, so the endpoint cannot be used to probe which file IDs exist.

### Audit trail

Recorded in `audit_events`: `file_uploaded`, `link_generated`, `link_redeemed`, `signature_rejected`, `link_expired`, `file_deleted`.

Events are written to Postgres *and* emitted as structured logs. These are not redundant: logs are ephemeral and best-effort, the audit table is durable and queryable. `signature_rejected` is stored with a null `file_id` — a forged signature cannot be trusted to identify a real file, so it is not attributed to one.

### Deletion

`DELETE /files/{id}` removes the database row and the stored bytes, and records a `file_deleted` audit event.

Audit history is deliberately retained: events for the deleted file have their `file_id` set to null rather than being cascaded away, with the filename preserved in `detail`. An audit trail that disappears along with its subject cannot answer the questions an audit trail exists for.

The row is committed before the file is unlinked from disk. An orphaned file with no row wastes space but breaks nothing; a row pointing at missing bytes is a failed download on a link that was promised to work.

Deleting a file invalidates any outstanding signed links for it, which then return `404`.

---

## Testing

```bash
python -m pytest tests/ -v
```

19 tests, no external services required. Tests run against in-memory SQLite via FastAPI dependency overrides, so the suite is fast, isolated, and runs unchanged in CI.

Coverage focuses on the security-critical paths:

- Signature round-trip, and binding to **both** file ID and expiry
- Tampered signature rejected (`403`)
- Expired link rejected (`410`)
- Cross-user access and cross-user deletion denied
- File listings scoped to owner
- Deletion removes the file and invalidates outstanding links
- TTL bounds enforced
- Link generation recorded in the audit trail

---

## Architecture

See [`docs/architecture.md`](docs/architecture.md) for component and sequence diagrams and the full design-decision rationale.

```
app/
├── main.py            app assembly, middleware, exception handlers, seeding
├── config.py          environment-driven settings
├── database.py        engine, session factory, get_db dependency
├── models.py          User, FileRecord, AuditEvent
├── schemas.py         request/response contracts (separate from ORM models)
├── security.py        HMAC signing, bcrypt, JWT — pure functions
├── storage.py         streamed disk writes, path-traversal guard
├── dependencies.py    get_current_user
├── logging_config.py  structlog + request-ID context
└── routers/
    ├── auth.py        login
    ├── files.py       upload, list, metadata, delete, sign, audit
    └── download.py    public signed download

frontend/
└── src/App.jsx        minimal React client

tests/
├── test_signing.py    pure unit tests — no DB, no HTTP
└── test_api.py        route-level integration tests
```

ORM models and API schemas are deliberately separate classes. Coupling them would make a column rename a breaking API change and would risk exposing internal fields — `password_hash` and `stored_name` are never serializable by accident.

Signing logic is isolated in `security.py` as pure functions, which is why it can be unit-tested without a database, a request, or any fixtures. It is the part of the system where a bug is most costly.

---

## Security notes

| Concern | Mitigation |
|---|---|
| Path traversal | Uploads are stored under a generated UUID; the client filename never touches the filesystem. Resolved paths are additionally verified to be inside the storage root. |
| Password storage | bcrypt with per-password salt. Input truncated to bcrypt's 72-byte limit explicitly rather than relying on library behaviour. |
| Timing attacks | `hmac.compare_digest` for signature comparison. |
| User enumeration | Login returns one error for both unknown user and wrong password. Unowned files return `404`. |
| Known-credential accounts in production | User seeding is gated on `ENVIRONMENT=development`; no accounts are created in other environments. Seed passwords are environment-driven rather than hardcoded. |
| Credential leakage in logs | JWTs and download signatures are never logged. Audit entries record file and user IDs only. |
| Information disclosure | Unhandled exceptions return a generic message plus a request ID; the stack trace goes to logs only. |
| Memory exhaustion | Uploads stream to disk in 1 MiB chunks rather than being buffered whole. |
| Orphaned data | A failed metadata commit rolls back and deletes the file already written to disk. |
| Token exposure in the browser | The React client holds the token in memory only, never in browser storage. |
| Overly permissive CORS | Origins are allowlisted explicitly rather than using a wildcard. |

Uploads are never served from a static mount. Mounting `STORAGE_PATH` statically would bypass signature verification entirely and defeat the purpose of the service.

---

## Deployment

Runtime requirements: a stable `SECRET_KEY`, a reachable PostgreSQL instance, and a **persistent** filesystem at `STORAGE_PATH`.

The persistence requirement rules out stateless platforms. On DigitalOcean App Platform, the container filesystem is wiped on every redeploy and uploads would be lost. Suitable targets:

- **Droplet + Docker with a bind-mounted host directory** — satisfies the local-filesystem requirement. Attaching a Block Storage Volume separates the data lifecycle from the compute lifecycle, so the data survives rebuilding the Droplet.
- **Object storage (Spaces / S3)** — the correct production answer at scale, and the necessary change before running more than one instance.

Bind to `0.0.0.0`, not `127.0.0.1`, or the platform cannot route traffic to the container.

### CI

GitHub Actions runs on every push and on pull requests targeting `main`:

- **Tests** — the full suite, with no database service required
- **Docker build** — builds the image, runs it, and polls `/health` until it responds, so a container that builds but fails to start also fails CI

Branch strategy: work lands on `staging`, reaches `main` only through a pull request, and `main` requires both checks to pass before merge.

---

## Known limitations

Deliberate scope decisions, not oversights:

- **`create_all` instead of Alembic migrations.** Creates tables but cannot alter them, making it unusable once the schema evolves in production. Alembic is the immediate next addition.
- **Local disk does not scale horizontally.** Two instances behind a load balancer do not share a filesystem; a file uploaded to one is a 404 on the other. Object storage is the migration path, and signed URLs map directly onto what Spaces and S3 already provide natively.
- **No upload size limit.** Should be enforced at the reverse proxy and rejected before bytes are written.
- **JWTs cannot be revoked before expiry.** Would require a token blocklist, or short-lived tokens with refresh.
- **No rate limiting** on login or link generation.
- **Tests run against SQLite.** The query surface is kept dialect-agnostic, but a PostgreSQL service container in CI would close the gap.
- **Users are seeded, not registered.** Registration is well-understood CRUD; the time went to the signing and audit paths instead. Seeding is gated to development, so production starts with no accounts — a real deployment would need either a registration endpoint or provisioning through an identity provider.
- **Signed links are not single-use.** A link can be redeemed any number of times until it expires. Enforcing single use would require recording redemption state, which is a straightforward addition to the existing audit table.
- **CORS origins are hardcoded** for local development rather than environment-driven.
