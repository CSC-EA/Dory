from datetime import datetime, timezone

from sqlmodel import Field, SQLModel


def now_utc():
    return datetime.now(timezone.utc)


class Message(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    session_id: int
    role: str
    text: str
    created_at: datetime = Field(default_factory=now_utc)


class Session(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    started_at: datetime = Field(default_factory=now_utc)
    last_active_at: datetime = Field(default_factory=now_utc)


class Faq(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    question_norm: str
    answer: str
    created_at: datetime = Field(default_factory=now_utc)
