import logging
from contextlib import asynccontextmanager
from functools import lru_cache
from uuid import uuid4

import yaml
from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from . import accounts, catalog, research
from . import schemas as s
from .scoring import ROOT
from .security import APIError, COOKIE, PREFIX, Current, Db, Writer, login, settings
from .db import now

LOGGER = logging.getLogger("enot.api")
MAX_REQUEST_BYTES = 32_768


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings()
    yield


app = FastAPI(lifespan=lifespan, redirect_slashes=False, redoc_url=None)


@lru_cache
def approved_openapi() -> dict:
    path = ROOT / "architecture/TASK-004/api-contract.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


app.openapi = approved_openapi


def error(request: Request, status: int, code: str, message: str) -> JSONResponse:
    payload = s.Error(code=code, message=message, request_id=request.state.request_id)
    return JSONResponse(payload.model_dump(), status_code=status)


class RequestLimits:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id
        is_api = scope["path"].startswith(PREFIX + "/")

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["X-Request-ID"] = request_id
                headers["X-Content-Type-Options"] = "nosniff"
                if is_api:
                    headers["Cache-Control"] = "no-store"
            await send(message)

        if not is_api or scope["method"] not in {"POST", "PATCH", "DELETE"}:
            await self.app(scope, receive, send_with_headers)
            return

        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > MAX_REQUEST_BYTES:
                status = 403 if scope["method"] == "DELETE" else 422
                response = error(
                    Request(scope),
                    status,
                    "request_too_large",
                    "Request body is too large",
                )
                await response(scope, receive, send_with_headers)
                return
            body.extend(chunk)
            if not message.get("more_body", False):
                break

        replayed = False

        async def replay_body() -> Message:
            nonlocal replayed
            if replayed:
                return await receive()
            replayed = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        await self.app(scope, replay_body, send_with_headers)


app.add_middleware(RequestLimits)


@app.exception_handler(APIError)
async def api_error(request: Request, exc: APIError):
    return error(request, exc.status, exc.code, exc.message)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    return error(
        request, 422, "validation_error", "Request does not match the API contract"
    )


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    response = error(request, exc.status_code, "http_error", "HTTP request failed")
    response.headers.update(exc.headers or {})
    return response


@app.exception_handler(SQLAlchemyError)
async def database_error(request: Request, exc: SQLAlchemyError):
    LOGGER.error(
        "Database error request_id=%s type=%s",
        request.state.request_id,
        type(exc).__name__,
    )
    return error(
        request, 503, "database_unavailable", "Database temporarily unavailable"
    )


@app.get("/healthz", include_in_schema=False)
def liveness() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz", include_in_schema=False)
def readiness(db: Db) -> dict[str, str]:
    db.execute(text("SELECT email FROM users LIMIT 0"))
    if db.execute(text("SELECT 1 FROM dataset_versions LIMIT 1")).first() is None:
        raise APIError(503, "dataset_unavailable", "Published dataset is required")
    return {"status": "ready"}


app.post(PREFIX + "/session", operation_id="login")(login)


@app.get(PREFIX + "/session", operation_id="getSession")
def get_session(auth: Current) -> s.Session:
    return auth.response()


@app.delete(PREFIX + "/session", operation_id="logout", status_code=204)
def logout(auth: Writer, db: Db) -> Response:
    auth.record.revoked_at = now()
    db.commit()
    response = Response(status_code=204)
    response.delete_cookie(
        COOKIE, path=PREFIX, secure=settings().secure, httponly=True, samesite="lax"
    )
    return response


app.include_router(accounts.router, prefix=PREFIX)
app.include_router(catalog.router, prefix=PREFIX)
app.include_router(research.router, prefix=PREFIX)
