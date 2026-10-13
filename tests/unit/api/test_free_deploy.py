"""Free-tier deploy plumbing (docs/09 §4): Cloud Run Jobs, the one-shot entrypoint,
Cloud Scheduler cron endpoints and the private-SearXNG token. No network access."""

import json
import time
from typing import Any

import httpx
import jwt
import pytest

from deno_api import cron
from deno_api.app import create_app
from deno_core import gcp, jobs, maintenance
from deno_core.settings import Settings
from deno_sources.base import SearxngClient
from tests.helpers.tokens import RSA_KEY, default_jwks

AUD = "https://deno-api-abc.run.app"
SCHEDULER = "scheduler@deno-prod.iam.gserviceaccount.com"
JOB = "projects/deno-prod/locations/us-central1/jobs/deno-run"


def google_token(**overrides: Any) -> str:
    now = int(time.time())
    claims: dict[str, Any] = {
        "iss": "https://accounts.google.com",
        "aud": AUD,
        "iat": now,
        "exp": now + 3600,
        "email": SCHEDULER,
        "email_verified": True,
        "sub": "1234567890",
    }
    claims.update(overrides)
    return jwt.encode(
        {k: v for k, v in claims.items() if v is not None}, RSA_KEY, algorithm="RS256", headers={"kid": "rsa-1"}
    )


# ---- cron endpoints ----------------------------------------------------------


@pytest.fixture
def cron_client(monkeypatch: pytest.MonkeyPatch) -> httpx.AsyncClient:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        environment="test",
        cron_oidc_audience=AUD,
        cron_service_account=SCHEDULER,
    )
    app = create_app(settings)
    app.state.sessionmaker = object()
    monkeypatch.setattr(cron, "google_jwks", default_jwks)

    async def purged(_maker: object) -> int:
        return 3

    async def requeued(_maker: object) -> int:
        return 1

    monkeypatch.setattr(maintenance, "purge_old_scraped_text", purged)
    monkeypatch.setattr(maintenance, "requeue_stale_runs", requeued)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_cron_runs_with_the_scheduler_token(cron_client: httpx.AsyncClient) -> None:
    headers = {"Authorization": f"Bearer {google_token()}"}
    async with cron_client as c:
        assert (await c.post("/internal/cron/purge", headers=headers)).json() == {"purged": 3}
        assert (await c.post("/internal/cron/requeue", headers=headers)).json() == {"requeued": 1}


@pytest.mark.parametrize(
    "token",
    [
        None,
        google_token(aud="https://someone-else.run.app"),
        google_token(email="attacker@evil.iam.gserviceaccount.com"),
        google_token(email_verified=False),
        google_token(iss="https://evil.example.com"),
        google_token(exp=int(time.time()) - 120),
    ],
    ids=["missing", "wrong-audience", "wrong-account", "unverified-email", "wrong-issuer", "expired"],
)
async def test_cron_rejects_anything_but_the_scheduler(cron_client: httpx.AsyncClient, token: str | None) -> None:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with cron_client as c:
        res = await c.post("/internal/cron/purge", headers=headers)
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "unauthenticated"


async def test_cron_is_hidden_when_not_configured() -> None:
    app = create_app(Settings(_env_file=None, environment="test"))  # type: ignore[call-arg]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        assert (
            await c.post("/internal/cron/purge", headers={"Authorization": f"Bearer {google_token()}"})
        ).status_code == 404
    assert "/internal/cron/purge" not in json.dumps(app.openapi())


# ---- Cloud Run Jobs ------------------------------------------------------------


async def test_enqueue_starts_a_cloud_run_job_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, list[str]]] = []

    async def fake_run(job: str, args: list[str]) -> str:
        calls.append((job, args))
        return "operations/1"

    settings = Settings(_env_file=None, environment="test", task_runner="cloudrun_job", cloudrun_job=JOB)  # type: ignore[call-arg]
    monkeypatch.setattr(jobs, "get_settings", lambda: settings)
    monkeypatch.setattr(gcp, "run_cloud_run_job", fake_run)

    assert await jobs.enqueue(jobs.TASK_VALIDATION_RUN, run_id="r1", user_id="u1") == "operations/1"
    assert calls == [
        (JOB, ["-m", "deno_worker.run_once", "validation.run", json.dumps({"run_id": "r1", "user_id": "u1"})])
    ]


async def test_run_cloud_run_job_posts_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["Authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"name": "operations/42"})

    async def token() -> str:
        return "ya29.test"

    monkeypatch.setattr(gcp, "access_token", token)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await gcp.run_cloud_run_job(JOB, ["-m", "x"], client=client) == "operations/42"
    assert seen == {
        "url": f"https://run.googleapis.com/v2/{JOB}:run",
        "auth": "Bearer ya29.test",
        "body": {"overrides": {"containerOverrides": [{"args": ["-m", "x"]}]}},
    }


def test_production_needs_a_full_job_name_for_cloudrun_runner() -> None:
    base = {
        "_env_file": None,
        "environment": "production",
        "supabase_url": "https://p.supabase.co",
        "nvidia_nim_api_key": "k",
        "database_url": "postgresql+asyncpg://u:p@h/db",
        "task_runner": "cloudrun_job",
    }
    with pytest.raises(ValueError, match="CLOUDRUN_JOB"):
        Settings(**base, cloudrun_job="deno-run")
    assert Settings(**base, cloudrun_job=JOB).cloudrun_job == JOB


# ---- one-shot entrypoint ---------------------------------------------------------


@pytest.mark.parametrize(
    "argv",
    [[], ["nope", "{}"], ["validation.run", "not json"], ["validation.run", "[1]"]],
    ids=["empty", "unknown-task", "bad-json", "not-an-object"],
)
def test_run_once_rejects_bad_invocations(argv: list[str]) -> None:
    from deno_worker import run_once

    assert run_once.main(argv) == 2


@pytest.mark.parametrize(("raises", "code"), [(False, 0), (True, 1)], ids=["finished", "transient"])
def test_run_once_exit_codes(monkeypatch: pytest.MonkeyPatch, raises: bool, code: int) -> None:
    from deno_worker import run_once

    received: list[dict[str, str]] = []

    async def fake_run(task: str, kwargs: dict[str, str]) -> None:
        received.append(kwargs)
        if raises:
            raise TimeoutError("NIM queue")

    monkeypatch.setattr(run_once, "run", fake_run)
    assert run_once.main(["validation.run", '{"run_id": "r", "user_id": "u"}']) == code
    assert received == [{"run_id": "r", "user_id": "u"}]


# ---- private SearXNG ---------------------------------------------------------------


async def test_searxng_requests_carry_the_id_token() -> None:
    seen: list[Any] = []

    class FakeFetcher:
        async def get(self, url: str, **kw: Any) -> Any:
            seen.append(kw.get("headers"))
            return type("R", (), {"status": 200, "json": lambda self: {"results": []}})()

    async def headers() -> dict[str, str]:
        return {"Authorization": "Bearer id-token"}

    await SearxngClient(FakeFetcher(), "https://searx.run.app", headers).search("q")  # type: ignore[arg-type]
    await SearxngClient(FakeFetcher(), "http://127.0.0.1:8890").search("q")  # type: ignore[arg-type]
    assert seen == [{"Authorization": "Bearer id-token"}, None]


def test_searxng_auth_only_when_enabled() -> None:
    assert gcp.searxng_auth_headers(Settings(_env_file=None)) is None  # type: ignore[call-arg]
    assert gcp.searxng_auth_headers(Settings(_env_file=None, searxng_gcp_auth=True)) is not None  # type: ignore[call-arg]
