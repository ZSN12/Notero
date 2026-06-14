from pydantic import BaseModel, field_validator, EmailStr
from typing import Optional
from datetime import datetime
import re

# User Schemas
class UserCreate(BaseModel):
    username: str
    email: str
    password: str
    security_question: Optional[str] = None
    security_answer: Optional[str] = None

    @field_validator("username")
    @classmethod
    def username_length(cls, v: str) -> str:
        if len(v) < 2 or len(v) > 50:
            raise ValueError("Username must be between 2 and 50 characters")
        return v

    @field_validator("email")
    @classmethod
    def email_format(cls, v: str) -> str:
        if "@" not in v or "." not in v:
            raise ValueError("Invalid email format")
        return v

    @field_validator("password")
    @classmethod
    def password_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v

    @field_validator("security_question")
    @classmethod
    def security_question_length(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and len(v) > 500:
            raise ValueError("Security question must be <= 500 characters")
        return v

    @field_validator("security_answer")
    @classmethod
    def security_answer_length(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and len(v) > 500:
            raise ValueError("Security answer must be <= 500 characters")
        return v

class UserLogin(BaseModel):
    email: str
    password: str

class UserResponse(BaseModel):
    model_config = {"from_attributes": True}
    id: str
    username: str
    email: str
    avatar_url: Optional[str] = None

# Notebook Schemas
class NotebookCreate(BaseModel):
    title: str
    description: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None

    @field_validator("title")
    @classmethod
    def title_length(cls, v: str) -> str:
        if len(v) < 1 or len(v) > 100:
            raise ValueError("Title must be between 1 and 100 characters")
        return v

    @field_validator("color")
    @classmethod
    def color_format(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not re.match(r'^#[0-9a-fA-F]{6}$', v):
            raise ValueError("Color must be in hex format #RRGGBB")
        return v

class NotebookUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None

class NotebookResponse(BaseModel):
    model_config = {"from_attributes": True}
    id: str
    user_id: str
    title: str
    description: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    session_count: int = 0
    created_at: datetime

# Session Schemas
class SessionCreate(BaseModel):
    title: str
    keywords: Optional[list[str]] = None

    @field_validator("title")
    @classmethod
    def title_length(cls, v: str) -> str:
        if len(v) < 1 or len(v) > 200:
            raise ValueError("Title must be between 1 and 200 characters")
        return v

class SessionUpdate(BaseModel):
    title: Optional[str] = None
    keywords: Optional[list[str]] = None
    duration: Optional[str] = None

class SessionResponse(BaseModel):
    model_config = {"from_attributes": True}
    id: str
    notebook_id: str
    title: str
    keywords: list[str] = []
    duration: Optional[str] = None
    status: str = "pending"
    share_enabled: bool = False
    share_expires_at: Optional[datetime] = None
    share_max_views: Optional[int] = None
    share_view_count: int = 0
    created_at: datetime

    @field_validator("keywords", mode="before")
    @classmethod
    def ensure_keywords_list(cls, v):
        return v if v is not None else []

# ── JSON Field Validation Models ──
# These provide runtime validation for JSON/JSONB columns that would
# otherwise accept any shape silently.

class TranscriptTimestamp(BaseModel):
    model_config = {"extra": "allow"}
    text: str
    start_ms: int
    end_ms: int

class TranscriptChunk(BaseModel):
    model_config = {"extra": "allow"}
    chunk_index: Optional[int] = None
    raw_text: Optional[str] = None
    text: Optional[str] = None
    display_text: Optional[str] = None
    corrected_text: Optional[str] = None
    correction_stage: Optional[str] = None
    timestamps: Optional[list[TranscriptTimestamp]] = None

class PPTSlide(BaseModel):
    model_config = {"extra": "allow"}
    page: int
    title: str
    text: str
    image_path: Optional[str] = None
    image_base64: Optional[str] = None

class PPTImageData(BaseModel):
    model_config = {"extra": "allow"}
    slides: list[PPTSlide] = []

class VocabularyItem(BaseModel):
    model_config = {"extra": "allow"}
    kind: Optional[str] = None

class LayoutBlock(BaseModel):
    model_config = {"extra": "allow"}
    id: str
    type: str
    content: Optional[str] = None
    src: Optional[str] = None
    page: Optional[int] = None
    title: Optional[str] = None

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        if v not in ("transcript", "ppt", "note"):
            raise ValueError("type must be one of: transcript, ppt, note")
        return v

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        if not v or len(v) > 128:
            raise ValueError("id must be non-empty and <= 128 chars")
        return v


# Note Schemas
class NoteCreate(BaseModel):
    content: Optional[str] = None
    transcript: Optional[list[TranscriptChunk]] = None
    ppt_images: Optional[list[PPTImageData]] = None
    vocabulary: Optional[list[VocabularyItem]] = None
    layout_blocks: Optional[list[LayoutBlock]] = None

class NoteUpdate(BaseModel):
    content: Optional[str] = None
    layout_blocks: Optional[list[LayoutBlock]] = None

    @field_validator("layout_blocks")
    @classmethod
    def validate_layout_blocks_length(cls, v):
        if v is not None and len(v) > 10000:
            raise ValueError("layout_blocks cannot exceed 10000 items")
        return v

class NoteResponse(BaseModel):
    model_config = {"from_attributes": True, "extra": "ignore"}
    id: str
    session_id: str
    content: Optional[str] = None
    transcript: Optional[list[TranscriptChunk]] = None
    ppt_images: Optional[list[PPTImageData]] = None
    vocabulary: Optional[list[VocabularyItem]] = None
    layout_blocks: Optional[list[LayoutBlock]] = None
    created_at: datetime

# File Schemas
class FileResponse(BaseModel):
    model_config = {"from_attributes": True}
    id: str
    session_id: str
    file_type: str
    file_name: str
    file_path: str
    file_size: Optional[int] = None
    created_at: datetime

# Task Schemas
class TaskResponse(BaseModel):
    model_config = {"from_attributes": True}
    id: str
    session_id: str
    task_type: str
    status: str
    progress: float = 0.0
    error_message: Optional[str] = None
    created_at: datetime

# Vocabulary Schemas
class VocabularyCreate(BaseModel):
    term: str
    translation: Optional[str] = None
    definition: Optional[str] = None
    source: Optional[str] = None

class VocabularyResponse(BaseModel):
    model_config = {"from_attributes": True}
    id: str
    notebook_id: str
    term: str
    translation: Optional[str] = None
    definition: Optional[str] = None
    source: Optional[str] = None
    created_at: datetime

# Auth
class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class TokenRefresh(BaseModel):
    refresh_token: str


class TokenRefreshResponse(BaseModel):
    access_token: str
    token_type: str


class PasswordReset(BaseModel):
    email: str
    security_answer: str
    new_password: str

    @field_validator("security_answer")
    @classmethod
    def security_answer_required(cls, v: str) -> str:
        if not v or len(v.strip()) == 0:
            raise ValueError("Security answer is required")
        return v.strip()

    @field_validator("new_password")
    @classmethod
    def password_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class UserProfileUpdate(BaseModel):
    username: Optional[str] = None

    @field_validator("username")
    @classmethod
    def username_length(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and (len(v) < 2 or len(v) > 50):
            raise ValueError("Username must be between 2 and 50 characters")
        return v


class PasswordChange(BaseModel):
    old_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def password_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class SessionNoteBundle(BaseModel):
    title: str
    keywords: Optional[list[str]] = None
    content: Optional[str] = None
    transcript: Optional[list] = None
    ppt_images: Optional[list] = None
    layout_blocks: Optional[list[dict]] = None


class NotebookPackage(BaseModel):
    format_version: int = 2
    notebook: NotebookCreate
    sessions: list[SessionNoteBundle] = []
