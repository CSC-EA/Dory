import os

from sqlmodel import Session, SQLModel, create_engine

from .settings import Settings

# Read DATABASE_URL from Settings (which reads from Streamlit Secrets)
settings = Settings()

# Engine for Neon Postgres
engine = create_engine(
    settings.database_url,
    echo=False,  # Set to True for debugging SQL queries
)


def init_db() -> None:
    """
    Create tables if they do not exist.
    Call this once at app startup.
    """
    SQLModel.metadata.create_all(engine)


def get_session() -> Session:
    """
    Get a database session.
    Use `with get_session() as db: ...`
    """
    return Session(engine)
