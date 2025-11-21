from datetime import datetime

from sqlmodel import Field, SQLModel


class ChatLog(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)

    ts: datetime
    session_id: str

    user_text: str
    answer: str

    domain: str | None = None
    used_rag: bool = False
    manual_override: bool = False
    model: str

    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
