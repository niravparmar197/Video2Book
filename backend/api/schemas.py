from pydantic import BaseModel, ConfigDict, EmailStr, HttpUrl


class UserCreateRequest(BaseModel):
    email: EmailStr


class UserCreateResponse(BaseModel):
    user_id: str
    api_key: str


class BookCreateRequest(BaseModel):
    url: HttpUrl


class BookResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: str
    pdf_path: str | None = None
    error_message: str | None = None


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
