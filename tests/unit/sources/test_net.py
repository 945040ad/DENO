"""Fetcher safety and politeness guarantees (HTTP mocked with respx; no network)."""

import httpx
import pytest
import respx

from deno_sources.models import AccessDenied, SourceUnavailable
from deno_sources.net import Fetcher, HostPolicy
from deno_sources.registry import SourceConfig, build_fetcher

PUBLIC_IP = "93.184.216.34"


async def public(_: str) -> list[str]:
    return [PUBLIC_IP]


async def private(_: str) -> list[str]:
    return ["10.0.0.7"]


def fetcher(**kw: object) -> tuple[Fetcher, list[float]]:
    sleeps: list[float] = []

    async def fake_sleep(s: float) -> None:
        sleeps.append(s)

    hosts = {
        "api.example.com": HostPolicy(rate_per_s=100, burst=100, access="api"),
        "site.example.com": HostPolicy(rate_per_s=100, burst=100, access="robots"),
    }
    options: dict[str, object] = {"resolver": public, "sleep": fake_sleep, "transport": httpx.AsyncHTTPTransport()}
    options.update(kw)
    return Fetcher(hosts, internal_hosts={"searxng": HostPolicy(access="api")}, **options), sleeps  # type: ignore[arg-type]


@respx.mock
async def test_rejects_hosts_not_on_the_allow_list() -> None:
    f, _ = fetcher()
    with pytest.raises(AccessDenied, match="not allow-listed"):
        await f.get("https://evil.example.net/x", source="t")


@respx.mock
async def test_rejects_plain_http_for_public_hosts() -> None:
    f, _ = fetcher()
    with pytest.raises(AccessDenied, match="https"):
        await f.get("http://api.example.com/x", source="t")


@respx.mock
async def test_ssrf_guard_blocks_hosts_resolving_to_private_ips() -> None:
    f, _ = fetcher(resolver=private)
    with pytest.raises(AccessDenied, match="non-public"):
        await f.get("https://api.example.com/x", source="t")


@respx.mock
async def test_internal_hosts_skip_dns_and_scheme_checks() -> None:
    respx.get("http://searxng/search").respond(200, json={"results": []})
    f, _ = fetcher(resolver=private)
    assert (await f.get("http://searxng/search", source="searxng")).status == 200


@respx.mock
async def test_redirect_to_disallowed_host_is_refused() -> None:
    respx.get("https://api.example.com/r").respond(302, headers={"Location": "https://evil.example.net/steal"})
    f, _ = fetcher()
    with pytest.raises(AccessDenied):
        await f.get("https://api.example.com/r", source="t")


@respx.mock
async def test_redirect_to_login_wall_is_treated_as_blocked() -> None:
    respx.get("https://api.example.com/post").respond(302, headers={"Location": "https://api.example.com/authwall?x=1"})
    f, _ = fetcher()
    with pytest.raises(SourceUnavailable, match="login wall"):
        await f.get("https://api.example.com/post", source="t")


@respx.mock
async def test_robots_disallow_blocks_unless_opted_in() -> None:
    respx.get("https://site.example.com/robots.txt").respond(200, text="User-agent: *\nDisallow: /")
    page = respx.get("https://site.example.com/page").respond(200, text="hello")
    f, _ = fetcher()
    with pytest.raises(AccessDenied, match="opt-in"):
        await f.get("https://site.example.com/page", source="t")
    assert not page.called
    assert f.health["t"].blocked == 1

    opted, _ = fetcher(robots_opt_in={"site.example.com"})
    assert (await opted.get("https://site.example.com/page", source="t")).text == "hello"


@respx.mock
async def test_robots_allow_and_missing_robots_allow() -> None:
    respx.get("https://site.example.com/robots.txt").respond(404)
    respx.get("https://site.example.com/page").respond(200, text="ok")
    f, _ = fetcher()
    assert (await f.get("https://site.example.com/page", source="t")).status == 200


@respx.mock
async def test_unreadable_robots_fails_closed() -> None:
    respx.get("https://site.example.com/robots.txt").respond(503)
    f, _ = fetcher()
    with pytest.raises(AccessDenied):
        await f.get("https://site.example.com/page", source="t")


@respx.mock
async def test_retries_honour_retry_after_then_succeed() -> None:
    route = respx.get("https://api.example.com/x")
    route.side_effect = [httpx.Response(429, headers={"Retry-After": "7"}), httpx.Response(200, text="ok")]
    f, sleeps = fetcher()
    res = await f.get("https://api.example.com/x", source="t")
    assert res.text == "ok"
    assert sleeps == [7.0]


@respx.mock
async def test_retry_wait_is_capped_and_uses_ratelimit_reset() -> None:
    route = respx.get("https://api.example.com/x")
    route.side_effect = [
        httpx.Response(503, headers={"Retry-After": "3600"}),
        httpx.Response(429, headers={"X-RateLimit-Reset": "4"}),
        httpx.Response(200, text="ok"),
    ]
    f, sleeps = fetcher()
    await f.get("https://api.example.com/x", source="t")
    assert sleeps == [30.0, 4.0]


@respx.mock
async def test_gives_up_after_max_attempts_and_returns_last_response() -> None:
    respx.get("https://api.example.com/x").respond(500)
    f, sleeps = fetcher()
    res = await f.get("https://api.example.com/x", source="t")
    assert res.status == 500
    assert len(sleeps) == 2


@respx.mock
async def test_linkedin_999_is_blocked_without_retry() -> None:
    route = respx.get("https://api.example.com/x").respond(999)
    f, sleeps = fetcher()
    with pytest.raises(SourceUnavailable, match="999"):
        await f.get("https://api.example.com/x", source="t")
    assert route.call_count == 1
    assert sleeps == []


@respx.mock
async def test_transport_errors_retry_then_raise() -> None:
    respx.get("https://api.example.com/x").mock(side_effect=httpx.ConnectError("boom"))
    f, sleeps = fetcher()
    with pytest.raises(SourceUnavailable, match="transport"):
        await f.get("https://api.example.com/x", source="t")
    assert len(sleeps) == 2


@respx.mock
async def test_circuit_opens_after_repeated_failures() -> None:
    route = respx.get("https://api.example.com/x").respond(999)
    f, _ = fetcher()
    for _ in range(5):
        with pytest.raises(SourceUnavailable):
            await f.get("https://api.example.com/x", source="flaky")
    with pytest.raises(SourceUnavailable, match="circuit open"):
        await f.get("https://api.example.com/x", source="flaky")
    assert route.call_count == 5


@respx.mock
async def test_cache_serves_repeat_requests() -> None:
    route = respx.get("https://api.example.com/x", params={"q": "a"}).respond(200, text="one")
    f, _ = fetcher()
    first = await f.get("https://api.example.com/x", source="t", params={"q": "a"}, cache_ttl_s=60)
    second = await f.get("https://api.example.com/x", source="t", params={"q": "a"}, cache_ttl_s=60)
    assert (first.text, second.text) == ("one", "one")
    assert second.from_cache
    assert route.call_count == 1


@respx.mock
async def test_health_snapshot_counts_successes() -> None:
    respx.get("https://api.example.com/x").respond(200, text="ok")
    f, _ = fetcher()
    for _ in range(3):
        await f.get("https://api.example.com/x", source="t")
    snap = f.health["t"].snapshot()
    assert snap["requests"] == 3
    assert snap["success_rate"] == 1.0
    assert snap["p95_ms"] is not None


def test_drain_health_returns_deltas_and_resets() -> None:
    from deno_sources.net import SourceHealth

    fetcher = build_fetcher(SourceConfig(searxng_url="http://searxng:8080"))
    fetcher.health["hn"] = SourceHealth(requests=2, successes=1)
    fetcher.health["x"] = SourceHealth()
    assert set(fetcher.drain_health()) == {"hn"}
    assert fetcher.drain_health() == {}


@respx.mock
async def test_daily_cap_stops_a_source_but_cache_hits_are_free() -> None:
    async def public(_: str) -> list[str]:
        return ["93.184.216.34"]

    route = respx.get("https://hn.algolia.com/api/v1/search").respond(200, json={"hits": []})
    config = SourceConfig(searxng_url="http://searxng:8080", daily_caps={"hn": 2})
    fetcher = build_fetcher(config, resolver=public, transport=httpx.AsyncHTTPTransport())
    for q in ("a", "b"):
        await fetcher.get("https://hn.algolia.com/api/v1/search", source="hn", params={"query": q}, cache_ttl_s=60)
    await fetcher.get("https://hn.algolia.com/api/v1/search", source="hn", params={"query": "a"}, cache_ttl_s=60)
    with pytest.raises(SourceUnavailable, match="daily cap"):
        await fetcher.get("https://hn.algolia.com/api/v1/search", source="hn", params={"query": "c"})
    assert route.call_count == 2
