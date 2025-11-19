# streamlit_app.py

import os
from pathlib import Path
from typing import Any, Dict, List

import streamlit as st
from openai import OpenAI

from server.retrieval import RAGIndex, search
from server.settings import Settings


def debug_environment():
    """Temporary debug function to check environment variables"""
    st.sidebar.title("🔧 Debug Info")
    st.sidebar.write("Checking Streamlit secrets and environment...")

    # Check Streamlit secrets
    try:
        secrets_keys = list(st.secrets.keys())
        st.sidebar.write("Secrets keys:", secrets_keys)
        if "DORY_API_KEY" in st.secrets:
            st.sidebar.success("✅ DORY_API_KEY found in secrets!")
            st.sidebar.write(
                "Key value (first 10 chars):", st.secrets["DORY_API_KEY"][:10] + "..."
            )
        else:
            st.sidebar.error("❌ DORY_API_KEY NOT in secrets!")
    except Exception as e:
        st.sidebar.error(f"Secrets error: {e}")

    # Check environment variables
    env_vars = [
        k
        for k in os.environ.keys()
        if any(word in k for word in ["DORY", "API", "KEY"])
    ]
    st.sidebar.write("Relevant env vars:", env_vars)

    # Show all secrets for comprehensive debugging
    st.sidebar.write("All secrets:", dict(st.secrets))


# ----------------- Settings and clients -----------------


@st.cache_resource
def get_settings() -> Settings:
    """
    Load Settings once, trying to use Streamlit secrets if present,
    otherwise falling back to env/.env.
    """

    # Call debug function
    debug_environment()

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
