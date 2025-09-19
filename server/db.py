import os

from sqlmodel import SQLModel, create_engine

# Read DB location from .env or default to a local SQLite file
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./dory.db")

# SQLite flag for web app with multiple threads usage
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

# Create a single engine for app to reuse
# echo=False keeps logs quiet; turn it True if you want SQL logs during debugging
engine = create_engine(DATABASE_URL, echo=False, connect_args=connect_args)


# Initialize tables once at setup
def init_db() -> None:
    # Import models inside the function so table classes are registered
    # and to avoid circular imports when app.py imports db.py
    from server import models  # noqa: F401

    SQLModel.metadata.create_all(engine)
