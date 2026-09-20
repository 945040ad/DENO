"""Run event bus on Valkey Streams.

The worker appends node/source/status events to ``run:{id}:events``; the API
relays them to the browser as SSE. Stream entry ids double as SSE event ids,
so a reconnecting client resumes exactly where it left off (``Last-Event-ID``).
Streams are capped and expire a day after the last write.

Cancellation is a separate flag (``run:{id}:cancel``) that graph code checks
between nodes (cooperative cancellation).
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal

from redis.asyncio import Redis

EventType = Literal["status", "node_started", "node_finished", "source", "progress", "log", "interrupt", "error"]
TERMINAL_STATUSES = frozenset({"succeeded", "failed", "cancelled", "awaiting_review"})
STREAM_MAXLEN = 2000
STREAM_TTL_SECONDS = 24 * 3600


def stream_key(run_id: str) -> str:
    return f"run:{run_id}:events"


def cancel_key(run_id: str) -> str:
    return f"run:{run_id}:cancel"


@dataclass(frozen=True)
class RunEvent:
    type: EventType
    data: dict[str, Any] = field(default_factory=dict)
    id: str | None = None  # stream entry id, set when read back
    ts: float = field(default_factory=time.time)

    @property
    def is_terminal(self) -> bool:
        return self.type == "status" and self.data.get("status") in TERMINAL_STATUSES

    def to_fields(self) -> dict[str, str]:
        return {"type": self.type, "data": json.dumps(self.data, default=str), "ts": f"{self.ts:.3f}"}

    @classmethod
    def from_fields(cls, entry_id: str, fields: dict[str, str]) -> RunEvent:
        return cls(
            type=fields["type"],  # type: ignore[arg-type]
            data=json.loads(fields.get("data") or "{}"),
            id=entry_id,
            ts=float(fields.get("ts") or 0),
        )


class RunEvents:
    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    async def publish(self, run_id: str, event: RunEvent) -> str:
        key = stream_key(run_id)
        entry_id = await self.redis.xadd(key, event.to_fields(), maxlen=STREAM_MAXLEN, approximate=True)  # type: ignore[arg-type]
        await self.redis.expire(key, STREAM_TTL_SECONDS)
        return entry_id.decode() if isinstance(entry_id, bytes) else str(entry_id)

    async def read(self, run_id: str, after: str = "0-0", block_ms: int = 15_000, count: int = 100) -> list[RunEvent]:
        """Events after `after`; blocks up to `block_ms` when there are none yet (empty list on timeout)."""
        result: list[tuple[Any, list[tuple[Any, dict[Any, Any]]]]] = await self.redis.xread(
            {stream_key(run_id): after}, block=block_ms, count=count
        )  # type: ignore[assignment]
        events: list[RunEvent] = []
        for _key, entries in result or []:
            for entry_id, fields in entries:
                decoded = {_s(k): _s(v) for k, v in fields.items()}
                events.append(RunEvent.from_fields(_s(entry_id), decoded))
        return events

    async def follow(self, run_id: str, after: str = "0-0", block_ms: int = 15_000) -> AsyncIterator[RunEvent | None]:
        """Yields events as they arrive, `None` on each idle `block_ms` (heartbeat), and stops after a terminal event."""
        cursor = after
        while True:
            events = await self.read(run_id, cursor, block_ms)
            if not events:
                yield None
                continue
            for event in events:
                cursor = event.id or cursor
                yield event
                if event.is_terminal:
                    return

    async def request_cancel(self, run_id: str) -> None:
        await self.redis.set(cancel_key(run_id), "1", ex=STREAM_TTL_SECONDS)

    async def is_cancelled(self, run_id: str) -> bool:
        return bool(await self.redis.exists(cancel_key(run_id)))


def _s(value: bytes | str) -> str:
    return value.decode() if isinstance(value, bytes) else value
