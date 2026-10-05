from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, HttpUrl


class UserCreateRequest(BaseModel):
    email: EmailStr
    # Must be true: the user takes responsibility for having the rights to
    # the videos they submit (terms of use).
    accept_terms: bool = False
    invite_code: str | None = None


class UserCreateResponse(BaseModel):
    user_id: str
    api_key: str


class ApiKeyResponse(BaseModel):
    api_key: str
    expires_at: datetime | None = None


class BookCreateRequest(BaseModel):
    url: HttpUrl
    # The kind of book: "auto" lets the pipeline decide from the video;
    # lecture -> Study Notes, podcast -> Podcast Notes, comedy -> Comedy Recap.
    genre: Literal["auto", "lecture", "podcast", "comedy"] = "auto"


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
