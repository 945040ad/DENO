"""Exact-match cache for deterministic-ish calls (planner, classifiers).

Key = model + prompt id/version + schema + rendered inputs, so a prompt bump invalidates it.
Stored in Valkey when available (shared across workers), else in-process.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel
from redis.asyncio import Redis
from redis.exceptions import RedisError

from deno_core.logging import get_logger

log = get_logger(__name__)


class StructuredCache:
    def __init__(self, redis: Redis | None = None, *, ttl_s: int = 7 * 24 * 3600, prefix: str = "llm:cache:") -> None:
        self._redis, self._ttl, self._prefix = redis, ttl_s, prefix
        self._local: dict[str, str] = {}

    @staticmethod
    def key(*, model: str, prompt_id: str, prompt_version: int, schema: type[BaseModel], inputs: dict[str, Any]) -> str:
        blob = json.dumps(
            {"m": model, "p": prompt_id, "v": prompt_version, "s": schema.__name__, "i": inputs},
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(blob.encode()).hexdigest()

    async def _get(self, key: str) -> str | None:
        if self._redis is not None:
            try:
                raw = await self._redis.get(self._prefix + key)
                return raw.decode() if isinstance(raw, bytes) else raw
            except RedisError:
                log.warning("llm_cache_unavailable")
        return self._local.get(key)

    async def _set(self, key: str, value: str) -> None:
        if self._redis is not None:
            try:
                await self._redis.set(self._prefix + key, value, ex=self._ttl)
                return
            except RedisError:
                log.warning("llm_cache_unavailable")
        if len(self._local) > 5000:
            self._local.pop(next(iter(self._local)))
        self._local[key] = value

    async def get_or_call[T: BaseModel](self, key: str, schema: type[T], call: Callable[[], Awaitable[T]]) -> T:
        if (hit := await self._get(key)) is not None:
            try:
                return schema.model_validate_json(hit)
            except ValueError:
                log.warning("llm_cache_corrupt_entry")
        value = await call()
        await self._set(key, value.model_dump_json())
        return value
