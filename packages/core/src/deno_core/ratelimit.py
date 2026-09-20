"""Sliding-window rate limiter on Valkey (sorted set per key, atomic via Lua)."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

from redis.asyncio import Redis

# KEYS[1] = bucket; ARGV = now_ms, window_ms, limit, member
_SLIDING_WINDOW = """
redis.call('ZREMRANGEBYSCORE', KEYS[1], 0, ARGV[1] - ARGV[2])
local count = redis.call('ZCARD', KEYS[1])
if count >= tonumber(ARGV[3]) then
  local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
  return {0, count, oldest[2] or ARGV[1]}
end
redis.call('ZADD', KEYS[1], ARGV[1], ARGV[4])
redis.call('PEXPIRE', KEYS[1], ARGV[2])
return {1, count + 1, 0}
"""


@dataclass(frozen=True)
class RateDecision:
    allowed: bool
    remaining: int
    retry_after_s: int


class SlidingWindowLimiter:
    def __init__(self, redis: Redis, prefix: str = "rl") -> None:
        self.redis = redis
        self.prefix = prefix
        self._script = redis.register_script(_SLIDING_WINDOW)

    async def hit(self, key: str, limit: int, window_s: int) -> RateDecision:
        now_ms = int(time.time() * 1000)
        window_ms = window_s * 1000
        allowed, count, oldest = await self._script(
            keys=[f"{self.prefix}:{key}"], args=[now_ms, window_ms, limit, f"{now_ms}-{uuid.uuid4().hex[:8]}"]
        )
        if allowed:
            return RateDecision(True, max(0, limit - int(count)), 0)
        retry_ms = int(float(oldest)) + window_ms - now_ms
        return RateDecision(False, 0, max(1, (retry_ms + 999) // 1000))
