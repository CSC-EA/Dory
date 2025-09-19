import os
from typing import Optional

from dotenv import load_dotenv
from fastapi import Body, FastAPI
from openai import OpenAI
from pydantic import BaseModel
from sqlmodel import Session as DBSession
from sqlmodel import select

from server.db import engine, init_db
from server.models import Message
from server.models import Session as ChatSession

load_dotenv()
client = OpenAI(api_key=os.getenv("DORY_API_KEY"))

# Model setup
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "gpt-4.1-mini")
CURRENT_MODEL = DEFAULT_MODEL

app = FastAPI()
init_db()


@app.get("/health")
def health():
    return {"ok": True, "current_model": CURRENT_MODEL, "default_model": DEFAULT_MODEL}


# Define the request body
class ChatIn(BaseModel):
    user_text: str
    session_id: int | None = None


# Create the /chat endpoint
@app.post("/chat")
def chat(payload: ChatIn):
    with DBSession(engine) as db:
        # create or reuse chat session
        if payload.session_id is None:
            s = ChatSession()
            db.add(s)
            db.commit()
            db.refresh(s)
            session_id = s.id
        else:
            session_id = payload.session_id

        # log the user message
        db.add(Message(session_id=session_id, role="user", text=payload.user_text))
        db.commit()

    # call the model
    response = client.responses.create(
        model=CURRENT_MODEL,
        input=payload.user_text,
        max_output_tokens=200,
        temperature=0.5,
    )
    answer = response.output_text

    # log the assistant message
    db.add(Message(session_id=session_id, role="assistant", text=answer))
    db.commit

    # Return answer + session_id so client can continue the same convo

    return {
        "session_id": session_id,
        "answer": response.output_text,
        # "model": CURRENT_MODEL,
        "tokens_used": response.usage.total_tokens if response.usage else None,
    }


@app.post("/admin/set_model")
def set_model(new_model: str = Body(..., embed=True)):
    """
    Hidden admin-only endpoint to change the model at runtime.
    Users will never see this in the UI.
    """

    global CURRENT_MODEL
    CURRENT_MODEL = new_model
    return {"ok": True, "current_model": CURRENT_MODEL}


@app.get("/admin/logs")
def get_logs(limit: int = 20, session_id: Optional[int] = None):
    """
    Return the most recent messages (default: 20)
    Optional: filter by a specific session_id to see a single conversation

    Args:
        limit (int, optional): number of messages to retrieve. Defaults to 20.
        session_id (Optional[int], optional): session_id to filter by. Defaults to None.
    """

    limit = max(1, min(limit, 200))

    with DBSession(engine) as db:
        stmt = select(Message)
        if session_id is not None:
            stmt = stmt.where(Message.session_id == session_id)

        # order by newest first using the auto-incrementing ID
        stmt = stmt.order_by(Message.id.desc()).limit(limit)
        rows = db.exec(stmt).all()

        # format minimal, dev-friendly payload
        return [
            {
                "id": m.id,
                "session_id": m.session_id,
                "role": m.role,
                "text": m.text,
                "created_at": m.created_at.isoformat(),
            }
            for m in rows
        ]
