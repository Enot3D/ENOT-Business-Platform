from uuid import uuid4

from fastapi import APIRouter, Request, Response
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert

from . import schemas as s
from .db import now, transaction_lock
from .models import SessionRecord, User
from .security import (
    PASSWORD_HASHER,
    APIError,
    Current,
    Db,
    Writer,
    client_ip,
    normalize_email,
    origin_allowed,
    password_matches,
    rate_limit,
    start_session,
)

router = APIRouter()


@router.post("/register", status_code=201, operation_id="register")
def register(
    body: s.Registration, request: Request, response: Response, db: Db
) -> s.Session:
    if not origin_allowed(request):
        raise APIError(403, "forbidden", "Invalid origin")
    email = normalize_email(body.email)
    rate_limit({f"register-ip:{client_ip(request)}": 12, f"register-email:{email}": 4})
    rate_limit({"register-global": 100})
    conflict = APIError(
        409, "account_exists", "An account with this email already exists"
    )
    password_hash = PASSWORD_HASHER.hash(body.password)
    transaction_lock(db, f"account-email:{email}")
    if db.scalar(select(User.id).where(func.lower(User.login) == email).limit(1)):
        raise conflict
    user = db.scalar(
        insert(User)
        .values(
            login=f"account:{uuid4().hex}",
            email=email,
            display_name=body.name,
            password_hash=password_hash,
            enabled=True,
        )
        .on_conflict_do_nothing(index_elements=[User.email])
        .returning(User)
    )
    if user is None:
        raise conflict
    return start_session(user, request, response, db)


def profile(user: User) -> s.Profile:
    return s.Profile(name=user.display_name or user.login, email=user.email)


@router.get("/profile", operation_id="getProfile")
def get_profile(auth: Current, db: Db) -> s.Profile:
    return profile(db.get_one(User, auth.user_id))


@router.patch("/profile", operation_id="updateProfile")
def update_profile(body: s.ProfileName, auth: Writer, db: Db) -> s.Profile:
    user = db.get_one(User, auth.user_id)
    user.display_name = body.name
    db.commit()
    return profile(user)


@router.post("/profile/password", operation_id="changePassword")
def change_password(
    body: s.PasswordChange, request: Request, response: Response, auth: Writer, db: Db
) -> s.Session:
    rate_limit({f"password-change:{auth.user_id}": 5})
    user = db.get_one(User, auth.user_id, with_for_update=True)
    db.refresh(auth.record)
    if auth.record.revoked_at or auth.record.expires_at <= now() or not user.enabled:
        raise APIError(401, "unauthenticated", "Valid session required")
    if not password_matches(user.password_hash, body.current_password):
        raise APIError(403, "wrong_current_password", "Current password is incorrect")
    user.password_hash = PASSWORD_HASHER.hash(body.password)
    db.execute(
        update(SessionRecord)
        .where(SessionRecord.user_id == user.id, SessionRecord.revoked_at.is_(None))
        .values(revoked_at=now())
    )
    return start_session(user, request, response, db)
