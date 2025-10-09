import os
from typing import Optional

from dotenv import load_dotenv
from fastapi import Body, FastAPI
from openai import OpenAI
from pydantic import BaseModel
from sqlmodel import Session as DBSession
from sqlmodel import select

from server.db import engine, init_db
from server.models import Faq, Message
from server.models import Session as ChatSession


def normalize(q: str) -> str:
    return " ".join(q.lower().strip().split())


load_dotenv()
client = OpenAI(api_key=os.getenv("DORY_API_KEY"))

# --- Prompt loaders ---
PROMPTS_DIR = "prompts"
COMPACT_PATH = os.path.join(PROMPTS_DIR, "system_dory_compact.md")
FULL_PATH = os.path.join(PROMPTS_DIR, "system_dory_full.md")

DEFAULT_COMPACT = (
    "You are Dory, the Digital Engineering Summit assistant. "
    "Be accurate, concise, friendly; prefer bullets; avoid speculation."
)
DEFAULT_FULL = ""  # full is optional per session-first turn


def _read_text(path: str, fallback: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return fallback


SYSTEM_PROMPT_COMPACT = _read_text(COMPACT_PATH, DEFAULT_COMPACT)
SYSTEM_PROMPT_FULL = _read_text(FULL_PATH, DEFAULT_FULL)

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
    # guard against empty/whitespace input
    if not payload.user_text or not payload.user_text.strip():
        return {
            "session_id": payload.session_id,
            "answer": "🤔 I’m all ears—but I didn’t catch a question. Try typing one in!",
        }

    qn = normalize(payload.user_text)

    with DBSession(engine) as db:
        # --- 0) FAQ EXACT MATCH ---
        faq_row = db.exec(select(Faq).where(Faq.question_norm == qn)).first()
        if faq_row:
            # (optional) create/reuse session + log both sides so history is complete
            if payload.session_id is None:
                s = ChatSession()
                db.add(s)
                db.commit()
                db.refresh(s)
                session_id = s.id
            else:
                session_id = payload.session_id

            db.add(Message(session_id=session_id, role="user", text=payload.user_text))
            db.add(
                Message(session_id=session_id, role="assistant", text=faq_row.answer)
            )
            db.commit()
            return {"session_id": session_id, "answer": faq_row.answer}

        # --- 1) Create or reuse chat session (Step 2: detect first turn) ---
        if payload.session_id is None:
            s = ChatSession()
            db.add(s)
            db.commit()
            db.refresh(s)
            session_id = s.id
            first_turn = True
        else:
            session_id = payload.session_id
            first_turn = False

        # --- 2) Log user message ---
        db.add(Message(session_id=session_id, role="user", text=payload.user_text))
        db.commit()

        # --- 3) Call the model (Step 3: include compact always, full on first turn) ---
        response = None
        try:
            if not CURRENT_MODEL:
                raise RuntimeError("No model configured")

            messages = [{"role": "system", "content": SYSTEM_PROMPT_COMPACT}]
            if first_turn and SYSTEM_PROMPT_FULL:
                messages.append({"role": "system", "content": SYSTEM_PROMPT_FULL})
            messages.append({"role": "user", "content": payload.user_text})

            response = client.responses.create(
                model=CURRENT_MODEL,
                input=messages,
                max_output_tokens=200,
                temperature=0.5,
            )
            answer = response.output_text
        except Exception:
            answer = "Sorry, I had a problem generating a response. Please try again."

        # --- 4) Log assistant message ---
        db.add(Message(session_id=session_id, role="assistant", text=answer))
        db.commit()

        # --- 5) Return ---
        tokens_used = getattr(getattr(response, "usage", None), "total_tokens", None)
        return {
            "session_id": session_id,
            "answer": answer,
            "tokens_used": tokens_used,
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
    """
    limit = max(1, min(limit, 200))

    with DBSession(engine) as db:
        stmt = select(Message)
        if session_id is not None:
            stmt = stmt.where(Message.session_id == session_id)

        stmt = stmt.order_by(Message.id.desc()).limit(limit)
        rows = db.exec(stmt).all()

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
