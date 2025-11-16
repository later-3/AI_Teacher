from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlmodel import Session, SQLModel, create_engine

from .config import get_settings

settings = get_settings()

# Ensure the parent directory exists for sqlite database.
db_path = settings.database_url.replace("sqlite:///", "")
if settings.database_url.startswith("sqlite:///"):
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(settings.database_url, echo=False, future=True)


def init_db() -> None:
    """Create database tables."""
    from . import models  # noqa: F401  # Ensure models are imported

    SQLModel.metadata.create_all(engine)


def get_session() -> Iterator[Session]:
    """FastAPI dependency that yields a session."""
    with Session(engine) as session:
        yield session


@contextmanager
def session_context() -> Iterator[Session]:
    """Context manager for background workers."""
    with Session(engine) as session:
        yield session
