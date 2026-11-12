from collections.abc import Iterator
from datetime import UTC, datetime
from functools import lru_cache
from os import environ

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker


def now() -> datetime:
    return datetime.now(UTC)


def database_url() -> str:
    url = environ["DATABASE_URL"]
    if url.startswith(("postgres://", "postgresql://")):
        url = "postgresql+psycopg://" + url.split("://", 1)[1]
    if not url.startswith("postgresql+psycopg://"):
        raise ValueError("DATABASE_URL must use PostgreSQL and psycopg")
    return url


@lru_cache
def session_factory() -> sessionmaker[Session]:
    engine = create_engine(database_url(), pool_pre_ping=True, hide_parameters=True)
    return sessionmaker(engine, expire_on_commit=False)


def db_session() -> Iterator[Session]:
    with session_factory()() as db:
        yield db


def transaction_lock(db: Session, key: str) -> None:
    db.execute(
        text("select pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": key}
    )
