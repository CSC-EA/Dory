# server/settings.py
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Read from .env and ignore unknown keys (e.g., uvicorn --host/--port)
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Required
    dory_api_key: str = Field(..., env="DORY_API_KEY")

    # Core config
    default_model: str = Field("gpt-4.1-mini", env="DEFAULT_MODEL")
    database_url: str = Field("sqlite:///./dory.db", env="DATABASE_URL")

    # Prompt behavior
    prompt_mode: str = Field(
        "first_turn_full", env="PROMPT_MODE"
    )  # compact_only | first_turn_full | always_full

    # Feature flags
    enable_faq_cache: bool = Field(True, env="ENABLE_FAQ_CACHE")
    enable_semantic_cache: bool = Field(False, env="ENABLE_SEMANTIC_CACHE")
    enable_rag: bool = Field(False, env="ENABLE_RAG")

    # Optional: allow overriding prompt paths via env (or leave None to use defaults in app.py)
    compact_prompt_path: str | None = Field(None, env="COMPACT_PROMPT_PATH")
    full_prompt_path: str | None = Field(None, env="FULL_PROMPT_PATH")
    default_compact_prompt: str | None = None
    default_full_prompt: str | None = None

    # Fuzzy matching
    fuzzy_match_threshold: int = Field(
        90, env="FUZZY_MATCH_THRESHOLD"
    )  # 0–100; start strict, we can tune later
