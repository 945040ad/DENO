"""One request budget for everything that calls NVIDIA NIM with our key.

NIM caps a key at 40 requests/minute across chat, embeddings and rerank. Every
call goes through a ``Limiter.acquire()`` first. ``ValkeyLimiter`` shares the
budget across API, worker and scheduler processes; ``LocalLimiter`` is the
single-process fallback (dev, tests, Valkey down).
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import Awaitable, Callable
from typing import Protocol

from redis.asyncio import Redis
from redis.exceptions import RedisError

from deno_core.logging import get_logger
from deno_core.ratelimit import SlidingWindowLimiter

log = get_logger(__name__)
NIM_KEY = "nim:requests"


class Limiter(Protocol):
    async def acquire(self) -> None: ...


class LocalLimiter:
    """In-process sliding window: at most ``limit`` acquisitions per ``window_s``."""

    def __init__(
        self,
        limit: int,
        window_s: float = 60.0,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.limit, self.window_s = limit, window_s
        self._stamps: deque[float] = deque()
        self._lock = asyncio.Lock()
        self._clock, self._sleep = clock, sleep

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = self._clock()
                while self._stamps and self._stamps[0] <= now - self.window_s:
                    self._stamps.popleft()
                if len(self._stamps) < self.limit:
                    self._stamps.append(now)
                    return
                await self._sleep(self._stamps[0] + self.window_s - now + 0.01)


class ValkeyLimiter:
    """Cross-process sliding window on Valkey; degrades to a local window if Valkey fails."""

    def __init__(self, redis: Redis, limit: int, window_s: int = 60, *, key: str = NIM_KEY) -> None:
        self._limiter = SlidingWindowLimiter(redis, prefix="llm")
        self._key, self.limit, self.window_s = key, limit, window_s
        self._fallback = LocalLimiter(limit, window_s)

    async def acquire(self) -> None:
        while True:
            try:
                decision = await self._limiter.hit(self._key, self.limit, self.window_s)
            except RedisError:
                log.warning("llm_limiter_valkey_unavailable")
                await self._fallback.acquire()
                return
            if decision.allowed:
                return
            await asyncio.sleep(decision.retry_after_s)


class NullLimiter:
    async def acquire(self) -> None:
        return None
