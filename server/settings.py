from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    dory_api_key: str = Field(..., env="DORY_API_KEY")
    default_model: str = Field("gpt-4.1-mini", env="DEFAULT_MODEL")
    database_url: str = Field("sqlite:///./dory.db", env="DATABASE_URL")
    prompt_mode: str = Field(
        "first_turn_full", env="PROMPT_MODE"
    )  # compact_only|first_turn_full|always_full
    enable_faq_cache: bool = Field(True, env="ENABLE_FAQ_CACHE")
    enable_semantic_cache: bool = Field(False, env="ENABLE_SEMANTIC_CACHE")
    enable_rag: bool = Field(False, env="ENABLE_RAG")

    class Config:
        env_file = ".env"
