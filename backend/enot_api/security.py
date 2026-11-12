import base64
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import timedelta
from functools import lru_cache
from hashlib import sha256
from os import environ
from typing import Annotated
from urllib.parse import urlsplit
from uuid import UUID

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from email_validator import EmailNotValidError, validate_email
from fastapi import Depends, Header, Request, Response
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from . import schemas as s
from .db import db_session, now, session_factory
from .models import RateLimit, SessionRecord, User

PREFIX = "/api/v1"
COOKIE = "enot_session"
PASSWORD_HASHER = PasswordHasher()
DUMMY_HASH = PASSWORD_HASHER.hash(secrets.token_urlsafe(32))
Db = Annotated[Session, Depends(db_session)]
CsrfHeader = Annotated[str | None, Header(alias="X-CSRF-Token")]
KeyHeader = Annotated[
    str, Header(alias="Idempotency-Key", min_length=8, max_length=128)
]


class APIError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message


def missing() -> APIError:
    return APIError(404, "not_found", "Resource not found")


def invalid(message: str) -> APIError:
    return APIError(422, "validation_error", message)


@dataclass(frozen=True)
class Settings:
    origin: str
    secret: bytes
    secure: bool


@lru_cache
def settings() -> Settings:
    origin = environ["APP_ORIGIN"]
    parsed = urlsplit(origin)
    secure = environ.get("APP_COOKIE_SECURE", "true").lower() != "false"
    secret = environ["APP_SIGNING_KEY"].encode()
    if (
        len(secret) < 32
        or parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.path
        or parsed.query
        or parsed.fragment
        or (
            parsed.scheme != "https"
            and (secure or parsed.hostname not in {"localhost", "127.0.0.1", "::1"})
        )
        or (not secure and parsed.hostname not in {"localhost", "127.0.0.1", "::1"})
    ):
        raise ValueError(
            "Configure a valid APP_ORIGIN, APP_COOKIE_SECURE and APP_SIGNING_KEY"
        )
    return Settings(origin, secret, secure)


def mac(data: bytes, purpose: bytes) -> str:
    return hmac.new(settings().secret, purpose + b":" + data, sha256).hexdigest()


def digest(token: str) -> str:
    return sha256(token.encode()).hexdigest()


def rate_limit(entries: dict[str, int], seconds: int = 60) -> None:
    window = int(now().timestamp()) // seconds
    exceeded = False
    with session_factory().begin() as db:
        for name, maximum in sorted(entries.items()):
            key = mac(name.encode(), b"rate")
            stmt = insert(RateLimit).values(key=key, window=window, count=1)
            count = db.scalar(
                stmt.on_conflict_do_update(
                    index_elements=[RateLimit.key, RateLimit.window],
                    set_={"count": RateLimit.count + 1},
                ).returning(RateLimit.count)
            )
            exceeded |= count > maximum
        # Bound retention without sweeping the table on every request.
        if secrets.randbelow(128) == 0:
            db.execute(delete(RateLimit).where(RateLimit.window < window - 120))
    if exceeded:
        raise APIError(429, "rate_limited", "Too many requests")


def origin_allowed(request: Request) -> bool:
    return request.headers.get("origin") == settings().origin


@dataclass(frozen=True)
class Auth:
    record: SessionRecord

    @property
    def user_id(self) -> UUID:
        return self.record.user_id

    def response(self) -> s.Session:
        return s.Session(
            user_id=self.user_id,
            csrf_token=mac(self.record.token_digest.encode(), b"csrf"),
            expires_at=self.record.expires_at,
        )


def authenticate(request: Request, db: Db) -> Auth:
    rate_limit({f"api-ip:{client_ip(request)}": 600})
    token = request.cookies.get(COOKIE, "")
    if not token or len(token) > 128:
        raise APIError(401, "unauthenticated", "Valid session required")
    record = db.scalar(
        select(SessionRecord)
        .join(User, User.id == SessionRecord.user_id)
        .where(
            SessionRecord.token_digest == digest(token),
            SessionRecord.revoked_at.is_(None),
            SessionRecord.expires_at > now(),
            User.enabled.is_(True),
        )
    )
    if record is None:
        raise APIError(401, "unauthenticated", "Valid session required")
    return Auth(record)


Current = Annotated[Auth, Depends(authenticate)]


def authorize_write(request: Request, auth: Current, csrf: CsrfHeader = None) -> Auth:
    expected = auth.response().csrf_token.encode()
    if (
        not origin_allowed(request)
        or not csrf
        or not hmac.compare_digest(csrf.encode(), expected)
    ):
        raise APIError(403, "csrf_failed", "Origin or CSRF token is invalid")
    return auth


Writer = Annotated[Auth, Depends(authorize_write)]


def login(body: s.Login, request: Request, response: Response, db: Db) -> s.Session:
    login_name = body.login.strip().lower()
    if not origin_allowed(request):
        raise APIError(401, "invalid_credentials", "Invalid credentials or origin")
    rate_limit({f"login-ip:{client_ip(request)}": 20, f"login-account:{login_name}": 6})
    try:
        email = normalize_email(login_name)
    except EmailNotValidError:
        email = None
    user = (
        db.scalar(select(User).where(User.email == email).with_for_update())
        if email
        else None
    )
    if user is None:
        user = db.scalar(select(User).where(User.login == body.login).with_for_update())
    if not password_matches(user.password_hash if user else DUMMY_HASH, body.password):
        raise APIError(401, "invalid_credentials", "Invalid credentials")
    if not user or not user.enabled:
        raise APIError(401, "invalid_credentials", "Invalid credentials")
    if PASSWORD_HASHER.check_needs_rehash(user.password_hash):
        user.password_hash = PASSWORD_HASHER.hash(body.password)
    return start_session(user, request, response, db)


def normalize_email(value: str) -> str:
    email = validate_email(value, check_deliverability=False)
    return f"{email.local_part.lower()}@{email.ascii_domain}"


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def password_matches(password_hash: str, password: str) -> bool:
    try:
        return PASSWORD_HASHER.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def start_session(
    user: User, request: Request, response: Response, db: Session
) -> s.Session:
    old = request.cookies.get(COOKIE, "")
    if old and len(old) <= 128:
        existing = db.scalar(
            select(SessionRecord).where(
                SessionRecord.token_digest == digest(old),
                SessionRecord.user_id == user.id,
            )
        )
        if existing:
            existing.revoked_at = now()
    token = secrets.token_urlsafe(32)
    expires = timedelta(hours=12)
    record = SessionRecord(
        token_digest=digest(token), user_id=user.id, expires_at=now() + expires
    )
    db.add(record)
    db.commit()
    response.set_cookie(
        COOKIE,
        token,
        max_age=int(expires.total_seconds()),
        path=PREFIX,
        secure=settings().secure,
        httponly=True,
        samesite="lax",
    )
    return Auth(record).response()


def encode_cursor(
    scope: str, binding: str, last: UUID, dataset_id: UUID | None = None
) -> str:
    payload = json.dumps(
        [scope, binding, str(last), str(dataset_id) if dataset_id else None],
        separators=(",", ":"),
    )
    data = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
    return data + "." + mac(data.encode(), b"cursor")


def decode_cursor(
    cursor: str | None, scope: str, binding: str
) -> tuple[UUID | None, UUID | None]:
    if cursor is None:
        return None, None
    try:
        data, signature = cursor.split(".", 1)
        if not hmac.compare_digest(
            signature.encode(), mac(data.encode(), b"cursor").encode()
        ):
            raise ValueError
        stored_scope, stored_binding, last, dataset = json.loads(
            base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))
        )
        if (stored_scope, stored_binding) != (scope, binding):
            raise ValueError
        return UUID(last), UUID(dataset) if dataset else None
    except (ValueError, TypeError):
        raise invalid("Invalid cursor or cursor filters") from None
