from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, HttpUrl


class UserCreateRequest(BaseModel):
    email: EmailStr


class UserCreateResponse(BaseModel):
    user_id: str
    api_key: str


class BookCreateRequest(BaseModel):
    url: HttpUrl


class VideoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    video_id: str
    title: str | None = None
    duration_seconds: int | None = None


class BookResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: str
    pdf_path: str | None = None
    error_message: str | None = None
    estimated_cost_usd: float = 0.0
    url: str
    created_at: datetime
    videos: list[VideoOut] = []


class ChapterOut(BaseModel):
    id: str
    title: str
    order: int
    skip: bool
    locked: bool
    source_video_ids: list[str]


class ChapterEdit(BaseModel):
    id: str
    skip: bool
    locked: bool
