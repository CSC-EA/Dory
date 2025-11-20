# streamlit_app.py

import base64
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import streamlit as st
from openai import OpenAI
from PIL import Image

from server.retrieval import RAGIndex, search
from server.settings import Settings

# ----------------- Global logging helpers -----------------


def get_unsw_logo_html() -> str:
    if not UNSW_LOGO_PATH:
        return ""
    try:
        data = Path(UNSW_LOGO_PATH).read_bytes()
        b64 = base64.b64encode(data).decode("utf-8")

        # Use png as default; if you know it is jpg, change mime type
        return (
            f'<img src="data:image/png;base64,{b64}" '
            f'width="80" style="margin-left: 1rem;">'
        )
    except Exception:
        return ""


@st.cache_resource
def get_session_logs() -> Dict[str, List[Dict[str, Any]]]:
    """
    Store logs per session: {session_id: [log_entries]}
    """
    return {}


def log_event(
    user_text: str,
    answer: str,
    *,
    domain: str | None,
    used_rag: bool,
    manual_override: bool,
    model: str,
    session_id: str | None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cached_tokens: int = 0,
) -> None:
    if not session_id:
        return  # Skip if we did not generate a session id

    entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "user_text": user_text,
        "answer": answer,
        "domain": domain,
        "used_rag": used_rag,
        "manual_override": manual_override,
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cached_tokens": cached_tokens,
    }

    # In memory per session log
    session_logs = get_session_logs()
    if session_id not in session_logs:
        session_logs[session_id] = []
    session_logs[session_id].append(entry)

    # Also append to CSV for persistence
    try:
        import csv

        root = Path(__file__).resolve().parent
        logs_dir = root / "admin" / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        csv_path = logs_dir / "chat_log.csv"

        csv_entry = entry.copy()
        csv_entry["session_id"] = session_id
        csv_entry["ts"] = csv_entry.pop("timestamp")  # match previous ts field

        file_exists = csv_path.exists()
        with csv_path.open("a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "ts",
                    "session_id",
                    "user_text",
                    "answer",
                    "domain",
                    "used_rag",
                    "manual_override",
                    "model",
                    "input_tokens",
                    "output_tokens",
                    "cached_tokens",
                ],
            )
            if not file_exists:
                writer.writeheader()
            writer.writerow(csv_entry)
    except Exception:
        # Never break the app because of logging
        pass


def is_admin() -> bool:
    """
    Return True only if the caller has the correct admin token in the URL.

    Usage:
      1) Set DORY_ADMIN_TOKEN in Streamlit secrets.
      2) Open the app with ?admin=<that_token> in the URL.
    """
    try:
        admin_token = st.secrets.get("DORY_ADMIN_TOKEN")
    except Exception:
        admin_token = None

    if not admin_token:
        return False

    params = st.query_params
    supplied = params.get("admin", "")
    return supplied == admin_token


# ----------------- Settings and clients -----------------


@st.cache_resource
def get_settings() -> Settings:
    """
    Load Settings once, trying to use Streamlit secrets if present,
    otherwise falling back to env/.env.
    """

    try:
        if "DORY_API_KEY" in st.secrets:
            os.environ["DORY_API_KEY"] = st.secrets["DORY_API_KEY"]
    except Exception:
        pass

    settings = Settings()
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


def _normalize(text: str) -> str:
    return " ".join(text.lower().strip().split())


def _looks_like_summit_question(q: str) -> bool:
    """
    Textual hints that the user is talking about the Summit.
    """
    q = q.lower()
    keywords = [
        "summit",
        "digital engineering summit",
        "ades",
        "conference program",
        "summit program",
        "summit agenda",
    ]
    return any(k in q for k in keywords)


def _classify_program_request(q: str) -> str | None:
    """
    Return "day1", "day2", "both" or None.

    Only checks for program-like queries, does not decide
    whether this is Summit or general DE.
    """
    q = q.lower()

    # Must look like a program or schedule question
    if not any(
        w in q
        for w in [
            "program",
            "agenda",
            "schedule",
            "what is on",
            "what is happening",
            "line up",
            "sessions on",
            "workshop",
            "session",
        ]
    ):
        return None

    # Special case: Braden's workshop is on Day 2
    if "braden" in q and "workshop" in q:
        return "day2"

    day1_tokens = ["day 1", "day one", "monday", "24"]
    day2_tokens = ["day 2", "day two", "tuesday", "25"]

    day1_hit = any(t in q for t in day1_tokens)
    day2_hit = any(t in q for t in day2_tokens)

    if day1_hit and not day2_hit:
        return "day1"
    if day2_hit and not day1_hit:
        return "day2"
    if day1_hit and day2_hit:
        return "both"

    # Program-ish but no explicit day
    return "both"


def try_manual_program_answer(
    user_text: str,
    in_summit_context: bool,
) -> tuple[str | None, str | None]:
    """
    Manual override and context builder for Summit program questions.

    Returns:
        (answer, kind)

        - answer: the program text or None
        - kind:
            "program"  -> specific day program (day1 or day2)
            "summary"  -> both days summary
            None       -> no manual handling
    """
    q = _normalize(user_text)

    # 1) Is this a program-like question at all?
    day_type = _classify_program_request(q)
    if day_type is None:
        return None, None

    # 2) Decide if we should treat this as Summit related
    is_explicit_summit = _looks_like_summit_question(q)
    is_summit = is_explicit_summit or in_summit_context

    if not is_summit:
        # It is a program question, but we do not have evidence
        # that it is about the Summit, so let the model handle it.
        return None, None

    # 3) Now we know: program-ish and Summit context

    day1_text = (
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
    )

    day2_text = (
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

    both_text = (
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
        "For any last minute updates or room details, please refer to the official Summit website: "
        "https://consec.eventsair.com/2nd-australian-digital-engineering-summit"
    )

    if day_type == "day1":
        return day1_text, "program"
    if day_type == "day2":
        return day2_text, "program"

    # "both" or generic program question in Summit context
    return both_text, "summary"


# ----------------- Icon helper -----------------


@st.cache_resource
def load_icons():
    """
    Load Dory icon as a PIL image for page_icon, and return
    the filesystem path of the UNSW logo for later embedding.
    """
    root = Path(__file__).resolve().parent

    dory_icon = None
    unsw_logo_path = None

    try:
        dory_icon = Image.open(root / "static" / "dory.png")
    except Exception:
        try:
            dory_icon = Image.open(root / "static" / "dory.jpg")
        except Exception:
            dory_icon = None

    # You only need the path for UNSW logo, we will embed it as base64
    for name in ["unsw_logo.png", "unsw_logo.jpg", "unsw.png", "unsw.jpg"]:
        candidate = root / "static" / name
        if candidate.exists():
            unsw_logo_path = str(candidate)
            break

    return dory_icon, unsw_logo_path


DORY_ICON, UNSW_LOGO_PATH = load_icons()


def apply_custom_styling():
    custom_css = """
    <style>
        html, body {
            background-color: #f8f9fa !important;
        }

        [data-testid="stAppViewContainer"] {
            background-color: #f8f9fa !important;
        }

        [data-testid="stAppViewContainer"] > .main {
            background-color: #f8f9fa !important;
        }

        [data-testid="block-container"] {
            background-color: #f8f9fa !important;
        }

        [data-testid="stSidebar"] {
            background-color: #ffffff !important;
        }

        .gold-header {
            background-color: #FFCD00;
            padding: 1.5rem;
            border-radius: 0.5rem;
            margin-bottom: 2rem;
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
        }

        .header-title {
            color: #000000;
            margin: 0;
            font-size: 2.5rem;
            font-weight: 700;
        }

        .logo-container {
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100%;
        }
    </style>
    """
    st.markdown(custom_css, unsafe_allow_html=True)


# --- Analytics bar ---


def render_analytics_sidebar() -> None:
    if not is_admin():
        return

    session_logs = get_session_logs()

    st.sidebar.header("Analytics")

    # Overall stats
    total_sessions = len(session_logs)
    total_turns = sum(len(logs) for logs in session_logs.values())

    st.sidebar.subheader("Overview")
    st.sidebar.write(f"Total sessions: {total_sessions}")
    st.sidebar.write(f"Total turns: {total_turns}")

    if not session_logs:
        st.sidebar.write("No session data yet.")
        return

    # Session selector
    st.sidebar.subheader("Session details")

    sessions = sorted(session_logs.keys(), reverse=True)
    selected_session = st.sidebar.selectbox(
        "Select session",
        sessions,
        format_func=lambda x: f"Session {x[:8]}... ({len(session_logs[x])} turns)",
    )

    if not selected_session:
        return

    session_data = session_logs[selected_session]
    # Token stats per session
    total_in = sum((r.get("input_tokens") or 0) for r in session_data)
    total_out = sum((r.get("output_tokens") or 0) for r in session_data)
    total_cached = sum((r.get("cached_tokens") or 0) for r in session_data)

    st.sidebar.write(f"Input tokens: {total_in}")
    st.sidebar.write(f"Output tokens: {total_out}")
    st.sidebar.write(f"Cached tokens: {total_cached}")

    st.sidebar.write(f"Session id: `{selected_session}`")
    st.sidebar.write(f"Turns in session: {len(session_data)}")

    # Session specific stats
    de_count = sum(1 for r in session_data if r.get("domain") == "de")
    summit_count = sum(1 for r in session_data if r.get("domain") == "summit")
    override_count = sum(1 for r in session_data if r.get("manual_override"))
    rag_count = sum(1 for r in session_data if r.get("used_rag"))

    st.sidebar.write(f"DE queries: {de_count}")
    st.sidebar.write(f"Summit queries: {summit_count}")
    st.sidebar.write(f"Manual overrides: {override_count}")
    st.sidebar.write(f"RAG used: {rag_count}")

    # # Conversation flow preview
    # st.sidebar.subheader("Conversation flow")
    # for i, turn in enumerate(session_data):
    #     preview = (turn["user_text"] or "")[:60]
    #     st.sidebar.write(f"{i + 1}. {preview}...")

    # Download buttons
    import json

    col1, col2 = st.sidebar.columns(2)

    with col1:
        st.download_button(
            "This session (JSON)",
            data=json.dumps(session_data, ensure_ascii=False, indent=2),
            file_name=f"dory_session_{selected_session[:8]}.json",
            mime="application/json",
        )

    with col2:
        all_sessions_data = {
            "sessions": session_logs,
            "summary": {
                "total_sessions": total_sessions,
                "total_turns": total_turns,
                "generated_at": datetime.utcnow().isoformat(),
            },
        }
        st.download_button(
            "All sessions",
            data=json.dumps(all_sessions_data, ensure_ascii=False, indent=2),
            file_name="dory_all_sessions.json",
            mime="application/json",
        )


# ----------------- Page config -----------------

st.set_page_config(
    page_title="Dory - Digital Engineering Assistant",
    page_icon=DORY_ICON if DORY_ICON is not None else "🤖",
    layout="centered",
)

render_analytics_sidebar()

# Apply custom styling
apply_custom_styling()

# UNSW Gold header with title and logo INSIDE
header_html = f"""
<div class="gold-header">
    <div style="display: flex; justify-content: space-between; align-items: center;">
        <div>
            <h1 class="header-title">Dory - Digital Engineering Assistant</h1>
        </div>
        <div class="logo-container">
            {get_unsw_logo_html()}
        </div>
    </div>
</div>
"""
st.markdown(header_html, unsafe_allow_html=True)


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

if "session_id" not in st.session_state:
    # Random opaque id per Streamlit session
    st.session_state.session_id = uuid.uuid4().hex
if "summit_mode" not in st.session_state:
    # Becomes True once the user clearly asks about the Summit
    st.session_state.summit_mode = False


# ----------------- Core generation logic -----------------


def generate_answer(user_text: str) -> str:
    # Normalized lowercased version for heuristics
    q_lower = _normalize(user_text)

    # Update summit conversation context flag
    if _looks_like_summit_question(q_lower):
        st.session_state.summit_mode = True

    # 1) Manual override and context for Summit program questions
    manual_answer, manual_kind = try_manual_program_answer(
        user_text,
        st.session_state.summit_mode,
    )

    # Heuristic: pure program questions get the manual answer directly
    # while recommendation or preference questions use manual as context.
    is_recommendation = any(
        kw in q_lower
        for kw in [
            "which ",
            "recommend",
            "should i",
            "good for me",
            "suitable",
            "best",
            "what should i attend",
        ]
    )

    if manual_answer and manual_kind == "program" and not is_recommendation:
        # Direct schedule answer, no model call
        log_event(
            user_text=user_text,
            answer=manual_answer,
            domain="summit",
            used_rag=False,
            manual_override=True,
            model="manual",
            session_id=st.session_state.get("session_id"),
            input_tokens=0,
            output_tokens=0,
            cached_tokens=0,
        )
        return manual_answer

    # 2) Normal generation path
    settings = get_settings()
    client = get_openai_client(settings)
    index = get_rag_index()
    compact_prompt, full_prompt = get_prompts(settings)

    is_first_turn = len(st.session_state.messages) == 0

    # 3) RAG context
    context_block = ""
    domain = None
    used_rag = False

    # Bias search toward summit documents when applicable
    summit_hint = (
        "summit"
        if st.session_state.summit_mode or _looks_like_summit_question(q_lower)
        else None
    )

    if settings.enable_rag and index is not None:
        try:
            hits, domain = search(
                user_text,
                settings,
                index,
                domain_hint=summit_hint,
            )
            if hits:
                context_block = build_context_block(hits)
                used_rag = True
        except Exception:
            context_block = ""
            domain = None
            used_rag = False

    # 4) Build messages with system prompts, manual program context, RAG context and history
    messages: List[Dict[str, str]] = []
    messages.append({"role": "system", "content": compact_prompt})

    include_full = False
    if settings.prompt_mode == "always_full":
        include_full = True
    elif settings.prompt_mode == "first_turn_full" and is_first_turn:
        include_full = True

    if include_full and full_prompt:
        messages.append({"role": "system", "content": full_prompt})

    # If we have a manual Summit program text, feed it as trusted context
    if manual_answer:
        messages.append(
            {
                "role": "system",
                "content": "Summit program context:\n" + manual_answer,
            }
        )

    if context_block:
        messages.append({"role": "system", "content": context_block})

    # Add recent chat history (including the current user turn that was
    # already appended to st.session_state.messages in the UI code)
    history: List[Dict[str, str]] = []
    for msg in st.session_state.messages[-10:]:
        if msg["role"] in ("user", "assistant"):
            history.append({"role": msg["role"], "content": msg["content"]})

    # Fallback in case history is empty or last message is not the current user text
    if not history or history[-1]["role"] != "user":
        history.append({"role": "user", "content": user_text})

    messages.extend(history)

    # 5) Call model
    input_tokens = output_tokens = cached_tokens = 0

    try:
        resp = client.responses.create(
            model=settings.default_model,
            input=messages,
            temperature=0.5,
        )
        answer = resp.output_text

        usage = getattr(resp, "usage", None)
        if usage is not None:
            input_tokens = getattr(usage, "input_tokens", 0)
            output_tokens = getattr(usage, "output_tokens", 0)
            cached_tokens = getattr(usage, "cached_input_tokens", 0)
    except Exception as e:
        answer = f"Sorry, I had a problem generating a response. ({e})"

    # 6) Log turn for analytics
    log_event(
        user_text=user_text,
        answer=answer,
        domain=domain,
        used_rag=used_rag,
        manual_override=False,
        model=settings.default_model,
        session_id=st.session_state.get("session_id"),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_tokens=cached_tokens,
    )

    return answer


# ----------------- Chat UI -----------------

cols = st.columns([1, 3])
with cols[0]:
    if st.button("Clear conversation"):
        st.session_state.messages = []
        st.rerun()

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

user_input = st.chat_input("Ask me anything about Digital Engineering or the Summit...")

if user_input:
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    answer = generate_answer(user_input)

    st.session_state.messages.append({"role": "assistant", "content": answer})
    with st.chat_message("assistant"):
        st.markdown(answer)
