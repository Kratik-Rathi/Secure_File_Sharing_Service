from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class FileMetadata(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    original_filename: str
    content_type: str
    size_bytes: int
    created_at: datetime


class SignRequest(BaseModel):
    ttl_seconds: int = Field(default=300, ge=1, le=86400)


class SignedLinkResponse(BaseModel):
    file_id: int
    expires_at: datetime
    ttl_seconds: int
    download_url: str


class AuditEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    event_type: str
    file_id: int | None
    ttl_seconds: int | None
    expires_at: datetime | None
    created_at: datetime


class ErrorResponse(BaseModel):
    detail: str
    request_id: str | None = None
    