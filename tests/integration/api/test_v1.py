"""API v1 end to end against Postgres + Valkey: tenancy, runs, SSE, report, account."""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from deno_api import auth
from deno_api.app import create_app
from deno_api.v1 import projects as projects_module
from deno_api.v1 import runs as runs_module
from deno_core.db import models as m
from deno_core.db.base import new_id
from deno_core.db.enums import Plan, Source, Stance, UsageKind, VerdictKind
from deno_core.events import RunEvents
from deno_core.runs import RunContext, RunOutcome, execute_run
from deno_core.settings import Settings
from tests.helpers.tokens import make_verifier, user_token

VALKEY_URL = "redis://127.0.0.1:6379/15"
IDEA = {"idea": "A tool that scores LinkedIn drafts for AI-sounding language before you post."}


@pytest.fixture
async def redis() -> AsyncIterator[Redis]:
    client = Redis.from_url(VALKEY_URL)
    try:
        await client.ping()
    except Exception:
        pytest.skip("Valkey not reachable on 127.0.0.1:6379")
    yield client
    await client.flushdb()
    await client.aclose()


@pytest.fixture
def enqueued(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def fake_enqueue(task: str, **kwargs: Any) -> str:
        calls.append({"task": task, **kwargs})
        return "job"

    monkeypatch.setattr(projects_module, "enqueue", fake_enqueue)
    monkeypatch.setattr(runs_module, "enqueue", fake_enqueue)
    return calls


@pytest.fixture
def maker(connection: AsyncConnection) -> async_sessionmaker[AsyncSession]:
    # Requests run as savepoints inside the test's outer transaction (rolled back afterwards).
    return async_sessionmaker(bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint")


@pytest.fixture
async def client(
    maker: async_sessionmaker[AsyncSession], redis: Redis, enqueued: list[dict[str, Any]]
) -> AsyncIterator[httpx.AsyncClient]:
    settings = Settings(environment="test", database_url="", valkey_url=VALKEY_URL, api_rate_limit_per_minute=1000)
    app = create_app(settings)
    app.state.sessionmaker = maker
    app.state.redis = redis
    _verifier = make_verifier()
    app.dependency_overrides[auth.get_verifier] = lambda: _verifier
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def create_project(client: httpx.AsyncClient, headers: dict[str, str]) -> str:
    res = await client.post("/api/v1/projects", json=IDEA, headers=headers)
    assert res.status_code == 201, res.text
    return str(res.json()["id"])


# ---- tenancy ----------------------------------------------------------------------


async def test_project_crud_and_foreign_access_is_404(client: httpx.AsyncClient) -> None:
    _, alice = user_token()
    _, bob = user_token()
    pid = await create_project(client, alice)

    assert (await client.get("/api/v1/projects", headers=alice)).json()["items"][0]["id"] == pid
    assert (await client.patch(f"/api/v1/projects/{pid}", json={"title": "Draft scorer"}, headers=alice)).json()[
        "title"
    ] == "Draft scorer"

    for method, path, body in [
        ("get", f"/api/v1/projects/{pid}", None),
        ("patch", f"/api/v1/projects/{pid}", {"title": "pwned"}),
        ("delete", f"/api/v1/projects/{pid}", None),
        ("get", f"/api/v1/projects/{pid}/runs", None),
        ("post", f"/api/v1/projects/{pid}/runs", None),
    ]:
        res = await client.request(method.upper(), path, json=body, headers=bob)
        assert res.status_code == 404, (method, path, res.text)
        assert res.json()["error"]["code"] == "not_found"
    assert (await client.get("/api/v1/projects", headers=bob)).json()["items"] == []

    assert (await client.delete(f"/api/v1/projects/{pid}", headers=alice)).status_code == 204
    assert (await client.get(f"/api/v1/projects/{pid}", headers=alice)).status_code == 404


async def test_requires_token(client: httpx.AsyncClient) -> None:
    res = await client.get("/api/v1/projects")
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "unauthenticated"


# ---- runs ----------------------------------------------------------------------------


async def test_start_run_is_idempotent_and_enqueued_once(
    client: httpx.AsyncClient, enqueued: list[dict[str, Any]]
) -> None:
    user_id, headers = user_token()
    pid = await create_project(client, headers)
    first = await client.post(f"/api/v1/projects/{pid}/runs", headers={**headers, "Idempotency-Key": "abc-123"})
    again = await client.post(f"/api/v1/projects/{pid}/runs", headers={**headers, "Idempotency-Key": "abc-123"})
    assert first.status_code == 202
    assert again.status_code == 200
    assert first.json()["run_id"] == again.json()["run_id"]
    assert enqueued == [{"task": "validation.run", "run_id": first.json()["run_id"], "user_id": str(user_id)}]


async def test_concurrency_and_monthly_quota(
    client: httpx.AsyncClient, maker: async_sessionmaker[AsyncSession]
) -> None:
    user_id, headers = user_token()
    p1, p2 = await create_project(client, headers), await create_project(client, headers)
    assert (await client.post(f"/api/v1/projects/{p1}/runs", headers=headers)).status_code == 202
    busy = await client.post(f"/api/v1/projects/{p2}/runs", headers=headers)
    assert busy.status_code == 429
    assert busy.json()["error"]["code"] == "rate_limited"

    async with maker() as session, session.begin():
        await session.execute(
            update(m.ValidationRun).where(m.ValidationRun.user_id == user_id).values(status="succeeded")
        )
        await session.execute(update(m.Profile).where(m.Profile.id == user_id).values(plan=Plan.FREE))
        for _ in range(5):
            session.add(m.UsageEvent(id=new_id(), user_id=user_id, kind="validation_run", units=1))
    over = await client.post(f"/api/v1/projects/{p2}/runs", headers=headers)
    assert over.status_code == 402
    assert over.json()["error"]["code"] == "quota_exceeded"


async def test_internal_plan_is_not_capped_monthly(
    client: httpx.AsyncClient, maker: async_sessionmaker[AsyncSession]
) -> None:
    user_id, headers = user_token()
    project = await create_project(client, headers)
    async with maker() as session, session.begin():
        await session.execute(update(m.Profile).where(m.Profile.id == user_id).values(plan=Plan.FREE))
        for _ in range(50):
            session.add(m.UsageEvent(id=new_id(), user_id=user_id, kind="validation_run", units=1))
    assert (await client.post(f"/api/v1/projects/{project}/runs", headers=headers)).status_code == 402

    async with maker() as session, session.begin():
        await session.execute(update(m.Profile).where(m.Profile.id == user_id).values(plan=Plan.INTERNAL))
    assert (await client.post(f"/api/v1/projects/{project}/runs", headers=headers)).status_code == 202
    listed = (await client.get("/api/v1/projects", headers=headers)).json()["items"]
    assert listed[0]["latest_run"]["status"] == "queued"


async def _start(client: httpx.AsyncClient, headers: dict[str, str]) -> str:
    pid = await create_project(client, headers)
    res = await client.post(f"/api/v1/projects/{pid}/runs", headers=headers)
    assert res.status_code == 202
    return str(res.json()["run_id"])


async def fake_graph(ctx: RunContext) -> RunOutcome:
    """Stands in for the Phase 8 graph: emits node events and writes findings."""
    await ctx.emit("node_started", node="collect_x")
    async with ctx.sessionmaker() as session, session.begin():
        scope = ctx.scope(session)
        doc_id, _ = await scope.add_document(
            ctx.run_id,
            source=Source.X,
            url="https://x.com/jane/status/1",
            canonical_url="https://x.com/jane/status/1",
            content_hash="h1",
            fetch_tier="syndication",
            raw_text="I spend 3 hours on every LinkedIn post and still hate it.",
            author_handle="jane",
            engagement={"likes": 120},
        )
        [chunk_id] = await scope.add_chunks(doc_id, ["I spend 3 hours on every LinkedIn post and still hate it."])
        claim = scope._add(
            m.Claim(
                id=new_id(),
                run_id=ctx.run_id,
                analyst="pain",
                text="Founders spend hours per post.",
                stance=Stance.SUPPORTS,
            )
        )
        await session.flush()
        scope._add(m.Citation(id=new_id(), claim_id=claim.id, chunk_id=chunk_id, verified=True, entailment_score=0.93))
        scope._add(
            m.Signal(
                id=new_id(),
                run_id=ctx.run_id,
                name="pain_intensity",
                value=0.8,
                method="engagement-weighted",
                inputs={},
            )
        )
        scope._add(
            m.Verdict(
                id=new_id(), run_id=ctx.run_id, verdict=VerdictKind.BUILD, confidence=0.72, reasons=["pain is real"]
            )
        )
    await ctx.emit("node_finished", node="collect_x", documents=1)
    return RunOutcome("succeeded")


def run_ctx(run_id: str, user_id: uuid.UUID, redis: Redis, maker: async_sessionmaker[AsyncSession]) -> RunContext:
    return RunContext(run_id=uuid.UUID(run_id), user_id=user_id, events=RunEvents(redis), sessionmaker=maker)


async def read_sse(client: httpx.AsyncClient, url: str, headers: dict[str, str]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    async with client.stream("GET", url, headers=headers) as res:
        assert res.status_code == 200
        assert res.headers["content-type"].startswith("text/event-stream")
        async for line in res.aiter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    return events


async def test_run_lifecycle_events_report_and_evidence(
    client: httpx.AsyncClient, redis: Redis, maker: async_sessionmaker[AsyncSession]
) -> None:
    user_id, headers = user_token()
    run_id = await _start(client, headers)
    await execute_run(run_ctx(run_id, user_id, redis, maker), fake_graph)

    events = await read_sse(client, f"/api/v1/runs/{run_id}/events", headers)
    assert [e["type"] for e in events] == ["status", "node_started", "node_finished", "status"]
    assert events[0]["status"] == "running"
    assert events[-1]["status"] == "succeeded"

    run = (await client.get(f"/api/v1/runs/{run_id}", headers=headers)).json()
    assert run["status"] == "succeeded"
    assert run["started_at"] and run["finished_at"]

    report = (await client.get(f"/api/v1/runs/{run_id}/report", headers=headers)).json()
    assert report["verdict"]["verdict"] == "build"
    [claim] = report["claims"]
    assert claim["citations"][0]["document"]["url"] == "https://x.com/jane/status/1"
    assert claim["citations"][0]["verified"] is True
    assert report["signals"][0]["name"] == "pain_intensity"

    detail = await client.get(f"/api/v1/runs/{run_id}/claims/{claim['id']}", headers=headers)
    assert detail.json()["text"] == "Founders spend hours per post."
    evidence = (await client.get(f"/api/v1/runs/{run_id}/evidence?source=x", headers=headers)).json()
    assert evidence["items"][0]["author_handle"] == "jane"
    assert (await client.get(f"/api/v1/runs/{run_id}/evidence?source=hn", headers=headers)).json()["items"] == []

    assert (await client.post(f"/api/v1/runs/{run_id}/cancel", headers=headers)).status_code == 409

    _, intruder = user_token()
    for path in ["", "/events", "/report", "/evidence", f"/claims/{claim['id']}"]:
        assert (await client.get(f"/api/v1/runs/{run_id}{path}", headers=intruder)).status_code == 404


async def test_sse_resumes_after_last_event_id(
    client: httpx.AsyncClient, redis: Redis, maker: async_sessionmaker[AsyncSession]
) -> None:
    user_id, headers = user_token()
    run_id = await _start(client, headers)
    await execute_run(run_ctx(run_id, user_id, redis, maker), fake_graph)
    all_events = await RunEvents(redis).read(run_id, block_ms=0)
    after_second = all_events[1].id
    resumed = await read_sse(client, f"/api/v1/runs/{run_id}/events", {**headers, "Last-Event-ID": after_second or ""})
    assert [e["type"] for e in resumed] == ["node_finished", "status"]


async def test_duplicate_delivery_runs_once(
    redis: Redis, maker: async_sessionmaker[AsyncSession], client: httpx.AsyncClient
) -> None:
    user_id, headers = user_token()
    run_id = await _start(client, headers)
    calls = 0

    async def slow(ctx: RunContext) -> RunOutcome:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.2)
        return RunOutcome("succeeded")

    ctx = run_ctx(run_id, user_id, redis, maker)
    await asyncio.gather(execute_run(ctx, slow), execute_run(ctx, slow))
    assert calls == 1
    await execute_run(ctx, slow)  # already finished → skipped
    assert calls == 1


async def test_cancel_queued_run_is_never_executed(
    client: httpx.AsyncClient, redis: Redis, maker: async_sessionmaker[AsyncSession]
) -> None:
    user_id, headers = user_token()
    run_id = await _start(client, headers)
    res = await client.post(f"/api/v1/runs/{run_id}/cancel", headers=headers)
    assert res.json()["status"] == "cancelled"

    async def must_not_run(ctx: RunContext) -> RunOutcome:
        raise AssertionError("cancelled run was executed")

    await execute_run(run_ctx(run_id, user_id, redis, maker), must_not_run)


async def test_runner_crash_fails_run_without_leaking_details(
    client: httpx.AsyncClient, redis: Redis, maker: async_sessionmaker[AsyncSession]
) -> None:
    user_id, headers = user_token()
    run_id = await _start(client, headers)

    async def boom(ctx: RunContext) -> RunOutcome:
        raise RuntimeError("secret internal detail")

    await execute_run(run_ctx(run_id, user_id, redis, maker), boom)
    events = await read_sse(client, f"/api/v1/runs/{run_id}/events", headers)
    assert events[-1] == {"type": "status", "ts": events[-1]["ts"], "status": "failed", "error_code": "internal_error"}
    assert "secret" not in json.dumps(events)


async def test_transient_failure_is_retried_not_failed(
    client: httpx.AsyncClient, redis: Redis, maker: async_sessionmaker[AsyncSession]
) -> None:
    user_id, headers = user_token()
    run_id = await _start(client, headers)

    async def flaky(ctx: RunContext) -> RunOutcome:
        raise ConnectionError("NIM timed out")

    with pytest.raises(ConnectionError):
        await execute_run(run_ctx(run_id, user_id, redis, maker), flaky)
    assert (await client.get(f"/api/v1/runs/{run_id}", headers=headers)).json()["status"] == "running"
    # the retry (lease released) completes it
    await execute_run(run_ctx(run_id, user_id, redis, maker), fake_graph)
    assert (await client.get(f"/api/v1/runs/{run_id}", headers=headers)).json()["status"] == "succeeded"


async def test_review_interrupt_and_resume(
    client: httpx.AsyncClient, redis: Redis, maker: async_sessionmaker[AsyncSession], enqueued: list[dict[str, Any]]
) -> None:
    user_id, headers = user_token()
    run_id = await _start(client, headers)

    async def needs_review(ctx: RunContext) -> RunOutcome:
        await fake_graph(ctx)
        return RunOutcome("awaiting_review")

    await execute_run(run_ctx(run_id, user_id, redis, maker), needs_review)
    report = (await client.get(f"/api/v1/runs/{run_id}/report", headers=headers)).json()
    claim_id = report["claims"][0]["id"]
    res = await client.post(f"/api/v1/runs/{run_id}/resume", json={"wrong_claim_ids": [claim_id]}, headers=headers)
    assert res.status_code == 202
    assert res.json()["status"] == "queued"
    assert enqueued[-1]["run_id"] == run_id
    flagged = (await client.get(f"/api/v1/runs/{run_id}/claims/{claim_id}", headers=headers)).json()
    assert flagged["flagged_wrong"] is True
    assert (await client.post(f"/api/v1/runs/{run_id}/resume", json={}, headers=headers)).status_code == 409


# ---- account ------------------------------------------------------------------------


async def test_me_export_and_delete(client: httpx.AsyncClient) -> None:
    user_id, headers = user_token()
    me = (await client.get("/api/v1/me", headers=headers)).json()
    assert me["id"] == str(user_id)
    assert me["plan"] == "free"
    await create_project(client, headers)
    export = (await client.get("/api/v1/me/export", headers=headers)).json()
    assert len(export["tables"]["projects"]) == 1
    assert (await client.delete("/api/v1/me", headers=headers)).status_code == 204
    assert (await client.get("/api/v1/projects", headers=headers)).json()["items"] == []


# ---- studio edit ("fix it for me") ---------------------------------------------------

SLOP_POST = (
    "Here's the thing: onboarding isn't about features. It's about trust. "
    "We utilize a checklist so every new user gets a win on day one."
)


def scripted_editor(monkeypatch: pytest.MonkeyPatch, answer: str) -> list[str]:
    """Stands in for the LLM stack; records the post it was asked to edit."""
    import deno_llm

    seen: list[str] = []

    class Runnable:
        async def ainvoke(self, messages: list[Any], config: Any) -> Any:
            seen.append(str(messages[-1].content))
            return type("Msg", (), {"content": answer})()

    stack = type(
        "Stack", (), {"router": type("Router", (), {"chat": lambda self, role, temperature=0: Runnable()})()}
    )()
    monkeypatch.setattr(deno_llm, "build_stack", lambda settings, redis=None: stack)
    return seen


async def _audits_used(client: httpx.AsyncClient, headers: dict[str, str]) -> int:
    usage = (await client.get("/api/v1/billing", headers=headers)).json()["usage"]
    return next(u["used"] for u in usage if u["kind"] == "audit")


async def test_fix_it_for_me_returns_the_edit_and_what_changed(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, headers = user_token()
    seen = scripted_editor(
        monkeypatch,
        "EDITED:\nOnboarding is about trust. We use a checklist so every new user gets a win on day one.\n"
        "WHAT CHANGED:\n- Cut the throat-clearing opener\n- Stated the binary contrast directly\n- utilize -> use\n",
    )
    res = await client.post("/api/v1/gates/edit", json={"text": SLOP_POST, "platform": "linkedin"}, headers=headers)

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["edited"].startswith("Onboarding is about trust.")
    assert body["changes"] == [
        "Cut the throat-clearing opener",
        "Stated the binary contrast directly",
        "utilize -> use",
    ]
    assert body["passed"] is True
    assert "L2.binary_contrast" in seen[0], "the editor is told what the gates found"
    assert await _audits_used(client, headers) == 1


async def test_an_edit_that_invents_a_number_does_not_come_back_clean(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, headers = user_token()
    scripted_editor(
        monkeypatch,
        "EDITED:\nOnboarding is about trust. Our checklist cut churn by 40% for new users.\nWHAT CHANGED:\n- Tightened\n",
    )
    res = await client.post("/api/v1/gates/edit", json={"text": SLOP_POST, "platform": "linkedin"}, headers=headers)

    body = res.json()
    assert body["passed"] is False
    assert any(f["rule_id"] == "L1.unsourced_number" for g in body["layers"] for f in g["findings"])


async def test_an_unusable_editor_answer_is_503_and_costs_nothing(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, headers = user_token()
    scripted_editor(monkeypatch, "Sure! Here is a better version of your post.")
    res = await client.post("/api/v1/gates/edit", json={"text": SLOP_POST, "platform": "linkedin"}, headers=headers)

    assert res.status_code == 503
    assert await _audits_used(client, headers) == 0


async def test_fix_it_for_me_is_refused_once_the_audit_quota_is_spent(
    client: httpx.AsyncClient, maker: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    user_id, headers = user_token()
    assert (await client.get("/api/v1/me", headers=headers)).status_code == 200  # creates the profile
    async with maker() as session, session.begin():
        session.add(m.UsageEvent(id=new_id(), user_id=user_id, kind=UsageKind.AUDIT, units=200, cost_usd=0, meta={}))
    seen = scripted_editor(monkeypatch, "EDITED:\nanything\nWHAT CHANGED:\n- x")

    res = await client.post("/api/v1/gates/edit", json={"text": SLOP_POST, "platform": "linkedin"}, headers=headers)

    assert res.status_code == 402
    assert res.json()["error"]["code"] == "quota_exceeded"
    assert seen == [], "the LLM is never called past the quota"


async def test_an_editor_that_crashes_is_503_and_costs_nothing(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import deno_llm

    class Broken:
        async def ainvoke(self, messages: list[Any], config: Any) -> Any:
            raise TimeoutError("NIM timed out")

    stack = type("Stack", (), {"router": type("Router", (), {"chat": lambda self, role, temperature=0: Broken()})()})()
    monkeypatch.setattr(deno_llm, "build_stack", lambda settings, redis=None: stack)
    _, headers = user_token()

    res = await client.post("/api/v1/gates/edit", json={"text": SLOP_POST, "platform": "linkedin"}, headers=headers)

    assert res.status_code == 503
    assert "by hand" in res.json()["error"]["message"]
    assert await _audits_used(client, headers) == 0


async def test_the_edit_and_the_audit_agree_on_community_rules(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both use the target community's rules, so "passes" means the same thing in both places."""
    _, headers = user_token()
    edited = "We built a checklist for onboarding. Try it at https://example.com/checklist if you want."
    scripted_editor(monkeypatch, f"EDITED:\n{edited}\nWHAT CHANGED:\n- Cut the opener")
    params = {"platform": "reddit", "community": "r/SaaS", "is_promotional": True}

    fixed = (await client.post("/api/v1/gates/edit", json={"text": SLOP_POST, **params}, headers=headers)).json()
    audit = (await client.post("/api/v1/gates/audit", json={"text": edited, **params}, headers=headers)).json()

    def compliance(layers: list[dict[str, Any]]) -> list[str]:
        return sorted(f["rule_id"] for layer in layers if layer["layer"] == "compliance" for f in layer["findings"])

    assert compliance(fixed["layers"]), "r/SaaS's rules flag a promotional link"
    assert compliance(fixed["layers"]) == compliance(audit["layers"])
    assert fixed["passed"] == audit["passed"]


@pytest.mark.parametrize(
    ("original", "edited", "flagged"),
    [
        ("Three customers asked for annual billing.", "Three customers asked for annual plans.", False),
        ("Three customers asked for annual billing.", "Five customers asked for annual plans.", True),
        ("We cut churn to 4% last quarter.", "Churn fell to 4% last quarter.", False),
        ("We cut churn last quarter.", "Churn fell 12% last quarter.", True),
    ],
    ids=["kept-word", "invented-word", "kept-figure", "invented-figure"],
)
async def test_only_numbers_from_the_original_survive_an_edit(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, original: str, edited: str, flagged: bool
) -> None:
    _, headers = user_token()
    scripted_editor(monkeypatch, f"EDITED:\n{edited}\nWHAT CHANGED:\n- Tightened")

    body = (
        await client.post("/api/v1/gates/edit", json={"text": original, "platform": "linkedin"}, headers=headers)
    ).json()

    unsourced = any(f["rule_id"] == "L1.unsourced_number" for g in body["layers"] for f in g["findings"])
    assert unsourced is flagged
    if flagged:
        assert body["passed"] is False


async def test_an_edit_that_keeps_slop_in_typographic_quotes_is_still_caught(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, headers = user_token()
    scripted_editor(
        monkeypatch, "EDITED:\nOnboarding isn\u2019t about features. It\u2019s about trust.\nWHAT CHANGED:\n- x"
    )

    body = (
        await client.post("/api/v1/gates/edit", json={"text": SLOP_POST, "platform": "linkedin"}, headers=headers)
    ).json()

    assert body["passed"] is False
    assert any(f["rule_id"] == "L2.binary_contrast" for g in body["layers"] for f in g["findings"])


async def test_dashes_the_editor_adds_are_fixed_mechanically(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, headers = user_token()
    scripted_editor(
        monkeypatch,
        "EDITED:\nWe use a checklist \u2014 every new user gets a win on day one, 9\u20135.\nWHAT CHANGED:\n- x",
    )

    body = (
        await client.post("/api/v1/gates/edit", json={"text": SLOP_POST, "platform": "linkedin"}, headers=headers)
    ).json()

    assert body["edited"] == "We use a checklist, every new user gets a win on day one, 9\u20135."


# ---- limits -------------------------------------------------------------------------


async def test_rate_limit_returns_429_with_retry_after(maker: async_sessionmaker[AsyncSession], redis: Redis) -> None:
    app = create_app(Settings(environment="test", valkey_url=VALKEY_URL, api_rate_limit_per_minute=3))
    app.state.sessionmaker, app.state.redis = maker, redis
    _verifier = make_verifier()
    app.dependency_overrides[auth.get_verifier] = lambda: _verifier
    _, headers = user_token()
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c,
    ):
        codes = [(await c.get("/api/v1/projects", headers=headers)).status_code for _ in range(4)]
        assert codes == [200, 200, 200, 429]
        res = await c.get("/api/v1/projects", headers=headers)
        assert int(res.headers["retry-after"]) >= 1


async def test_oversized_body_is_413(client: httpx.AsyncClient) -> None:
    _, headers = user_token()
    res = await client.post(
        "/api/v1/projects", content=b"x" * 2_000_000, headers={**headers, "Content-Type": "application/json"}
    )
    assert res.status_code == 413


async def test_openapi_lists_v1_routes(client: httpx.AsyncClient) -> None:
    spec = (await client.get("/api/v1/openapi.json")).json()
    paths = set(spec["paths"])
    for p in [
        "/api/v1/projects",
        "/api/v1/projects/{project_id}/runs",
        "/api/v1/runs/{run_id}/events",
        "/api/v1/runs/{run_id}/report",
        "/api/v1/me/export",
    ]:
        assert p in paths
    assert not any(p.startswith("/api/projects") for p in paths)  # legacy routes stay out of the contract


# ---- takedowns ------------------------------------------------------------------------


async def test_takedown_intake_is_public_and_review_is_admin_only(
    client: httpx.AsyncClient, maker: async_sessionmaker[AsyncSession]
) -> None:
    bad = await client.post("/api/v1/takedowns", json={"reason": "no target"})
    assert bad.status_code == 422
    res = await client.post(
        "/api/v1/takedowns", json={"author_handle": "@victim", "reason": "Please remove my posts", "contact": "v@x.io"}
    )
    assert res.status_code == 202, res.text
    tid = res.json()["id"]

    _, user = user_token()
    assert (await client.get("/api/v1/admin/takedowns", headers=user)).status_code == 404
    assert (await client.post(f"/api/v1/admin/takedowns/{tid}/approve", headers=user)).status_code == 404

    admin_id, admin = user_token()
    await client.get("/api/v1/me", headers=admin)  # creates the profile
    async with maker() as s, s.begin():
        await s.execute(update(m.Profile).where(m.Profile.id == admin_id).values(role="admin"))
    listed = await client.get("/api/v1/admin/takedowns?status=received", headers=admin)
    assert [t["id"] for t in listed.json()] == [tid]
    approved = await client.post(f"/api/v1/admin/takedowns/{tid}/approve", headers=admin)
    assert approved.json() == {"id": tid, "status": "processed", "purged_documents": 0}
    assert (await client.post(f"/api/v1/admin/takedowns/{tid}/reject", headers=admin)).status_code == 409


async def test_takedown_intake_is_rate_limited_per_ip(client: httpx.AsyncClient) -> None:
    body = {"url": "https://x.com/a/status/1", "reason": "mine"}
    codes = [(await client.post("/api/v1/takedowns", json=body)).status_code for _ in range(6)]
    assert codes == [202] * 5 + [429]
