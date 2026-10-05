"""API-key auth.

A key is a random 256-bit token (`secrets.token_urlsafe(32)`), shown to
the caller exactly once at `POST /users` time. Only its SHA-256 hash is
ever persisted or logged -- never the raw token. This is deliberately
simpler than a slow-hash password scheme (bcrypt/argon2): those defend
low-entropy human-chosen passwords against offline brute force, which
isn't the threat model for an already-256-bit random token.
"""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from api.config import settings
from api.db import get_db
from api.models import User


def generate_api_key() -> str:
    return secrets.token_urlsafe(32)


def hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def _user_for_key(x_api_key: str | None, db: Session) -> User:
    if not x_api_key:
        raise HTTPException(status_code=401, detail="missing X-API-Key header")

    user = db.query(User).filter(User.api_key_hash == hash_api_key(x_api_key)).first()
    if user is None:
        raise HTTPException(status_code=401, detail="invalid API key")

    return user


def key_expired(user: User, now: datetime | None = None) -> bool:
    if settings.api_key_max_age_days <= 0 or user.api_key_created_at is None:
        return False
    issued = user.api_key_created_at
    if issued.tzinfo is None:
        issued = issued.replace(tzinfo=timezone.utc)
    return (now or datetime.now(timezone.utc)) - issued > timedelta(days=settings.api_key_max_age_days)


def get_current_user(
    x_api_key: str | None = Header(default=None), db: Session = Depends(get_db)
) -> User:
    """The key's owner; a key older than API_KEY_MAX_AGE_DAYS is refused
    until rotated with POST /users/me/api-key."""
    user = _user_for_key(x_api_key, db)
    if key_expired(user):
        raise HTTPException(status_code=401, detail="API key expired -- rotate it with POST /users/me/api-key")
    return user


def get_user_for_rotation(
    x_api_key: str | None = Header(default=None), db: Session = Depends(get_db)
) -> User:
    """Like get_current_user but accepts an expired key: rotating is how an
    expired user gets a working key back."""
    return _user_for_key(x_api_key, db)
