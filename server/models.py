# server/models.py
from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class ChatLog(SQLModel, table=True):
    __tablename__ = "chat_logs"
    __table_args__ = {"extend_existing": True}

    id: Optional[int] = Field(default=None, primary_key=True)

    ts: datetime = Field(default_factory=datetime.utcnow)
    session_id: str = Field(index=True)

    user_text: str
    answer: str

    domain: Optional[str] = Field(default=None, index=True)
    used_rag: bool = Field(default=False)
    manual_override: bool = Field(default=False)
    model: str = Field(index=True)

    input_tokens: int = Field(default=0)
    output_tokens: int = Field(default=0)
    cached_tokens: int = Field(default=0)
