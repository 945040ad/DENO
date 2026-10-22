"""Polite, safe HTTP for every source client.

One ``Fetcher`` enforces, in order, for each request:

1. **Allow-list + SSRF guard** — only registered hosts; public hosts must not
   resolve to private/loopback/link-local addresses; redirects are followed by
   hand and every hop is re-checked.
2. **Access policy** — hosts marked ``robots`` are checked against their
   robots.txt for our user agent. A disallowed fetch raises ``AccessDenied``
   unless the operator explicitly opted that host in (documented, auditable).
3. **Circuit breaker** per source — after repeated failures the source is
   skipped for a cool-down instead of hammering it.
4. **Cache** (TTL per call) — identical requests inside a run/day hit the cache.
   Cache misses count against a global **per-source daily cap**.
5. **Per-host token bucket** — steady request spacing, bursts capped.
6. **Retries** on 408/429/5xx and transport errors, honouring ``Retry-After``
   and ``X-RateLimit-Reset``, otherwise exponential backoff with jitter.

Health counters per source feed the ``source_health`` table and alerts.
"""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import random
import time
from collections import deque
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from typing import Literal, Protocol
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from deno_sources.models import AccessDenied, SourceUnavailable

DEFAULT_UA = "DenoResearchBot/0.1 (+https://deno.gtm/bot; human-initiated research, low volume)"
BROWSER_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"
ROBOTS_TOKEN = "DenoResearchBot"  # noqa: S105 — robots.txt user-agent token, not a secret

RETRY_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})
BLOCK_STATUSES = frozenset({999})  # LinkedIn's "go away"
MAX_RETRY_WAIT_S = 30.0
MAX_REDIRECTS = 3

Resolver = Callable[[str], Awaitable[list[str]]]


@dataclass(frozen=True)
class HostPolicy:
    rate_per_s: float = 1.0
    burst: int = 2
    access: Literal["api", "robots"] = "robots"  # "api": a documented programmatic endpoint


@dataclass
class FetchResult:
    status: int
    url: str
    text: str
    headers: Mapping[str, str]
    from_cache: bool = False

    def json(self) -> object:
        import json

        return json.loads(self.text)


class Cache(Protocol):
    async def get(self, key: str) -> str | None: ...
    async def set(self, key: str, value: str, ttl_s: int) -> None: ...
    async def incr(self, key: str, ttl_s: int) -> int: ...


class MemoryCache:
    def __init__(self, max_items: int = 2000) -> None:
        self._data: dict[str, tuple[float, str]] = {}
        self._max = max_items

    async def get(self, key: str) -> str | None:
        hit = self._data.get(key)
        if hit is None or hit[0] < time.monotonic():
            self._data.pop(key, None)
            return None
        return hit[1]

    async def set(self, key: str, value: str, ttl_s: int) -> None:
        if len(self._data) >= self._max:
            self._data.pop(next(iter(self._data)))
        self._data[key] = (time.monotonic() + ttl_s, value)

    async def incr(self, key: str, ttl_s: int) -> int:
        count = int(await self.get(key) or 0) + 1
        hit = self._data.get(key)
        expires = hit[0] if hit else time.monotonic() + ttl_s
        self._data[key] = (expires, str(count))
        return count


class ValkeyCache:
    """Shared cache across workers (optional `valkey` extra)."""

    def __init__(self, redis: object, prefix: str = "src:cache:") -> None:
        self._redis = redis
        self._prefix = prefix

    async def get(self, key: str) -> str | None:
        value = await self._redis.get(self._prefix + key)  # type: ignore[attr-defined]
        return value.decode() if isinstance(value, bytes) else value

    async def set(self, key: str, value: str, ttl_s: int) -> None:
        await self._redis.set(self._prefix + key, value, ex=ttl_s)  # type: ignore[attr-defined]

    async def incr(self, key: str, ttl_s: int) -> int:
        async with self._redis.pipeline(transaction=True) as pipe:  # type: ignore[attr-defined]
            pipe.incr(self._prefix + key)
            pipe.expire(self._prefix + key, ttl_s, nx=True)
            count, _ = await pipe.execute()
        return int(count)


class TokenBucket:
    def __init__(self, rate_per_s: float, burst: int) -> None:
        self.rate, self.capacity = rate_per_s, float(burst)
        self.tokens, self.updated = float(burst), time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
                self.updated = now
                if self.tokens >= 1:
                    self.tokens -= 1
                    return
                await asyncio.sleep((1 - self.tokens) / self.rate)


@dataclass
class CircuitBreaker:
    failure_threshold: int = 5
    cooldown_s: float = 60.0
    failures: int = 0
    opened_at: float | None = None

    def allow(self) -> bool:
        if self.opened_at is None:
            return True
        return time.monotonic() - self.opened_at >= self.cooldown_s  # half-open after the cool-down

    def record(self, ok: bool) -> None:
        if ok:
            self.failures, self.opened_at = 0, None
            return
        self.failures += 1
        if self.failures >= self.failure_threshold:
            self.opened_at = time.monotonic()


@dataclass
class SourceHealth:
    requests: int = 0
    successes: int = 0
    blocked: int = 0
    latencies_ms: deque[float] = field(default_factory=lambda: deque(maxlen=500))

    def snapshot(self) -> dict[str, float | int | None]:
        lat = sorted(self.latencies_ms)
        p95 = lat[int(0.95 * (len(lat) - 1))] if lat else None
        return {
            "requests": self.requests,
            "successes": self.successes,
            "blocked": self.blocked,
            "success_rate": round(self.successes / self.requests, 3) if self.requests else None,
            "p95_ms": round(p95) if p95 is not None else None,
        }


async def system_resolver(host: str) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, 443)
    return [str(info[4][0]) for info in infos]


def _is_public(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    return not (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    )


class Fetcher:
    def __init__(
        self,
        hosts: Mapping[str, HostPolicy],
        *,
        internal_hosts: Mapping[str, HostPolicy] | None = None,
        robots_opt_in: set[str] | None = None,
        daily_caps: Mapping[str, int] | None = None,
        cache: Cache | None = None,
        user_agent: str = DEFAULT_UA,
        timeout_s: float = 20.0,
        resolver: Resolver = system_resolver,
        transport: httpx.AsyncBaseTransport | None = None,
        max_attempts: int = 3,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._hosts = dict(hosts)
        self._internal = dict(internal_hosts or {})
        self._robots_opt_in = {h.lower() for h in (robots_opt_in or set())}
        self._cache = cache or MemoryCache()
        self._daily_caps = dict(daily_caps or {})
        self._ua = user_agent
        self._resolver = resolver
        self._max_attempts = max_attempts
        self._sleep = sleep
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_s, connect=10.0),
            follow_redirects=False,
            http2=transport is None,
            transport=transport,
            headers={"Accept-Encoding": "gzip, deflate"},
        )
        self._buckets: dict[str, TokenBucket] = {}
        self._robots: dict[str, RobotFileParser | None] = {}
        self._robots_lock = asyncio.Lock()
        self.breakers: dict[str, CircuitBreaker] = {}
        self.health: dict[str, SourceHealth] = {}

    async def aclose(self) -> None:
        await self._client.aclose()

    def drain_health(self) -> dict[str, dict[str, float | int | None]]:
        """Snapshot per-source counters and reset them, so each flush to `source_health` is a delta."""
        drained = {name: h.snapshot() for name, h in self.health.items() if h.requests}
        self.health = {}
        return drained

    # ---- policy -----------------------------------------------------------------

    def _policy(self, host: str) -> tuple[HostPolicy, bool] | None:
        """(policy, internal) for an allow-listed host (exact or subdomain match)."""
        for table, internal in ((self._internal, True), (self._hosts, False)):
            for domain, policy in table.items():
                if host == domain or host.endswith("." + domain):
                    return policy, internal
        return None

    async def _check_url(self, url: str) -> HostPolicy:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        resolved = self._policy(host)
        if resolved is None:
            raise AccessDenied(f"host not allow-listed: {host}")
        policy, internal = resolved
        if internal:
            return policy
        if parts.scheme != "https":
            raise AccessDenied(f"only https is allowed for public hosts: {url}")
        try:
            addresses = await self._resolver(host)
        except OSError as exc:
            raise SourceUnavailable(f"DNS failed for {host}") from exc
        if not addresses or not all(_is_public(a) for a in addresses):
            raise AccessDenied(f"{host} resolves to a non-public address")
        if policy.access == "robots" and host not in self._robots_opt_in and not await self._robots_allow(url):
            raise AccessDenied(f"robots.txt disallows {url} for {ROBOTS_TOKEN}; operator opt-in required")
        return policy

    async def _robots_allow(self, url: str) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        async with self._robots_lock:
            if origin not in self._robots:
                self._robots[origin] = await self._load_robots(origin)
        parser = self._robots[origin]
        return parser is not None and parser.can_fetch(ROBOTS_TOKEN, url)

    async def _load_robots(self, origin: str) -> RobotFileParser | None:
        """Parsed robots.txt; None when it can't be read (fail closed)."""
        try:
            res = await self._client.get(f"{origin}/robots.txt", headers={"User-Agent": self._ua})
        except httpx.HTTPError:
            return None
        if res.status_code >= 500:
            return None
        parser = RobotFileParser()
        parser.parse([] if res.status_code >= 400 else res.text.splitlines())  # 4xx: no robots.txt = allowed
        return parser

    # ---- fetching ------------------------------------------------------------------

    @property
    def sleep(self) -> Callable[[float], Awaitable[None]]:
        """The injected sleep, so a client can back off on its own retryable errors in tests."""
        return self._sleep

    async def get(
        self,
        url: str,
        *,
        source: str,
        params: Mapping[str, str | int] | None = None,
        headers: Mapping[str, str] | None = None,
        cache_ttl_s: int | None = None,
        browser_ua: bool = False,
    ) -> FetchResult:
        full_url = str(httpx.URL(url, params=params)) if params else url
        breaker = self.breakers.setdefault(source, CircuitBreaker())
        health = self.health.setdefault(source, SourceHealth())
        if not breaker.allow():
            raise SourceUnavailable(f"{source} circuit open")

        cache_key = hashlib.sha256(f"{source}|{full_url}".encode()).hexdigest()
        if cache_ttl_s:
            cached = await self._cache.get(cache_key)
            if cached is not None:
                return FetchResult(200, full_url, cached, {}, from_cache=True)

        if (cap := self._daily_caps.get(source)) is not None:
            day = time.strftime("%Y-%m-%d", time.gmtime())
            if await self._cache.incr(f"cap:{source}:{day}", 26 * 3600) > cap:
                raise SourceUnavailable(f"{source} daily cap of {cap} requests reached")

        request_headers = {"User-Agent": BROWSER_UA if browser_ua else self._ua, **(headers or {})}
        started = time.monotonic()
        health.requests += 1
        try:
            result = await self._get_with_retries(full_url, request_headers)
        except AccessDenied:
            health.blocked += 1
            raise
        except SourceUnavailable:
            breaker.record(ok=False)
            raise
        ok = 200 <= result.status < 300
        # The breaker tracks outages (5xx, 429, transport); a 4xx is about this request, not the source.
        breaker.record(ok=result.status < 500 and result.status != 429)
        if ok:
            health.successes += 1
            health.latencies_ms.append((time.monotonic() - started) * 1000)
            if cache_ttl_s:
                await self._cache.set(cache_key, result.text, cache_ttl_s)
        return result

    async def _get_with_retries(self, url: str, headers: dict[str, str]) -> FetchResult:
        attempt = 0
        while True:
            attempt += 1
            try:
                result = await self._get_following_redirects(url, headers)
            except httpx.TransportError as exc:
                if attempt >= self._max_attempts:
                    raise SourceUnavailable(f"transport error: {type(exc).__name__}") from exc
                await self._sleep(self._backoff(attempt))
                continue
            if result.status in BLOCK_STATUSES:
                raise SourceUnavailable(f"blocked by upstream (HTTP {result.status})")
            if result.status in RETRY_STATUSES and attempt < self._max_attempts:
                await self._sleep(self._retry_wait(result.headers, attempt))
                continue
            return result

    async def _get_following_redirects(self, url: str, headers: dict[str, str]) -> FetchResult:
        for _ in range(MAX_REDIRECTS + 1):
            policy = await self._check_url(url)
            host = (urlsplit(url).hostname or "").lower()
            await self._bucket(host, policy).acquire()
            res = await self._client.get(url, headers=headers)
            if res.is_redirect and "location" in res.headers:
                target = urljoin(url, res.headers["location"])
                if "authwall" in target or "/login" in target or "checkpoint" in target:
                    raise SourceUnavailable("redirected to a login wall")
                url = target
                continue
            return FetchResult(res.status_code, str(res.url), res.text, res.headers)
        raise SourceUnavailable("too many redirects")

    def _bucket(self, host: str, policy: HostPolicy) -> TokenBucket:
        if host not in self._buckets:
            self._buckets[host] = TokenBucket(policy.rate_per_s, policy.burst)
        return self._buckets[host]

    @staticmethod
    def _backoff(attempt: int) -> float:
        return min(MAX_RETRY_WAIT_S, float(2 ** (attempt - 1)) + random.uniform(0, 1))  # noqa: S311 — jitter, not crypto

    def _retry_wait(self, headers: Mapping[str, str], attempt: int) -> float:
        retry_after = headers.get("retry-after")
        if retry_after:
            if retry_after.strip().isdigit():
                return min(MAX_RETRY_WAIT_S, float(retry_after))
            try:
                return min(
                    MAX_RETRY_WAIT_S, max(0.0, float(parsedate_to_datetime(retry_after).timestamp()) - time.time())
                )
            except (TypeError, ValueError):
                pass
        reset = headers.get("x-ratelimit-reset")
        if reset and reset.replace(".", "", 1).isdigit():
            value = float(reset)
            wait = value - time.time() if value > 1_000_000_000 else value  # epoch seconds or delta
            return min(MAX_RETRY_WAIT_S, max(0.0, wait))
        return self._backoff(attempt)
