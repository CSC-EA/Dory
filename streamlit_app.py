# streamlit_app.py

import os
from pathlib import Path
from typing import Any, Dict, List

import streamlit as st
from openai import OpenAI

from server.retrieval import RAGIndex, search
from server.settings import Settings

# ----------------- Settings and clients -----------------


@st.cache_resource
def get_settings() -> Settings:
    """
    Load Settings once, trying to use Streamlit secrets if present,
    otherwise falling back to env/.env.
    """

    try:
        # This will raise if secrets are not configured (local dev case)
        if "DORY_API_KEY" in st.secrets:
            os.environ["DORY_API_KEY"] = st.secrets["DORY_API_KEY"]
    except Exception:
        # No secrets file or key, env/.env will be used by Settings
        pass

    settings = Settings()
    # Ensure RAG is enabled for this Streamlit-only deployment
    settings.enable_rag = True
    return settings


@st.cache_resource
def get_openai_client(settings: Settings) -> OpenAI:
    return OpenAI(
        api_key=settings.dory_api_key,
        timeout=settings.request_timeout_seconds,
        max_retries=settings.model_max_retries,
    )


@st.cache_resource
def get_rag_index() -> RAGIndex | None:
    """
    Load the dual corpus RAG index (DE + Summit) from knowledge/web_cache.
    """
    root = Path(__file__).resolve().parent
    try:
        return RAGIndex.load(root)
    except Exception:
        return None


# ----------------- Prompt loading -----------------


def _read_text(path: str, fallback: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return fallback


@st.cache_data
def get_prompts(settings: Settings) -> tuple[str, str]:
    """
    Load compact and full system prompts from disk, with sane defaults.
    """
    compact_path = settings.compact_prompt_path or os.getenv(
        "COMPACT_PROMPT_PATH", "prompts/system_dory_compact.md"
    )
    full_path = settings.full_prompt_path or os.getenv(
        "FULL_PROMPT_PATH", "prompts/system_dory_full.md"
    )

    default_compact = settings.default_compact_prompt or (
        "You are Dory, a Digital Engineering assistant for UNSW Canberra. "
        "Be accurate, concise, friendly; prefer bullets; avoid speculation."
    )
    default_full = settings.default_full_prompt or ""

    compact = _read_text(compact_path, default_compact)
    full = _read_text(full_path, default_full)
    return compact, full


# ----------------- RAG context builder -----------------


def build_context_block(hits: List[Dict[str, Any]]) -> str:
    """
    Turn top-k hits into a compact context block the model can use.
    Keep it brief; include source names for transparency.
    """
    if not hits:
        return ""
    lines = ["# Knowledge Context (Top Matches)"]
    for h in hits[:5]:
        src = h["meta"].get("source_name", "source")
        lines.append(f"- [{h['score']:.2f}] {src}: {h['text']}")
    return "\n".join(lines)


# ----------------- Manual override for summit program -----------------
def try_manual_program_answer(user_text: str) -> str | None:
    """
    Manual override for Summit program questions.
    Uses the official Day 1 and Day 2 program documents.
    Returns a formatted answer string or None if no override applies.
    """
    q = user_text.lower()

    # Simple intent checks
    is_summit = "summit" in q or "digital engineering summit" in q
    asks_program = any(w in q for w in ["program", "agenda", "schedule", "what is on"])

    asks_day1 = any(w in q for w in ["day 1", "day one", "monday", "24", 24])
    asks_day2 = any(w in q for w in ["day 2", "day two", "tuesday", "25", 25])

    # Day 1 only
    if is_summit and asks_program and asks_day1:
        return (
            "Here is the program for Day 1 of the 2nd Australian Digital Engineering Summit "
            "(Monday 24 November 2025, National Convention Centre Canberra):\n\n"
            "8:00 - 9:00\n"
            "  Registration opens\n\n"
            "9:00 - 10:30  Summit Opening and SESSION 1: Engineering Digital Transformation\n"
            "  - Welcome to Country and Welcome to the Summit: Prof Sondoss Elsawah\n"
            "  - Welcome to UNSW Canberra and Opening: Prof Emma Sparks\n"
            "  - Speakers: Mr Terry Saunder, Dr Stephen Craig, Ms Kerry Lunney\n"
            "  - Panel: Transformation Through Digital Engineering: How Will We Get There?\n"
            "    Facilitator: Ms Rachel Hatton\n\n"
            "10:30 - 11:00\n"
            "  Morning tea and networking\n\n"
            "11:05 - 12:30  SESSION 2: Driving Innovations Across the Digital Engineering Ecosystem\n"
            "  - Speakers: Dr Barclay Brown, Mr Thomas A. McDermott, Dr Sam Davey, "
            "BRIG GEN (ret) Steve Bleymaier\n"
            "  - Panel: Building the Digital Engineering Ecosystem - "
            "Prioritising Technological and Innovation Investments\n"
            "    Facilitator: Mr Allan Dundas\n\n"
            "12:30 - 13:30\n"
            "  Lunch and networking\n\n"
            "13:35 - 14:50  SESSION 3: Driving the Adoption of Digital Engineering - "
            "Recruitment, Skillsets and Career Pathways\n"
            "  - Speakers: Ms Lucy Poole, Prof Sondoss Elsawah, BRIG Jennifer Harris\n"
            "  - Panel: Creating the Digital Workforce: What Are Opportunities and Challenges?\n"
            "    Facilitator: Ms Heather Nicoll\n\n"
            "14:55 - 15:30\n"
            "  Afternoon tea and networking\n\n"
            "15:35 - 17:00  SESSION 4: Digital Engineering - Creating and Realizing New Value "
            "and Summit Closing\n"
            "  - Speakers: Mr Jawahar Bhalla, Mr Adrian Piani, CDRE Andrew Macalister\n"
            "  - Panel: How Can Organisations Use Digital Engineering to Drive Value Across "
            "the Whole Lifecycle?\n"
            "    Facilitator: Ms Kerry Lunney\n\n"
            "Summit managers: Consec - Conference and Event Management "
            "(adesummit@consec.com.au, +61 2 6252 1200)."
        )

    # Day 2 only
    if is_summit and asks_program and asks_day2:
        return (
            "Here is the program for Day 2 of the 2nd Australian Digital Engineering Summit "
            "(Tuesday 25 November 2025):\n\n"
            "Online delivery:\n"
            "  9:00 - 13:00  Applications of Generative AI with Large Language Models (online)\n"
            "    Facilitator: Dr Barclay Brown\n\n"
            "  13:00 - 16:00  Mission Engineering Primer (online)\n"
            "    Facilitator: Dr Braden McGrath\n\n"
            "In person delivery:\n"
            "  9:00 - 12:00  Mission Engineering Advanced Workshop (in person)\n"
            "    Facilitator: Dr Braden McGrath\n\n"
            "  13:00 - 15:00  Low Cost Digitisation for SMEs: Unlocking Industry 4.0 Benefits (in person)\n"
            "    Facilitators: Dr Matthew Doolan and Dr Michael Stevens\n\n"
            "Summit managers: Consec - Conference and Event Management "
            "(adesummit@consec.com.au, +61 2 6252 1200)."
        )

    # Full two day program
    if is_summit and asks_program and not (asks_day1 or asks_day2):
        return (
            "Here is a summary of the two day program for the 2nd Australian Digital Engineering Summit:\n\n"
            "Day 1 - Monday 24 November 2025 (National Convention Centre Canberra)\n"
            "  - Registration from 8:00\n"
            "  - Summit Opening and Session 1: Engineering Digital Transformation\n"
            "  - Session 2: Driving Innovations Across the Digital Engineering Ecosystem\n"
            "  - Session 3: Driving the Adoption of Digital Engineering - Recruitment, Skillsets "
            "and Career Pathways\n"
            "  - Session 4: Digital Engineering - Creating and Realizing New Value and Summit closing\n"
            "  - Morning tea, lunch and afternoon tea with networking\n\n"
            "Day 2 - Tuesday 25 November 2025\n"
            "  Online:\n"
            "    - Applications of Generative AI with Large Language Models (morning)\n"
            "    - Mission Engineering Primer (afternoon)\n"
            "  In person:\n"
            "    - Mission Engineering Advanced Workshop (morning)\n"
            "    - Low Cost Digitisation for SMEs: Unlocking Industry 4.0 Benefits (afternoon)\n\n"
            "For any last minute updates or room details, please refer to the official Summit website."
        )

    return None


# ----------------- Icon helper -----------------


def get_icon_path() -> str | None:
    root = Path(__file__).resolve().parent
    candidates = [
        root / "static" / "UNSW_Canberra_logo.png",
        root / "static" / "dory_icon.png",
        root / "frontend" / "unsw_icon.png",
        root / "frontend" / "unsw_icon.jpg",
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    return None


ICON_PATH = get_icon_path()

# ----------------- Page config -----------------

st.set_page_config(
    page_title="Dory - Digital Engineering Assistant",
    page_icon=ICON_PATH,
    layout="centered",
)

st.title("Dory - Digital Engineering Assistant")

if ICON_PATH:
    st.image(ICON_PATH, width=64)

st.write(
    """
I am Dory, your assistant for **Digital Engineering (DE)**. I can help you:
- explore digital engineering concepts and practices  
- understand how DE is applied in projects and organisations  
- navigate information about the **2nd Australian Digital Engineering Summit** when you ask about it  

Unlike other Dorys, I do not forget, but I *might* hallucinate.
I try my best not to, but it is kind of genetic for my breed, so please double check important details against official sources when it really matters.
"""
)

st.markdown("---")

# ----------------- Session state -----------------

if "messages" not in st.session_state:
    st.session_state.messages = []

# ----------------- Core generation logic -----------------


def generate_answer(user_text: str) -> str:
    # Manual override for Summit program questions
    manual = try_manual_program_answer(user_text)
    if manual is not None:
        return manual

    settings = get_settings()
    client = get_openai_client(settings)
    index = get_rag_index()
    compact_prompt, full_prompt = get_prompts(settings)

    # Decide if this is the first turn for prompt_mode logic
    is_first_turn = len(st.session_state.messages) == 0

    messages: List[Dict[str, str]] = []
    messages.append({"role": "system", "content": compact_prompt})

    include_full = False
    if settings.prompt_mode == "always_full":
        include_full = True
    elif settings.prompt_mode == "first_turn_full" and is_first_turn:
        include_full = True

    if include_full and full_prompt:
        messages.append({"role": "system", "content": full_prompt})

    # RAG context
    context_block = ""
    if settings.enable_rag and index is not None:
        try:
            hits, domain = search(
                user_text,
                settings,
                index,
                domain_hint=None,
            )
            if hits:
                context_block = build_context_block(hits)
        except Exception:
            context_block = ""

    if context_block:
        messages.append({"role": "system", "content": context_block})

    messages.append({"role": "user", "content": user_text})

    try:
        resp = client.responses.create(
            model=settings.default_model,
            input=messages,
            temperature=0.5,
        )
        return resp.output_text
    except Exception as e:
        return f"Sorry, I had a problem generating a response. ({e})"


# ----------------- Chat UI -----------------

cols = st.columns([1, 3])
with cols[0]:
    if st.button("Clear conversation"):
        st.session_state.messages = []
        st.rerun()

# Show history
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# Input
user_input = st.chat_input("Ask me anything about Digital Engineering or the Summit...")

if user_input:
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    answer = generate_answer(user_input)

    st.session_state.messages.append({"role": "assistant", "content": answer})
    with st.chat_message("assistant"):
        st.markdown(answer)
