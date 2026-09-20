"""Error envelope and request-id plumbing."""

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from deno_api.errors import install_error_handlers
from deno_api.middleware import RequestContextMiddleware
from deno_core.errors import NotFound, UpstreamUnavailable


class Body(BaseModel):
    secret_field: int


def make_app() -> FastAPI:
    app = FastAPI()
    install_error_handlers(app)
    app.add_middleware(RequestContextMiddleware)

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("db password is hunter2")

    @app.get("/missing")
    async def missing() -> None:
        raise NotFound("Project not found.")

    @app.get("/upstream")
    async def upstream() -> None:
        raise UpstreamUnavailable()

    @app.post("/validate")
    async def validate(body: Body) -> dict[str, int]:
        return {"ok": body.secret_field}

    return app


client = TestClient(make_app(), raise_server_exceptions=False)


def test_unhandled_exception_is_generic_500_without_internals() -> None:
    res = client.get("/boom")
    assert res.status_code == 500
    body = res.json()
    assert body["error"]["code"] == "internal_error"
    assert "hunter2" not in res.text
    assert body["error"]["request_id"] == res.headers["x-request-id"]


def test_domain_errors_map_to_status_and_code() -> None:
    res = client.get("/missing")
    assert res.status_code == 404
    assert res.json()["error"] == {
        "code": "not_found",
        "message": "Project not found.",
        "request_id": res.headers["x-request-id"],
    }
    assert client.get("/upstream").status_code == 503


def test_unknown_route_uses_envelope() -> None:
    res = client.get("/nope")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "not_found"


def test_validation_error_names_fields_but_not_values() -> None:
    res = client.post("/validate", json={"secret_field": "sensitive-value-123"})
    assert res.status_code == 422
    assert "secret_field" in res.json()["error"]["message"]
    assert "sensitive-value-123" not in res.text


def test_safe_incoming_request_id_is_propagated() -> None:
    res = client.get("/missing", headers={"X-Request-ID": "abc12345-trace"})
    assert res.headers["x-request-id"] == "abc12345-trace"


def test_unsafe_incoming_request_id_is_replaced() -> None:
    res = client.get("/missing", headers={"X-Request-ID": "bad\nid<script>"})
    assert res.headers["x-request-id"] != "bad\nid<script>"
    assert len(res.headers["x-request-id"]) == 32


def test_health_probes() -> None:
    from deno_api.health import register_readiness_check
    from deno_api.main import app

    api = TestClient(app)
    assert api.get("/healthz").json() == {"status": "ok"}

    async def broken() -> None:
        raise ConnectionError("down")

    register_readiness_check("test-broken", broken)
    try:
        res = api.get("/readyz")
        assert res.status_code == 503
        assert res.json()["checks"]["test-broken"] == "fail"
    finally:
        from deno_api import health

        health._checks.pop("test-broken")


def test_clean_text_strips_control_chars_but_keeps_newlines() -> None:
    from deno_core.text import clean_text

    assert clean_text(" a\x00b\x1f\tc\nd\x7f ") == "ab\tc\nd"
