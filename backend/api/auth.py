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

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from api.db import get_db
from api.models import User


def generate_api_key() -> str:
    return secrets.token_urlsafe(32)


def hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def get_current_user(
    x_api_key: str | None = Header(default=None), db: Session = Depends(get_db)
) -> User:
    if not x_api_key:
        raise HTTPException(status_code=401, detail="missing X-API-Key header")

    user = db.query(User).filter(User.api_key_hash == hash_api_key(x_api_key)).first()
    if user is None:
        raise HTTPException(status_code=401, detail="invalid API key")

    return user
