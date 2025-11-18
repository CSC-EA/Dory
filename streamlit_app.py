# streamlit_app.py
import os
from pathlib import Path

import requests
import streamlit as st

# ----------------- Config helpers -----------------


def get_api_base() -> str:
    """
    Determine the base URL for the Dory backend API.

    Priority:
      1) st.secrets["DORY_API_BASE_URL"] (for Streamlit Cloud / prod)
      2) env var DORY_API_BASE_URL
      3) default local FastAPI server: http://127.0.0.1:8000
    """
    try:
        if hasattr(st, "secrets") and "DORY_API_BASE_URL" in st.secrets:
            return st.secrets["DORY_API_BASE_URL"]
    except Exception:
        # No secrets file or no key; fall back to env
        pass

    env_val = os.getenv("DORY_API_BASE_URL")
    if env_val:
        return env_val.strip()

    # Local default
    return "http://127.0.0.1:8000"


API_BASE = get_api_base()


# ----------------- Page setup -----------------


def get_icon_path() -> str | None:
    """
    Try to locate a UNSW/Dory icon.

    Checks, in order:
      - ./static/dory_icon.png
      - ./static/UNSW_Canberra_logo.png
      - ./frontend/unsw_icon.(png|jpg|ico) as fallback
    """
    root = Path(__file__).resolve().parent

    candidates = [
        root / "static" / "dory_icon.png",
        root / "static" / "UNSW_Canberra_logo.png",
        root / "frontend" / "unsw_icon.png",
        root / "frontend" / "unsw_icon.jpg",
        root / "frontend" / "unsw_icon.ico",
    ]

    for p in candidates:
        if p.exists():
            return str(p)

    return None


ICON_PATH = get_icon_path()

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
- navigate information about the **2nd Australian Digital Engineering Summit** (agenda, venue, workshops, speakers, etc.)

Unlike other Dorys, I do not forget - but I *might* hallucinate.
I try my best not to, but it is kind of genetic for my breed, so please double-check important details against official sources when it really matters.
"""
)

st.markdown("---")


# ----------------- Session state -----------------

if "messages" not in st.session_state:
    # Chat history for the UI: list of {"role": "user"|"assistant", "content": str}
    st.session_state.messages = []

if "session_id" not in st.session_state:
    # Backend conversation id (FastAPI /chat session_id)
    st.session_state.session_id = None


# ----------------- Backend interaction -----------------


def send_to_backend(user_text: str) -> str:
    """
    Send a message to the FastAPI backend and return the assistant's answer.
    Maintains conversation context by passing and updating `session_id`.
    """
    payload = {"user_text": user_text}

    if st.session_state.session_id is not None:
        payload["session_id"] = st.session_state.session_id

    try:
        resp = requests.post(f"{API_BASE}/chat", json=payload, timeout=30)
    except requests.exceptions.RequestException as e:
        return f"Sorry, I could not reach the Dory backend ({e}). Please try again in a moment."

    if resp.status_code != 200:
        return (
            f"Backend returned an error (status {resp.status_code}). Please try again."
        )

    data = resp.json()

    st.session_state.session_id = data.get("session_id", st.session_state.session_id)

    return data.get("answer", "")


# ----------------- Chat UI -----------------


cols = st.columns([1, 3])
with cols[0]:
    if st.button("Clear conversation"):
        st.session_state.messages = []
        st.session_state.session_id = None
        st.rerun()

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

user_input = st.chat_input("Ask me anything about Digital Engineering or the Summit...")

if user_input:
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    answer = send_to_backend(user_input)

    st.session_state.messages.append({"role": "assistant", "content": answer})
    with st.chat_message("assistant"):
        st.markdown(answer)
