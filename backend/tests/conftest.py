import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from enot_api.db import database_url, session_factory
from enot_api.importer import publish
from enot_api.models import User
from enot_api.security import PASSWORD_HASHER, settings

ORIGIN = "https://enot.test"
PASSWORD = "test-password-only"


@pytest.fixture
def database():
    test_url = os.environ.get("TEST_DATABASE_URL")
    if not test_url:
        pytest.fail("Set TEST_DATABASE_URL to an isolated PostgreSQL instance")
    schema = f"task005_{uuid4().hex}"
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = test_url
    url = make_url(database_url())
    admin = create_engine(url)
    with admin.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    scoped_url = url.update_query_dict(
        {"options": f"-csearch_path={schema} -ctimezone=UTC"}
    )
    os.environ["DATABASE_URL"] = scoped_url.render_as_string(hide_password=False)
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    try:
        command.upgrade(config, "head")
        yield config
    finally:
        if session_factory.cache_info().currsize:
            session_factory().kw["bind"].dispose()
        session_factory.cache_clear()
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


@pytest.fixture
def initial(database):
    hashed = PASSWORD_HASHER.hash(PASSWORD)
    with session_factory().begin() as db:
        release = publish(db)
        db.add_all(
            [
                User(login="owner", password_hash=hashed),
                User(login="second", password_hash=hashed),
            ]
        )
    return release


@pytest.fixture
def app_config(monkeypatch):
    monkeypatch.setenv("APP_ORIGIN", ORIGIN)
    monkeypatch.setenv(
        "APP_SIGNING_KEY", "test-only-signing-key-with-at-least-32-bytes"
    )
    monkeypatch.setenv("APP_COOKIE_SECURE", "true")
    for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "AI_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    settings.cache_clear()
    yield
    settings.cache_clear()
