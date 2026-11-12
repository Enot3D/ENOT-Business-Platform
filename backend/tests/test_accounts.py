from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import select

from conftest import ORIGIN
from enot_api.db import session_factory
from enot_api.main import app
from enot_api.models import User
from enot_api.security import PASSWORD_HASHER
from test_backend import PREFIX, assert_response, headers, sign_in

NEW_USER = {
    "name": "Пользователь",
    "email": "QA@enot.example.com",
    "password": "Test-secret-123",
}


def test_account_lifecycle(initial, app_config):
    with TestClient(app, base_url=ORIGIN) as client:
        origin = {"Origin": ORIGIN}
        assert_response(
            client.post(PREFIX + "/register", json=NEW_USER), "/register", "post", 403
        )
        for override in (
            {"password": "weak"},
            {"email": "bad-address"},
            {"name": "   "},
        ):
            assert_response(
                client.post(
                    PREFIX + "/register", json={**NEW_USER, **override}, headers=origin
                ),
                "/register",
                "post",
                422,
            )
        created = client.post(PREFIX + "/register", json=NEW_USER, headers=origin)
        session = assert_response(created, "/register", "post", 201)
        assert {"HttpOnly", "Secure", "SameSite=lax", f"Path={PREFIX}"} <= set(
            created.headers["set-cookie"].split("; ")
        )
        assert client.get(PREFIX + "/session").json() == session
        assert_response(
            client.post(
                PREFIX + "/register",
                json={**NEW_USER, "email": NEW_USER["email"].lower()},
                headers=origin,
            ),
            "/register",
            "post",
            409,
        )
        with session_factory()() as db:
            user = db.get_one(User, UUID(session["user_id"]))
            assert user.password_hash.startswith("$argon2id$")
            assert PASSWORD_HASHER.verify(user.password_hash, NEW_USER["password"])
        assert assert_response(client.get(PREFIX + "/profile"), "/profile") == {
            "name": NEW_USER["name"],
            "email": NEW_USER["email"].lower(),
        }
        body = {"name": "Новое имя"}
        assert_response(
            client.patch(PREFIX + "/profile", json=body, headers=origin),
            "/profile",
            "patch",
            403,
        )
        assert_response(
            client.patch(PREFIX + "/profile", json=body, headers=headers(session)),
            "/profile",
            "patch",
        )
        assert client.get(PREFIX + "/profile").json()["name"] == body["name"]

        wrong = {"current_password": "Wrong-password-123", "password": "New-secret-123"}
        assert (
            assert_response(
                client.post(
                    PREFIX + "/profile/password", json=wrong, headers=headers(session)
                ),
                "/profile/password",
                "post",
                403,
            )["code"]
            == "wrong_current_password"
        )
        previous = client.cookies["enot_session"]
        changed = client.post(
            PREFIX + "/profile/password",
            json={**wrong, "current_password": NEW_USER["password"]},
            headers=headers(session),
        )
        rotated = assert_response(changed, "/profile/password", "post")
        assert rotated["csrf_token"] != session["csrf_token"]
        with TestClient(app, base_url=ORIGIN) as other:
            other.cookies.set("enot_session", previous, path=PREFIX)
            assert_response(other.get(PREFIX + "/session"), "/session", status=401)
        assert_response(
            client.delete(PREFIX + "/session", headers=headers(rotated)),
            "/session",
            "delete",
            204,
        )
        assert_response(client.get(PREFIX + "/profile"), "/profile", status=401)
        credentials = {"login": NEW_USER["email"], "password": NEW_USER["password"]}
        assert_response(
            client.post(PREFIX + "/session", json=credentials, headers=origin),
            "/session",
            "post",
            401,
        )
        signed_in = client.post(
            PREFIX + "/session",
            json={**credentials, "password": wrong["password"]},
            headers=origin,
        )
        assert (
            assert_response(signed_in, "/session", "post")["user_id"]
            == session["user_id"]
        )

        result = assert_response(
            client.post(
                PREFIX + "/finance/calculate",
                json={"price": 5000, "variable": 1000, "fixed": 10000, "volume": 4},
                headers=headers(signed_in.json()),
            ),
            "/finance/calculate",
            "post",
        )
        assert result["contribution"] == 6000 and result["break_even"] == 3
        with TestClient(app, base_url=ORIGIN) as legacy:
            sign_in(legacy)


def test_registration_concurrency_and_rate_limit(initial, app_config):
    def signup(index):
        with TestClient(app, base_url=ORIGIN) as client:
            response = client.post(
                PREFIX + "/register",
                json={
                    **NEW_USER,
                    "email": NEW_USER["email"].lower() if index else NEW_USER["email"],
                },
                headers={"Origin": ORIGIN, "X-Forwarded-For": f"192.0.2.{index + 1}"},
            )
            return response.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(signup, range(2))) == [201, 409]
    with session_factory()() as db:
        assert (
            len(
                db.scalars(
                    select(User).where(User.email == NEW_USER["email"].lower())
                ).all()
            )
            == 1
        )
    assert signup(2) == 409
    assert signup(3) == 409
    assert signup(4) == 429
