# Architecture — Secure File Sharing Service

## Component Overview

```mermaid
flowchart TB
    Client["Client<br/>(Swagger UI / curl)"]

    subgraph API["FastAPI Application"]
        MW["Request-ID Middleware<br/>+ structlog context"]
        Auth["/auth/login<br/>JWT issue"]
        Files["/files<br/>upload · list · metadata · sign · audit<br/>JWT required"]
        Download["/download<br/>PUBLIC — signature is the authorization"]
        Sec["security.py<br/>HMAC-SHA256 · bcrypt · JWT"]
        Store["storage.py<br/>streamed writes · traversal guard"]
    end

    DB[("PostgreSQL<br/>users · files · audit_events")]
    Disk[["Private filesystem<br/>STORAGE_PATH<br/>UUID filenames"]]

    Client --> MW
    MW --> Auth & Files & Download
    Auth --> Sec
    Files --> Sec
    Files --> Store
    Download --> Sec
    Download --> Store
    Auth --> DB
    Files --> DB
    Download --> DB
    Store --> Disk
```

## Upload Flow

```mermaid
sequenceDiagram
    participant C as Client
    participant A as API
    participant S as Storage
    participant D as Postgres

    C->>A: POST /files (multipart + Bearer JWT)
    A->>A: verify JWT, load user
    A->>A: generate UUID stored_name
    A->>S: stream to disk in 1 MiB chunks
    S-->>A: bytes written
    A->>D: INSERT file metadata
    Note over A,S: commit fails → delete file (no orphans)
    A->>D: INSERT audit: file_uploaded
    A-->>C: 201 + metadata (stored_name never exposed)
```

## Signing and Download Flow

```mermaid
sequenceDiagram
    participant O as Owner
    participant A as API
    participant D as Postgres
    participant R as Recipient

    O->>A: POST /files/{id}/sign {ttl_seconds}
    A->>A: verify JWT + ownership
    A->>A: expires_at = now + ttl
    A->>A: sig = HMAC-SHA256(SECRET_KEY, "id:expires_at")
    A->>D: INSERT audit: link_generated
    A-->>O: download_url?file_id&expires&signature

    O->>R: shares link (no credentials)
    R->>A: GET /download?file_id&expires&signature
    A->>A: verify_signature (constant-time compare)
    Note over A: invalid → 403 + audit signature_rejected
    A->>A: check expiry
    Note over A: expired → 410 + audit link_expired
    A->>D: INSERT audit: link_redeemed
    A-->>R: 200 file stream
```

## Key Design Decisions

| Decision | Rationale |
|---|---|
| **HMAC-SHA256 signing, not encryption** | The requirement is unforgeability, not confidentiality. File ID and expiry are public; the signature prevents tampering. |
| **Secret from environment, never generated at boot** | Links stay valid across restarts and redeploys, as required. |
| **`hmac.compare_digest`** | Constant-time comparison; `==` leaks how much of a guessed signature was correct via timing. |
| **Signature verified before any DB lookup** | Prevents using the endpoint to probe which file IDs exist. |
| **UUID filenames on disk** | Client filenames never touch the filesystem — eliminates path traversal. Original kept in DB for display. |
| **Metadata in Postgres, bytes on disk** | Matches the requirement; streams efficiently. Trade-off: two systems can drift, mitigated by rollback-and-delete. |
| **404 not 403 for unowned files** | A 403 confirms the file exists. 404 reveals nothing. |
| **410 expired vs 403 forged** | Semantically distinct: "was valid, now isn't" vs "never was". Separate audit events. |
| **Audit rows in Postgres *and* structured logs** | Logs are ephemeral and best-effort; audit is durable and queryable. Different guarantees. |
| **Request ID on every log line and error response** | Connects a user's report to a full server-side trace. |
| **Sync SQLAlchemy over async** | Workload is file-I/O bound; FastAPI's threadpool handles `def` handlers. Async adds failure modes for no gain at this scale. |

## Known Limitations / Next Steps

- **`create_all` instead of Alembic** — creates tables but cannot alter them; Alembic is the immediate next addition.
- **Local disk doesn't scale horizontally** — two instances behind a load balancer don't share a filesystem. Production path is object storage (DO Spaces / S3), where signed URLs map directly onto native capability.
- **No upload size limit** — should be capped at the reverse proxy and rejected before writing to disk.
- **JWTs cannot be revoked before expiry** — would need a token blocklist or short-lived tokens with refresh.
- **No rate limiting** on login or signing endpoints.
- **Tests run against SQLite** — query surface kept dialect-agnostic, but a Postgres service container in CI would close the gap.
