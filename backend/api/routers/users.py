from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.auth import generate_api_key, hash_api_key
from api.db import get_db
from api.models import User
from api.schemas import UserCreateRequest, UserCreateResponse

router = APIRouter(prefix="/users", tags=["users"])


@router.post("", response_model=UserCreateResponse, status_code=201)
def create_user(payload: UserCreateRequest, db: Session = Depends(get_db)) -> UserCreateResponse:
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing is not None:
        raise HTTPException(status_code=409, detail="email already registered")

    raw_key = generate_api_key()
    user = User(email=payload.email, api_key_hash=hash_api_key(raw_key))
    db.add(user)
    db.commit()
    db.refresh(user)

    return UserCreateResponse(user_id=user.id, api_key=raw_key)
