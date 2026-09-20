"""Database engine and session helpers."""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

DEFAULT_DATABASE_URL = "postgresql+psycopg://vogelvrij:vogelvrij@localhost:5433/vogelvrij"


def database_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)


def make_engine(url: str = "") -> Engine:
    return create_engine(url or database_url(), pool_pre_ping=True)


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    with Session(engine) as session:
        with session.begin():
            yield session
