"""Exercise the running Compose API and worker in a disposable CI project."""

import json
import os
import secrets
import time
from http.cookiejar import CookieJar
from urllib.request import HTTPCookieProcessor, Request, build_opener

from enot_api.db import session_factory
from enot_api.models import User
from enot_api.security import PASSWORD_HASHER

origin = os.environ["APP_ORIGIN"]
base_url = "http://127.0.0.1:8000"
cookies = CookieJar()
client = build_opener(HTTPCookieProcessor(cookies))


def request(path, body=None, headers=None):
    headers = {"Origin": origin, **(headers or {})}
    if body is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(body).encode()
    with client.open(Request(base_url + path, data=body, headers=headers), timeout=5) as response:
        return json.load(response), response.headers


assert request("/healthz")[0] == {"status": "ok"}
assert request("/readyz")[0] == {"status": "ready"}
password = secrets.token_urlsafe(32)
with session_factory().begin() as db:
    db.add(User(login="ci-smoke", password_hash=PASSWORD_HASHER.hash(password)))

session, _ = request("/api/v1/session", {"login": "ci-smoke", "password": password})
assert any(cookie.name == "enot_session" and not cookie.secure for cookie in cookies)
page, _ = request("/api/v1/niches?limit=100")
assert len(page["items"]) == 20 and not page["next_cursor"]
print("API is ready; authenticated HTTP catalog contains 20 niches.")

write_headers = {"X-CSRF-Token": session["csrf_token"], "Idempotency-Key": "smoke-project"}
_, project_headers = request(
    "/api/v1/research-projects", {"title": "CI smoke", "filters": {"country": "RU"}}, write_headers
)
niche = next(item for item in page["items"] if item["legacy_code"] == "03")
write_headers["Idempotency-Key"] = "smoke-interpretation"
job, _ = request(
    project_headers["Location"] + "/interpretations",
    {"dataset_id": page["dataset_id"], "model_version": page["model_version"], "niche_ids": [niche["id"]]},
    write_headers,
)
deadline = time.monotonic() + 30
while time.monotonic() < deadline:
    result, _ = request(job["status_url"])
    if result["status"] not in {"queued", "running"}:
        assert result["status"] == "fallback" and result["items"], result["status"]
        print("The Compose worker processed the queued interpretation using the local fallback.")
        break
    time.sleep(1)
else:
    raise RuntimeError("The Compose worker did not finish the queued interpretation")
