"""Token and cost accounting per run, with a hard budget stop.

``UsageTracker`` is a LangChain callback: attach it to every model call of a run (the
router does, via ``callbacks``). It logs prompt id/version per call, sums tokens per
model, and refuses to *start* another call once the run's token budget is spent.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.messages import BaseMessage
from langchain_core.outputs import LLMResult

from deno_core.logging import get_logger
from deno_core.observability import LLM_COST, LLM_TOKENS

log = get_logger(__name__)


class BudgetExceeded(RuntimeError):
    """The run spent its LLM token budget; the graph stops and reports partial results."""


@dataclass
class ModelUsage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass(eq=False)  # handlers must be hashable (LangChain merges them in sets)
class UsageTracker(AsyncCallbackHandler):
    token_budget: int
    usd_per_mtok_input: float = 0.0
    usd_per_mtok_output: float = 0.0
    by_model: dict[str, ModelUsage] = field(default_factory=dict)
    _started: dict[UUID, tuple[float, dict[str, Any]]] = field(default_factory=dict)
    raise_error: bool = True  # budget violations must propagate, not be swallowed by LangChain

    def __post_init__(self) -> None:
        super().__init__()

    @property
    def total_tokens(self) -> int:
        return sum(u.input_tokens + u.output_tokens for u in self.by_model.values())

    @property
    def cost_usd(self) -> float:
        tin = sum(u.input_tokens for u in self.by_model.values())
        tout = sum(u.output_tokens for u in self.by_model.values())
        return round(tin * self.usd_per_mtok_input / 1e6 + tout * self.usd_per_mtok_output / 1e6, 6)

    async def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[BaseMessage]],
        *,
        run_id: UUID,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        if self.total_tokens >= self.token_budget:
            raise BudgetExceeded(f"LLM token budget of {self.token_budget} spent")
        self._started[run_id] = (time.monotonic(), dict(metadata or {}))

    async def on_llm_end(self, response: LLMResult, *, run_id: UUID, **kwargs: Any) -> None:
        started, meta = self._started.pop(run_id, (time.monotonic(), {}))
        model, tin, tout = _extract(response)
        usage = self.by_model.setdefault(model, ModelUsage())
        usage.calls += 1
        usage.input_tokens += tin
        usage.output_tokens += tout
        LLM_TOKENS.labels(model, "input").inc(tin)
        LLM_TOKENS.labels(model, "output").inc(tout)
        LLM_COST.inc(tin * self.usd_per_mtok_input / 1e6 + tout * self.usd_per_mtok_output / 1e6)
        log.info(
            "llm_call",
            model=model,
            prompt_id=meta.get("prompt_id"),
            prompt_version=meta.get("prompt_version"),
            input_tokens=tin,
            output_tokens=tout,
            ms=round((time.monotonic() - started) * 1000),
        )

    async def on_llm_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        _, meta = self._started.pop(run_id, (0.0, {}))
        log.warning("llm_call_failed", prompt_id=meta.get("prompt_id"), error=type(error).__name__)

    def summary(self) -> dict[str, Any]:
        return {
            "total_tokens": self.total_tokens,
            "cost_usd": self.cost_usd,
            "by_model": {k: vars(v) for k, v in self.by_model.items()},
        }


def _extract(response: LLMResult) -> tuple[str, int, int]:
    output = response.llm_output or {}
    model = str(output.get("model_name") or output.get("model") or "unknown")
    tin = tout = 0
    for gens in response.generations:
        for gen in gens:
            meta = getattr(getattr(gen, "message", None), "usage_metadata", None)
            if meta:
                tin += int(meta.get("input_tokens", 0))
                tout += int(meta.get("output_tokens", 0))
    if not (tin or tout) and (tu := output.get("token_usage")):
        tin, tout = int(tu.get("prompt_tokens", 0)), int(tu.get("completion_tokens", 0))
    return model, tin, tout
