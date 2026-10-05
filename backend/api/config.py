import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str = os.environ.get(
        "DATABASE_URL",
        "postgresql+psycopg://video2book:video2book@localhost:5433/video2book",
    )
    redis_url: str = os.environ.get("REDIS_URL", "redis://localhost:6379")
    output_root: str = os.environ.get("OUTPUT_ROOT", "./output")
    max_concurrent_books_per_user: int = int(
        os.environ.get("MAX_CONCURRENT_BOOKS_PER_USER", "3")
    )

    s3_bucket: str = os.environ.get("S3_BUCKET", "video2book-books")
    # "" (explicitly unset) -> None, so a real deploy can point boto3 at
    # actual AWS S3 by setting S3_ENDPOINT_URL= in its environment.
    # Defaults to the local S3Mock container (docker-compose.yml).
    s3_endpoint_url: str | None = os.environ.get("S3_ENDPOINT_URL", "http://localhost:9090") or None
    s3_access_key: str = os.environ.get("S3_ACCESS_KEY", "test")
    s3_secret_key: str = os.environ.get("S3_SECRET_KEY", "test")
    s3_region: str = os.environ.get("S3_REGION", "us-east-1")
    pdf_retention_days: int = int(os.environ.get("PDF_RETENTION_DAYS", "30"))

    # "" (default) -- error tracking is fully disabled, sentry_sdk.init()
    # is never called, no network I/O is ever attempted.
    sentry_dsn: str = os.environ.get("SENTRY_DSN", "")
    sentry_environment: str = os.environ.get("SENTRY_ENVIRONMENT", "development")

    worker_heartbeat_interval_seconds: int = int(
        os.environ.get("WORKER_HEARTBEAT_INTERVAL_SECONDS", "15")
    )
    worker_heartbeat_ttl_seconds: int = int(
        os.environ.get("WORKER_HEARTBEAT_TTL_SECONDS", "45")
    )

    events_poll_seconds: float = float(os.environ.get("EVENTS_POLL_SECONDS", "2"))

    # How many run_book jobs one worker process runs at once. At 1, a
    # book's render waited behind another book's entire plan phase (7.5
    # min measured live). Concurrent books share the CPU (Whisper) and the
    # LLM rate limit (app/llm.py's process-wide pacer), so higher values
    # trade per-book speed for less time waiting in line.
    worker_concurrency: int = int(os.environ.get("WORKER_CONCURRENCY", "2"))

    # Observational only (sprints/v8) -- sums estimated_cost_usd across every
    # book created since UTC midnight and warns past this threshold. Can't
    # fire in production yet: every real estimated_cost_usd is 0.0 until a
    # paid provider is configured (both NVIDIA and Gemini are free tiers).
    global_daily_spend_alert_usd: float = float(
        os.environ.get("GLOBAL_DAILY_SPEND_ALERT_USD", "20")
    )

    # The frontend/ dev server's origin -- browsers block cross-origin
    # fetch() calls (frontend on :3000, this API on :8000) unless the
    # server explicitly allows it via CORS.
    frontend_origin: str = os.environ.get("FRONTEND_ORIGIN", "http://localhost:3000")

    # Sign-up. With an invite code set, POST /users needs it -- otherwise
    # anyone could make unlimited accounts and run books in parallel past
    # MAX_CONCURRENT_BOOKS_PER_USER on the shared free LLM quota. (Email
    # verification would need a mail server.) Sign-ups per IP per hour are
    # capped either way; 0 = no cap.
    signup_invite_code: str = os.environ.get("SIGNUP_INVITE_CODE", "")
    signup_limit_per_ip_per_hour: int = int(os.environ.get("SIGNUP_LIMIT_PER_IP_PER_HOUR", "5"))

    # API keys older than this are refused until rotated (POST
    # /users/me/api-key). 0 = keys never expire.
    api_key_max_age_days: int = int(os.environ.get("API_KEY_MAX_AGE_DAYS", "90"))

    # The worker's daily housekeeping: retention (delete books older than
    # PDF_RETENTION_DAYS: S3 files + local folder) and a Postgres backup.
    housekeeping_interval_hours: float = float(os.environ.get("HOUSEKEEPING_INTERVAL_HOURS", "24"))
    # Backups: pg_dump -> gzip -> S3 under backups/, the newest N kept.
    # "" disables them (e.g. RDS with automated backups).
    backup_command: str = os.environ.get("BACKUP_COMMAND", "pg_dump")
    backups_to_keep: int = int(os.environ.get("BACKUPS_TO_KEEP", "14"))

    # LangSmith tracing of every pipeline LLM call, tagged with the book id.
    # Needs LANGSMITH_API_KEY; the LangChain clients read these from env.
    langsmith_tracing: bool = os.environ.get("LANGSMITH_TRACING", "").lower() in {"1", "true", "yes"}
    langsmith_project: str = os.environ.get("LANGSMITH_PROJECT", "video2book")


settings = Settings()
