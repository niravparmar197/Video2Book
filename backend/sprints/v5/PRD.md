# Sprint v5 — PRD: S3 File Storage

## Overview

Every rendered PDF has lived on the API/worker's local disk since v1,
even though `backend/AGENTS.md`'s stack table has said "Files: S3" since
sprint one. This sprint moves the rendered PDF (only the PDF, not
ai_llm's intermediate cache/checkpoint files) into S3-compatible storage
once a render succeeds, serves downloads via a presigned URL, and adds a
retention setting with an actual delete path — closing two
production-readiness checklist items (`backend/AGENTS.md`: "Files: S3"
and "Data retention") at once.

## Goals

- On a successful `render`/`retry` phase, the worker uploads
  `output/<book_id>/book.pdf` to S3 and stores the resulting object key
  in `Book.pdf_path` (replacing the local path it holds today); the local
  copy of `book.pdf` is deleted afterward — everything else in
  `output/<book_id>/` (chunks, checkpoint db, chapters) stays untouched,
  since a future retry still needs it.
- `GET /books/{id}/pdf` issues a time-limited presigned S3 URL and
  redirects (307) to it, instead of streaming the file through the API
  process.
- Local dev/test run against a real S3-compatible service via
  docker-compose (originally scoped as MinIO — landed on `adobe/s3mock`
  instead, see Technical Architecture) — no mocked S3 client, same
  principle v1-v4 applied to Postgres/Redis.
- `PDF_RETENTION_DAYS` (default 30, env-overridable) plus a
  `python -m api.retention` script that deletes S3 objects (and clears
  `Book.pdf_path`) for books older than the window — a real, runnable
  delete path, not just a documented policy.
- `GET /health` also reports S3 connectivity, alongside the existing
  Postgres/Redis checks from v2.

## User Stories

- As a user, I want my finished PDF served from fast, durable storage
  instead of a single API server's local disk, so a server restart or
  redeploy doesn't lose my book.
- As an operator, I want old PDFs actually deleted after a retention
  window, so storage costs don't grow unbounded — not just a policy
  written in a doc nobody runs.
- As an operator, I want `/health` to tell me if S3 itself is
  unreachable, the same way it already tells me about Postgres/Redis.

## Technical Architecture

Builds on v1-v4's `api/` package. Adds one new local dev dependency
(an S3-compatible service) and one new Python dependency (`boto3`).

```
 worker: render/retry phase succeeds
        │
        ▼
 api/storage.py: upload_pdf(book_id, local_pdf_path) -> s3_key
        │  boto3 put_object to S3_BUCKET; ensures bucket exists first
        ▼
 Book.pdf_path = s3_key (e.g. "<book_id>/book.pdf")
 local output/<book_id>/book.pdf deleted (rest of output_dir untouched)

 client ──GET /books/{id}/pdf──▶ FastAPI
                                    │  book.status != "done"? 404 (unchanged)
                                    ▼
                          storage.presigned_url(book.pdf_path)
                                    │
                                    ▼
                          307 redirect ──▶ client fetches bytes
                                            directly from S3/S3Mock

 GET /health ──▶ existing DB/Redis checks + storage.check_s3()

 python -m api.retention  (operator-run, not scheduled by this sprint)
        │  for each Book with pdf_path set and older than
        │  PDF_RETENTION_DAYS: delete the S3 object, clear pdf_path
        ▼
```

**Local dev**: `docker-compose.yml` gains an S3-compatible service.
Scoped as MinIO, but MinIO's official and Bitnami Docker images both
turned out to require a Docker Hub login to pull, and
`localstack/localstack:latest` pulls fine but refuses to start without a
paid `LOCALSTACK_AUTH_TOKEN` — all discovered by actually trying each,
not assumed. Landed on `adobe/s3mock` (Apache-2.0, genuinely free, no
auth), which ran and round-tripped a real `boto3` put/get/presigned-URL
cycle on the first try. `S3_ENDPOINT_URL` points the app's `boto3` client
at it locally; unset in a real deploy, so `boto3` talks to real AWS S3
there without any code change — same env-var-driven pattern as
`DATABASE_URL`/`REDIS_URL`.

**Why a redirect, not a proxy**: streaming PDF bytes through the API
process (as `GET /books/{id}/pdf` did through v4) doesn't scale and adds
no value once the file is in S3 — a presigned URL lets the client fetch
directly from storage while keeping the bucket private (no public-read
objects).

## Out of Scope (v6+)

- Deleting or archiving anything in `output/<book_id>/` besides the
  rendered `book.pdf` itself — the checkpoint db, chunk cache, and
  chapter `.tex` files stay local so `--resume`/`/retry` keep working.
- Scheduling `python -m api.retention` (cron, a background worker job,
  etc.) — this sprint ships the script; running it on a schedule is a
  deploy-time/ops concern for a later sprint.
- Multi-region buckets, S3 lifecycle policies configured in AWS itself,
  encryption-at-rest beyond S3's defaults, CDN/CloudFront in front of
  downloads.
- Uploading anything *other* than the final PDF to S3 (no screenshots,
  no intermediate assets) — out of scope until something needs it.
- Everything else already deferred as of v4 (live per-node `/events` +
  Postgres checkpointer, honoring a reordered outline, per-chapter
  status, password/JWT/OAuth login, key rotation, Sentry, Bull Board,
  backups, a global spend ceiling).

## Dependencies

- Sprints v1-v4 complete: core loop, health/logging/PDF download,
  outline review + retry, auth + rate limiting, all tested against real
  Postgres/Redis.
- `docker-compose up -d` available locally (Postgres, Redis, and now
  S3Mock).
