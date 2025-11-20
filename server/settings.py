# server/settings.py
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Read from .env and ignore unknown keys (e.g., uvicorn --host/--port)
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Required
    dory_api_key: str = Field(..., env="DORY_API_KEY")

    # Core configs
    default_model: str = Field("gpt-4.1-mini", env="DEFAULT_MODEL")
    database_url: str = Field("sqlite:///./dory.db", env="DATABASE_URL")

    # Prompt behavior
    prompt_mode: str = Field(
        "always_full", env="PROMPT_MODE"
    )  # compact_only | first_turn_full | always_full

    # Feature flags
    enable_faq_cache: bool = Field(True, env="ENABLE_FAQ_CACHE")
    enable_semantic_cache: bool = Field(False, env="ENABLE_SEMANTIC_CACHE")
    enable_rag: bool = Field(True, env="ENABLE_RAG")

    # Optional: allow overriding prompt paths via env (or leave None to use defaults in app.py)
    compact_prompt_path: str | None = Field(None, env="COMPACT_PROMPT_PATH")
    full_prompt_path: str | None = Field(None, env="FULL_PROMPT_PATH")
    default_compact_prompt: str | None = None
    default_full_prompt: str | None = None

    # Fuzzy matching
    fuzzy_match_threshold: int = Field(90, env="FUZZY_MATCH_THRESHOLD")  # 0–100

    # Model call hardening
    request_timeout_seconds: int = Field(25, env="REQUEST_TIMEOUT_SECONDS")
    model_max_retries: int = Field(2, env="MODEL_MAX_RETRIES")

    # Embeddings (generic defaults)
    embedding_model: str = Field("text-embedding-3-small", env="EMBEDDING_MODEL")
    embed_batch: int = Field(64, env="EMBED_BATCH")

    # RAG tuning
    rag_min_score: float = Field(0.4, env="RAG_MIN_SCORE")  # 0–1, higher = stricter
    rag_margin: float = Field(0.05, env="RAG_MARGIN")
    rag_top_k: int = Field(5, env="RAG_TOP_K")

    # Provider-agnostic embedding settings
    # "openai" | "hf" | "ollama" | "http_compatible"
    embedding_provider: str = Field("openai", env="EMBEDDING_PROVIDER")

    # OpenAI / HTTP-compatible endpoints
    embedding_endpoint: str | None = Field(
        None, env="EMBEDDING_ENDPOINT"
    )  # e.g. http://localhost:8001/v1
    embedding_api_key: str | None = Field(
        None, env="EMBEDDING_API_KEY"
    )  # if different from DORY_API_KEY

    # Hugging Face (sentence-transformers) local
    hf_model: str = Field("BAAI/bge-small-en-v1.5", env="HF_MODEL")
    hf_device: str = Field("cpu", env="HF_DEVICE")  # "cpu" | "cuda" | "mps"
    hf_pooling: str = Field("mean", env="HF_POOLING")  # "mean" | "cls"
    hf_normalize: bool = Field(True, env="HF_NORMALIZE")

    # Ollama local
    ollama_host: str = Field("http://localhost:11434", env="OLLAMA_HOST")
    ollama_model: str = Field("nomic-embed-text", env="OLLAMA_MODEL")

    # Instruction prefixes (applied outside providers)
    doc_prefix: str = Field("passage: ", env="DOC_PREFIX")  # for BGE/E5/GTE/Nomic docs
    query_prefix: str = Field("query: ", env="QUERY_PREFIX")
