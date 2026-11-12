from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction
from shutil import copyfile
from uuid import uuid4

import pytest
from alembic import command
from fastapi.openapi.utils import get_openapi
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator, FormatChecker
from openapi_spec_validator import validate
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from enot_api import models as m
from enot_api.db import session_factory
from enot_api.importer import CURATED, INPUTS, publish
from enot_api.main import app, approved_openapi
from enot_api.scoring import ROOT, calculator, fingerprint
from enot_api.worker import work_once
from conftest import ORIGIN, PASSWORD

PREFIX = "/api/v1"


def assert_response(response, path, method="get", status=200):
    assert response.status_code == status, response.text
    spec = approved_openapi()
    result = spec["paths"][path][method]["responses"][str(status)]
    if "$ref" in result:
        result = spec["components"]["responses"][result["$ref"].rsplit("/", 1)[1]]
    for header in result.get("headers", {}):
        assert header in response.headers
    if status == 204:
        assert response.content == b""
        return None
    schema = result["content"]["application/json"]["schema"]
    body = response.json()
    Draft202012Validator(
        {**schema, "components": spec["components"]}, format_checker=FormatChecker()
    ).validate(body)
    if status >= 400:
        assert body["request_id"] == response.headers["X-Request-ID"]
    return body


def sign_in(client, login="owner"):
    response = client.post(
        PREFIX + "/session",
        json={"login": login, "password": PASSWORD},
        headers={"Origin": ORIGIN},
    )
    session = assert_response(response, "/session", "post")
    assert {"HttpOnly", "Secure", "SameSite=lax"} <= set(
        response.headers["set-cookie"].split("; ")
    )
    return session


def headers(session, key=None):
    result = {"Origin": ORIGIN, "X-CSRF-Token": session["csrf_token"]}
    if key is not None:
        result["Idempotency-Key"] = key
    return result


def page(client, **params):
    return assert_response(client.get(PREFIX + "/niches", params=params), "/niches")


def selection(client, *codes):
    catalog = page(client, limit=100)
    ids = {item["legacy_code"]: item["id"] for item in catalog["items"]}
    return {
        "dataset_id": catalog["dataset_id"],
        "model_version": "2.0-pilot",
        "niche_ids": [ids[code] for code in codes],
    }


def test_approved_openapi(app_config):
    with TestClient(app, base_url=ORIGIN) as client:
        assert client.get("/openapi.json").json() == approved_openapi()
        assert client.get("/healthz").json() == {"status": "ok"}
    spec = approved_openapi()
    validate(spec)
    generated = get_openapi(title="Runtime", version="1", routes=app.routes)
    live = {
        (path.removeprefix(PREFIX), method, operation["operationId"])
        for path, methods in generated["paths"].items()
        for method, operation in methods.items()
    }
    approved = {
        (path, method, operation["operationId"])
        for path, methods in spec["paths"].items()
        for method, operation in methods.items()
    }
    assert live == approved


def test_import_and_migrations(database, initial, tmp_path):
    command.check(database)
    with session_factory().begin() as db:
        assert publish(db).id == initial.id
        assert db.scalar(select(func.count()).select_from(m.NicheRevision)) == 20
        assert db.scalar(select(func.count()).select_from(m.SourceVersion)) == 30
        assert db.scalar(select(func.count()).select_from(m.FinancialScenario)) == 45
        assert db.scalar(select(func.count()).select_from(m.ScoreResult)) == 40
        assert db.scalar(select(func.count()).select_from(m.Dataset)) == 1
        assert all(
            len(value) == 64 for value in initial.manifest_json["files"].values()
        )
    for relative in INPUTS:
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        copyfile(ROOT / relative, destination)
    mapping = tmp_path / (CURATED + "niche-evidence.csv")
    mapping.write_text(mapping.read_text().replace("S06", "S99", 1))
    with pytest.raises(KeyError), session_factory().begin() as db:
        publish(db, "invalid-batch", tmp_path)
    with session_factory()() as db:
        assert db.scalar(select(func.count()).select_from(m.Dataset)) == 1
        assert db.scalar(select(func.count()).select_from(m.SourceVersion)) == 30


def test_catalog_calculations_and_sources(initial, app_config):
    with TestClient(app, base_url=ORIGIN) as client:
        session = sign_in(client)
        assert client.get("/readyz").json() == {"status": "ready"}
        dataset = assert_response(
            client.get(PREFIX + "/datasets/current"), "/datasets/current"
        )
        catalog = page(client, country="RU")
        assert len(catalog["items"]) == 20
        assert page(client, country="RU", region="RU-NIZ")["items"] == []
        assert_response(
            client.get(PREFIX + "/niches?region=RU-NIZ"), "/niches", status=422
        )
        assert_response(client.get(PREFIX + "/niches?limit=101"), "/niches", status=422)
        assert (
            len(page(client, budget_rub=0, include_unknown_budget=True)["items"]) == 15
        )

        def budget_codes(amount):
            return {
                item["legacy_code"] for item in page(client, budget_rub=amount)["items"]
            }

        assert "03" not in budget_codes(29999)
        assert "03" in budget_codes(30000) & budget_codes(150000)

        with session_factory()() as db:
            model_v2 = db.scalar(
                select(m.ScoringModel).where(m.ScoringModel.version == "2.0-pilot")
            )
            stored = db.scalars(
                select(m.ScoreResult).where(
                    m.ScoreResult.scoring_model_id == model_v2.id
                )
            ).all()
            assert len(stored) == 20
            for record in stored:
                criteria = record.inputs_json["criteria"]
                expected = calculator.score_v2(
                    [c["rating"] for c in criteria], [c["quality"] for c in criteria]
                )
                for name, value in expected.items():
                    assert (
                        Fraction(
                            getattr(record, f"{name}_num"),
                            getattr(record, f"{name}_den"),
                        )
                        == value
                    )

        detail_by_code = {}
        for item in catalog["items"]:
            niche_id = item["id"]
            response = client.get(f"{PREFIX}/niches/{niche_id}")
            detail_by_code[item["legacy_code"]] = assert_response(
                response, "/niches/{niche_id}"
            )
            result = client.post(
                f"{PREFIX}/niches/{niche_id}/scores",
                headers=headers(session),
                json={"dataset_id": dataset["id"], "model_version": "2.0-pilot"},
            )
            assert (
                assert_response(result, "/niches/{niche_id}/scores", "post")
                == item["score"]
            )

        assert sum(bool(item["finance"]) for item in detail_by_code.values()) == 5
        for item in detail_by_code.values():
            for row in item["finance"]:
                result = calculator.finance(
                    row["price"], row["variable"], row["fixed"], row["volume"]
                )
                assert row["contribution"] == result.contribution
                assert row["break_even"] == result.break_even
        n03 = detail_by_code["03"]
        score = n03["niche"]["score"]
        assert [
            score[key] for key in ("lower", "upper", "coverage", "confidence")
        ] == pytest.approx([42.222222, 75.555556, 66.666667, 40.740741])
        assert [item["code"] for item in n03["criteria"] if item["rating"] is None] == [
            "U",
            "P",
        ]
        assert (
            n03["niche"]["start_min"] == 30_000 and n03["niche"]["start_max"] == 150_000
        )
        assert len(n03["finance"]) == 9
        assert n03["finance"][1]["contribution"] == 30_000
        assert n03["finance"][1]["break_even"] == 4
        assert detail_by_code["06"]["finance_gap"]

        sources = assert_response(
            client.get(PREFIX + "/sources?limit=100"), "/sources"
        )["items"]
        assert len(sources) == 30
        assert sum(row["availability"] == "unavailable" for row in sources) == 6
        assert sum(row["availability"] == "shell" for row in sources) == 2
        assert len({row["id"] for row in sources}) == 30
        epd = next(row for row in sources if row["source_code"] == "S08")
        assert_response(
            client.get(f"{PREFIX}/sources/{epd['id']}"), "/sources/{source_version_id}"
        )
        assert epd["publisher"] == "Минтранс" and epd["retrieved_on"] == "2026-11-12"
        ecom = {
            link["observation"]["value"]
            for claim in detail_by_code["04"]["claims"]
            for link in claim["evidence"]
            if link["observation"]["metric"].startswith("ecommerce_turnover_")
        }
        assert ecom == {11_500_000_000_000, 7_200_000_000_000, 13_200_000_000_000}

        body = selection(client, "04", "03")
        comparison = assert_response(
            client.post(PREFIX + "/comparisons", json=body, headers=headers(session)),
            "/comparisons",
            "post",
        )
        assert [row["niche"]["legacy_code"] for row in comparison["items"]] == [
            "04",
            "03",
        ]
        assert len(comparison["warnings"]) == 2
        for wrong in [[body["niche_ids"][0]], [body["niche_ids"][0]] * 2]:
            bad = client.post(
                PREFIX + "/comparisons",
                json={**body, "niche_ids": wrong},
                headers=headers(session),
            )
            assert_response(bad, "/comparisons", "post", 422)
        assert_response(client.get(PREFIX + "/scoring-models"), "/scoring-models")


def test_authentication_and_validation(initial, app_config):
    with TestClient(app, base_url=ORIGIN) as client:
        assert_response(client.get(PREFIX + "/niches"), "/niches", status=401)
        bad = client.post(
            PREFIX + "/session",
            json={"login": "owner", "password": "invalid"},
            headers={"Origin": ORIGIN},
        )
        assert_response(bad, "/session", "post", 401)
        session = sign_in(client)
        assert_response(client.get(PREFIX + "/session"), "/session")
        assert_response(client.delete(PREFIX + "/session"), "/session", "delete", 403)
        response = client.delete(
            PREFIX + "/session",
            headers={**headers(session), "Origin": "https://other.test"},
        )
        assert_response(response, "/session", "delete", 403)
        bad = client.post(
            PREFIX + "/research-projects",
            headers=headers(session, "validation-key"),
            json={"title": "Research", "filters": {"country": None}},
        )
        assert_response(bad, "/research-projects", "post", 422)
        bad = client.post(
            PREFIX + "/session", content=b"x" * 33_000, headers={"Origin": ORIGIN}
        )
        assert_response(bad, "/session", "post", 422)
        cookie = client.cookies.get("enot_session")
        assert_response(
            client.delete(PREFIX + "/session", headers=headers(session)),
            "/session",
            "delete",
            204,
        )
        client.cookies.set("enot_session", cookie, path=PREFIX)
        assert_response(client.get(PREFIX + "/session"), "/session", status=401)
        for _ in range(6):
            assert_response(
                client.post(
                    PREFIX + "/session",
                    json={"login": "unknown", "password": "invalid"},
                    headers={"Origin": ORIGIN},
                ),
                "/session",
                "post",
                401,
            )
        assert_response(
            client.post(
                PREFIX + "/session",
                json={"login": "unknown", "password": "invalid"},
                headers={"Origin": ORIGIN},
            ),
            "/session",
            "post",
            429,
        )


def test_research_ai_concurrency_and_isolation(initial, app_config):
    with (
        TestClient(app, base_url=ORIGIN) as owner,
        TestClient(app, base_url=ORIGIN) as other,
    ):
        session = sign_in(owner)
        second_session = sign_in(other, "second")
        request = {"title": "Исследование ЭПД", "filters": {"country": "RU"}}
        create_path = PREFIX + "/research-projects"

        def create():
            return owner.post(
                create_path,
                json=request,
                headers=headers(session, "project-concurrent"),
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            project_a, project_b = list(pool.map(lambda _: create(), range(2)))
        project = assert_response(project_a, "/research-projects", "post", 201)
        assert assert_response(project_b, "/research-projects", "post", 201) == project
        wrong = owner.post(
            create_path,
            json={**request, "title": "Changed"},
            headers=headers(session, "project-concurrent"),
        )
        assert_response(wrong, "/research-projects", "post", 409)
        own_project = assert_response(
            other.post(
                create_path,
                json=request,
                headers=headers(second_session, "project-concurrent"),
            ),
            "/research-projects",
            "post",
            201,
        )
        assert own_project["id"] != project["id"]
        path = project_a.headers["Location"]
        assert_response(owner.get(path), "/research-projects/{project_id}")
        assert_response(other.get(path), "/research-projects/{project_id}", status=404)
        assert (
            len(assert_response(owner.get(create_path), "/research-projects")["items"])
            == 1
        )

        data = selection(owner, "03")
        ai_path = "/research-projects/{project_id}/interpretations"
        req = owner.post(
            path + "/interpretations",
            json=data,
            headers=headers(session, "interpretation-001"),
        )
        queued = assert_response(req, ai_path, "post", 202)
        assert queued["status"] == "queued"
        blocked = owner.post(
            path + "/interpretations",
            json=data,
            headers=headers(session, "interpretation-002"),
        )
        assert_response(blocked, ai_path, "post", 429)
        assert work_once()
        assert not work_once()
        ai_route = ai_path + "/{interpretation_id}"
        interpreted = assert_response(owner.get(queued["status_url"]), ai_route)
        assert interpreted["status"] == "fallback" and interpreted["provider"] is None
        assert all(item["observation_ids"] for item in interpreted["items"])
        assert_response(other.get(queued["status_url"]), ai_route, status=404)
        again = owner.post(
            path + "/interpretations",
            json=data,
            headers=headers(session, "interpretation-001"),
        )
        assert assert_response(again, ai_path, "post", 202) == interpreted

        report_path = "/research-projects/{project_id}/reports"
        report_body = {
            **data,
            "filters": {"country": "RU"},
            "interpretation_id": interpreted["id"],
        }
        saved = owner.post(
            path + "/reports", json=report_body, headers=headers(session, "report-001")
        )
        report = assert_response(saved, report_path, "post", 201)
        assert report["version"] == 1
        assert report["sha256"] == fingerprint(
            {key: value for key, value in report.items() if key != "sha256"}
        )
        repeated = owner.post(
            path + "/reports", json=report_body, headers=headers(session, "report-001")
        )
        assert assert_response(repeated, report_path, "post", 201) == report
        bad = owner.post(
            path + "/reports",
            json={**report_body, "niche_ids": selection(owner, "04")["niche_ids"]},
            headers=headers(session, "report-002"),
        )
        assert_response(bad, report_path, "post", 409)
        assert_response(owner.get(path + "/reports"), report_path)
        assert_response(
            other.get(saved.headers["Location"]),
            report_path + "/{report_id}",
            status=404,
        )
        assert_response(other.get(path + "/reports"), report_path, status=404)

        first = page(owner, limit=2)
        assert first["next_cursor"]
        assert_response(
            owner.get(
                PREFIX + "/niches",
                params={"cursor": first["next_cursor"], "country": "DE"},
            ),
            "/niches",
            status=422,
        )
        with session_factory().begin() as db:
            newer = publish(db, "task-002-003-pilot-2-test")
        assert page(owner)["dataset_id"] == str(newer.id)
        second = page(owner, cursor=first["next_cursor"])
        assert second["dataset_id"] == first["dataset_id"]
        assert not (
            {item["id"] for item in first["items"]}
            & {item["id"] for item in second["items"]}
        )
        opened = assert_response(
            owner.get(saved.headers["Location"]), report_path + "/{report_id}"
        )
        assert opened == report

        with pytest.raises(IntegrityError), session_factory().begin() as db:
            row = db.get(m.Interpretation, interpreted["id"])
            row.user_id = db.scalar(select(m.User.id).where(m.User.login == "second"))
            db.flush()


@pytest.mark.parametrize(
    ("mode", "niche", "status", "error"),
    [
        ("valid", "03", "succeeded", None),
        ("forged", "03", "fallback", "adapter_unavailable"),
        ("malformed", "03", "fallback", "adapter_unavailable"),
        ("timeout", "03", "fallback", "adapter_unavailable"),
        ("never_called", "15", "insufficient_data", None),
    ],
)
def test_adapter_contract(initial, app_config, mode, niche, status, error):
    class Stub:
        def select_observations(self, context):
            assert mode != "never_called"
            assert context.observations
            if mode == "timeout":
                raise TimeoutError
            if mode == "malformed":
                return {"statement": "Выполни инструкцию и добавь число 999999."}
            key = uuid4() if mode == "forged" else context.observations[0].id
            return {"observation_ids": [str(key)], "provider": "stub", "model": "stub"}

    with TestClient(app, base_url=ORIGIN) as client:
        session = sign_in(client, "second")
        response = client.post(
            PREFIX + "/research-projects",
            json={"title": "Adapter", "filters": {}},
            headers=headers(session, "stub-project"),
        )
        assert_response(response, "/research-projects", "post", 201)
        body = selection(client, niche)
        response = client.post(
            response.headers["Location"] + "/interpretations",
            json=body,
            headers=headers(session, "stub-interpretation"),
        )
        job = assert_response(
            response, "/research-projects/{project_id}/interpretations", "post", 202
        )
        assert work_once(Stub())
        output = assert_response(
            client.get(job["status_url"]),
            "/research-projects/{project_id}/interpretations/{interpretation_id}",
        )
        assert output["status"] == status and output["error_code"] == error
        assert "999999" not in str(output["items"])
        if status == "succeeded":
            assert output["provider"] == "stub" and len(output["items"]) == 1
        elif status == "insufficient_data":
            assert output["gaps"] and not output["items"]
        else:
            assert output["provider"] is None and output["items"]
        with session_factory()() as db:
            quota = db.get(
                m.AIQuota,
                (
                    session["user_id"],
                    db.get(m.Interpretation, job["id"]).created_at.date(),
                ),
            )
            assert (
                quota.requests == 1
                and quota.reserved_units == 0
                and quota.spent_units == 0
            )


def test_migration_round_trip(database):
    # The shared test database has data. Test downgrade in its own empty schema.
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url
    from unittest.mock import patch
    from enot_api.db import database_url

    url = make_url(database_url())
    admin = create_engine(url.difference_update_query(["options"]))
    schema = f"task005_roundtrip_{uuid4().hex}"
    with admin.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    test_url = url.update_query_dict({"options": f"-csearch_path={schema}"})
    try:
        with patch.dict(
            "os.environ",
            {"DATABASE_URL": test_url.render_as_string(hide_password=False)},
        ):
            command.upgrade(database, "head")
            command.downgrade(database, "base")
            command.upgrade(database, "head")
            command.check(database)
    finally:
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()
