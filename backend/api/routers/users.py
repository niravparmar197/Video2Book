import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.auth import generate_api_key, get_current_user, get_user_for_rotation, hash_api_key
from api.book_deletion import delete_book
from api.config import settings
from api.db import get_db
from api.logging import get_logger
from api.models import Book, User
from api.schemas import ApiKeyResponse, UserCreateRequest, UserCreateResponse
from api.signup_limit import allow_signup

router = APIRouter(prefix="/users", tags=["users"])

# A job holds these while the worker runs it; deleting under it is refused.
_RUNNING_STATUSES = ("planning", "rendering")


def _expires_at(issued_at: datetime) -> datetime | None:
    if settings.api_key_max_age_days <= 0:
        return None
    return issued_at + timedelta(days=settings.api_key_max_age_days)


@router.post("", response_model=UserCreateResponse, status_code=201)
def create_user(
    payload: UserCreateRequest, request: Request, db: Session = Depends(get_db)
) -> UserCreateResponse:
    if not payload.accept_terms:
        raise HTTPException(status_code=422, detail="you must accept the terms of use")
    if settings.signup_invite_code and not secrets.compare_digest(
        (payload.invite_code or "").encode(), settings.signup_invite_code.encode()
    ):
        raise HTTPException(status_code=403, detail="a valid invite code is required to sign up")
    if not allow_signup(request.client.host if request.client else "unknown"):
        raise HTTPException(status_code=429, detail="too many sign-ups from this address -- try again later")

    existing = db.query(User).filter(User.email == payload.email).first()
    if existing is not None:
        raise HTTPException(status_code=409, detail="email already registered")

    raw_key = generate_api_key()
    now = datetime.now(timezone.utc)
    user = User(
        email=payload.email,
        api_key_hash=hash_api_key(raw_key),
        api_key_created_at=now,
        terms_accepted_at=now,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    return UserCreateResponse(user_id=user.id, api_key=raw_key)


@router.post("/me/api-key", response_model=ApiKeyResponse)
def rotate_api_key(
    db: Session = Depends(get_db), user: User = Depends(get_user_for_rotation)
) -> ApiKeyResponse:
    """Issue a new key and invalidate the old one at once. Works with an
    expired key too -- otherwise an expired user could never get back in."""
    raw_key = generate_api_key()
    user.api_key_hash = hash_api_key(raw_key)
    user.api_key_created_at = datetime.now(timezone.utc)
    db.commit()
    get_logger(step="rotate_key").info("api key rotated", extra={"user_id": user.id})
    return ApiKeyResponse(api_key=raw_key, expires_at=_expires_at(user.api_key_created_at))


@router.delete("/me", status_code=204)
async def delete_account(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> Response:
    """Delete the user and every book they made, with all of its files."""
    books = list(db.execute(select(Book).where(Book.user_id == user.id)).scalars())
    running = [book.id for book in books if book.status in _RUNNING_STATUSES]
    if running:
        raise HTTPException(
            status_code=409,
            detail=f"{len(running)} book(s) are still being made -- cancel them first",
        )
    for book in books:
        await delete_book(db, book)
    db.delete(user)
    db.commit()
    get_logger(step="delete_account").info("account deleted", extra={"user_id": user.id})
    return Response(status_code=204)
