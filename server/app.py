import os
from pathlib import Path
from typing import Optional

from fastapi import Body, FastAPI, Query, Request, Response
from openai import OpenAI
from pydantic import BaseModel
from rapidfuzz import fuzz, process
from sqlmodel import Session as DBSession
from sqlmodel import select

from server.db import engine, init_db
from server.models import Faq, Message
from server.models import Session as ChatSession
from server.retrieval import RAGIndex, search
from server.settings import Settings

# -------------------- Settings & Clients --------------------

settings = Settings()

# OpenAI client from centralized settings
client = OpenAI(
    api_key=settings.dory_api_key,
    timeout=settings.request_timeout_seconds,
    max_retries=settings.model_max_retries,
)

# Runtime config derived from settings
CURRENT_MODEL = settings.default_model
PROMPT_MODE = settings.prompt_mode  # compact_only | first_turn_full | always_full
FUZZY_MATCH_THRESHOLD = settings.fuzzy_match_threshold

# -------------------- Helpers --------------------


def normalize(q: str) -> str:
    return " ".join(q.lower().strip().split())


def _read_text(path: str, fallback: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return fallback


# Prompt paths and defaults can come from settings (preferred) or env, with sane fallbacks
COMPACT_PATH = getattr(
    settings,
    "compact_prompt_path",
    os.getenv("COMPACT_PROMPT_PATH", "prompts/system_dory_compact.md"),
)
FULL_PATH = getattr(
    settings,
    "full_prompt_path",
    os.getenv("FULL_PROMPT_PATH", "prompts/system_dory_full.md"),
)
DEFAULT_COMPACT = getattr(
    settings,
    "default_compact_prompt",
    "You are Dory, a Digital Engineering assistant for UNSW Canberra. "
    "Be accurate, concise, friendly; prefer bullets; avoid speculation.",
)
DEFAULT_FULL = getattr(settings, "default_full_prompt", "")

SYSTEM_PROMPT_COMPACT = _read_text(COMPACT_PATH, DEFAULT_COMPACT)
SYSTEM_PROMPT_FULL = _read_text(FULL_PATH, DEFAULT_FULL)

# -------------------- Retrieval Index (RAG) --------------------

# RAG: lazy-loaded index
INDEX: RAGIndex | None = None


def get_index() -> RAGIndex | None:
    global INDEX
    if INDEX is None:
        root = Path(__file__).resolve().parents[1]
        try:
            INDEX = RAGIndex.load(root)
        except Exception:
            INDEX = None
    return INDEX


def build_context_block(hits: list[dict]) -> str:
    """
    Turn top-k hits into a compact context block the model can use.
    Keep it brief; include source names for transparency.
    """
    lines = ["# Knowledge Context (Top Matches)"]
    for h in hits:
        src = h["meta"].get("source_name", "source")
        lines.append(f"- [{h['score']:.2f}] {src}: {h['text']}")
    return "\n".join(lines[: 1 + min(len(hits), 5)])


# -------------------- App Init --------------------

app = FastAPI()
init_db()

# -------------------- Routes --------------------


@app.get("/health")
def health():
    return {
        "ok": True,
        "current_model": CURRENT_MODEL,
        "default_model": settings.default_model,
        "prompt_mode": PROMPT_MODE,
        "prompts": {
            "compact_path": COMPACT_PATH,
            "full_path": FULL_PATH,
            "compact_loaded": bool(SYSTEM_PROMPT_COMPACT),
            "full_loaded": bool(SYSTEM_PROMPT_FULL),
        },
    }


class ChatIn(BaseModel):
    user_text: str
    session_id: int | None = None


@app.post("/chat")
def chat(payload: ChatIn, request: Request, response: Response):
    # Guard against empty or whitespace input
    if not payload.user_text or not payload.user_text.strip():
        return {
            "session_id": payload.session_id,
            "answer": "🤔 I’m all ears, but I didn’t catch a question. Try typing one in.",
        }

    qn = normalize(payload.user_text)

    # Try to pick up session_id from cookie if not provided in payload
    if payload.session_id is None:
        cookie_sid = request.cookies.get("dory_session")
        if cookie_sid and cookie_sid.isdigit():
            payload.session_id = int(cookie_sid)

    with DBSession(engine) as db:
        # --- 0) FAQ EXACT MATCH (toggleable via settings) ---
        if settings.enable_faq_cache:
            faq_row = db.exec(select(Faq).where(Faq.question_norm == qn)).first()
            if faq_row:
                # Create or reuse session and log both sides for complete history
                if payload.session_id is None:
                    s = ChatSession()
                    db.add(s)
                    db.commit()
                    db.refresh(s)
                    session_id = s.id
                else:
                    session_id = payload.session_id

                db.add(
                    Message(session_id=session_id, role="user", text=payload.user_text)
                )
                db.add(
                    Message(
                        session_id=session_id,
                        role="assistant",
                        text=faq_row.answer,
                    )
                )
                db.commit()
                return {"session_id": session_id, "answer": faq_row.answer}

            # --- 0.b) FAQ FUZZY MATCH (fallback when exact miss) ---
            # --- 0.b) FAQ FUZZY MATCH (fallback when exact miss) ---

        def is_query_about_site(q_norm: str) -> bool:
            # Only treat as "website" style questions when these hints appear
            site_hints = [
                "website",
                "web site",
                "link",
                "url",
                "register",
                "registration",
                "summit site",
            ]
            return any(h in q_norm for h in site_hints)

        faq_rows = db.exec(select(Faq)).all()
        choices = [row.question_norm for row in faq_rows] if faq_rows else []

        best = None
        if choices:
            match_text, score, _ = process.extractOne(
                qn, choices, scorer=fuzz.token_set_ratio
            )

            # Make fuzzy matching stricter by default
            effective_threshold = max(FUZZY_MATCH_THRESHOLD, 80)

            if score >= effective_threshold:
                candidate = next(
                    (r for r in faq_rows if r.question_norm == match_text), None
                )

                if candidate:
                    # Special guard: do not return the "summit website" FAQ
                    # unless the current query clearly asks about a site/link.
                    website_faq_norm = normalize(
                        "what is the official website for the 2nd australian digital engineering summit?"
                    )
                    if candidate.question_norm == website_faq_norm:
                        if is_query_about_site(qn):
                            best = candidate
                        else:
                            best = None
                    else:
                        best = candidate

        if best:
            # Create/reuse session and log both sides for complete history
            if payload.session_id is None:
                s = ChatSession()
                db.add(s)
                db.commit()
                db.refresh(s)
                session_id = s.id
            else:
                session_id = payload.session_id

            db.add(Message(session_id=session_id, role="user", text=payload.user_text))
            db.add(Message(session_id=session_id, role="assistant", text=best.answer))
            db.commit()
            return {"session_id": session_id, "answer": best.answer}

        # --- 1) Create or reuse chat session; detect first turn ---
        if payload.session_id is None:
            s = ChatSession()
            db.add(s)
            db.commit()
            db.refresh(s)
            session_id = s.id
            response.set_cookie(
                key="dory_session",
                value=str(session_id),
                httponly=True,
            )
            first_turn = True
        else:
            session_id = payload.session_id
            first_turn = False

        # --- 2) Log user message ---
        db.add(Message(session_id=session_id, role="user", text=payload.user_text))
        db.commit()

        # --- 3) Build messages (compact always; full per PROMPT_MODE) and call model ---
        response_obj = None
        try:
            if not CURRENT_MODEL:
                raise RuntimeError("No model configured")

            # RAG: build a context block if enabled and index is available
            context_block = ""
            if settings.enable_rag:
                idx = get_index()
                if idx is not None:
                    # Be compatible with both:
                    # - search(query, settings, idx) -> hits
                    # - search(query, settings, idx) -> (hits, domain)
                    # res = search(payload.user_text, settings, idx)
                    # if isinstance(res, tuple) and len(res) == 2:
                    #     hits, _domain = res
                    # else:
                    #     hits, _domain = res, None

                    # if hits:
                    #     context_block = build_context_block(hits)
                    hits, domain = search(payload.user_text, settings, idx)
                    # Always supply context if domain is "summit" and user refers to program/sessions/day
                    if hits and domain == "summit":
                        context_block = build_context_block(hits)
                    # Only provide DE context if user asks for DE topics — not Summit
                    elif hits and domain == "de":
                        context_block = build_context_block(hits)

            messages = [{"role": "system", "content": SYSTEM_PROMPT_COMPACT}]

            include_full = PROMPT_MODE == "always_full" or (
                PROMPT_MODE == "first_turn_full" and first_turn
            )
            if include_full and SYSTEM_PROMPT_FULL:
                messages.append({"role": "system", "content": SYSTEM_PROMPT_FULL})

            if context_block:
                messages.append({"role": "system", "content": context_block})

            messages.append({"role": "user", "content": payload.user_text})

            response_obj = client.responses.create(
                model=CURRENT_MODEL,
                input=messages,
                temperature=0.5,
            )
            answer = response_obj.output_text

        except Exception as e:
            # Temporary debug to surface the real error:
            answer = f"DEBUG ERROR: {type(e).__name__}: {e}"
            # err = str(e).lower()
            # if "timeout" in err:
            #     answer = (
            #         "Sorry, I am timing out right now. Please try again in a moment."
            #     )
            # elif "rate limit" in err or "too many requests" in err or "429" in err:
            #     answer = (
            #         "I am being rate limited at the moment. Please try again shortly."
            #     )
            # elif "connection" in err or "dns" in err or "resolver" in err:
            #     answer = (
            #         "I am having trouble reaching the model service. Please try again."
            #     )
            # else:
            #     answer = (
            #         "Sorry, I had a problem generating a response. Please try again."
            #     )

        # --- 4) Log assistant message ---
        db.add(Message(session_id=session_id, role="assistant", text=answer))
        db.commit()

        # --- 5) Return ---
        tokens_used = getattr(
            getattr(response_obj, "usage", None),
            "total_tokens",
            None,
        )
        return {
            "session_id": session_id,
            "answer": answer,
            "tokens_used": tokens_used,
        }


# Admin: switch model at runtime
@app.post("/admin/set_model")
def set_model(new_model: str = Body(..., embed=True)):
    """
    Hidden admin-only endpoint to change the model at runtime.
    """
    global CURRENT_MODEL
    CURRENT_MODEL = new_model
    return {"ok": True, "current_model": CURRENT_MODEL}


# Admin: recent logs
@app.get("/admin/logs")
def get_logs(limit: int = 20, session_id: Optional[int] = None):
    """
    Return the most recent messages (default: 20).
    Optional: filter by a specific session_id to see a single conversation.
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


@app.get("/admin/debug_rag")
def debug_rag(q: str = Query(..., description="Raw user query")):
    """
    Inspect RAG routing and top hits for a given query.
    """
    idx = get_index()
    if idx is None:
        return {"ok": False, "reason": "RAG index not loaded"}

    res = search(q, settings, idx)
    if isinstance(res, tuple) and len(res) == 2:
        hits, domain = res
    else:
        hits, domain = res, None

    return {
        "ok": True,
        "query": q,
        "domain": domain,
        "hit_count": len(hits),
        "hits": [
            {
                "score": h["score"],
                "source": h["meta"].get("source_name"),
                "len": len(h["text"]),
                "preview": h["text"][:240],
            }
            for h in hits[:5]
        ],
    }


# Admin: diagnostics snapshot
@app.get("/admin/diagnostics")
def diagnostics():
    return {
        "ok": True,
        "model": CURRENT_MODEL,
        "prompt_mode": PROMPT_MODE,
        "flags": {
            "faq_cache": settings.enable_faq_cache,
            "semantic_cache": settings.enable_semantic_cache,
            "rag": settings.enable_rag,
        },
        "prompts": {
            "compact_path": COMPACT_PATH,
            "full_path": FULL_PATH,
            "compact_loaded": bool(SYSTEM_PROMPT_COMPACT),
            "full_loaded": bool(SYSTEM_PROMPT_FULL),
        },
        "db": settings.database_url,
    }
