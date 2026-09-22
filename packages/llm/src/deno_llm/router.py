"""Model router (ADR-008): roles → configured chat models, with timeouts, fallbacks and the shared NIM limiter.

Switching provider is configuration only: ``LLM_PROVIDER`` + ``LLM_MODEL_*`` + base URL/key.
Structured output always goes through ``with_structured_output(PydanticModel)`` — never regex JSON.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from enum import StrEnum
from typing import Any, cast

from langchain.chat_models import init_chat_model
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models import BaseChatModel, LanguageModelInput
from langchain_core.rate_limiters import BaseRateLimiter
from langchain_core.runnables import Runnable
from pydantic import BaseModel

from deno_core.settings import Settings
from deno_llm.limiter import Limiter, NullLimiter


class Role(StrEnum):
    FAST = "fast"  # planner, classifiers, extraction
    STRONG = "strong"  # analysts, synthesis
    JUDGE = "judge"  # skeptic, citation/entailment checks


ROLE_TIMEOUT_FACTOR = {Role.FAST: 0.5, Role.STRONG: 1.5, Role.JUDGE: 1.0}
ROLE_MAX_TOKENS = {Role.FAST: 1500, Role.STRONG: 3000, Role.JUDGE: 1200}


class SharedRateLimiter(BaseRateLimiter):
    """Adapts our cross-process ``Limiter`` to LangChain's ``rate_limiter=`` hook (called before every request)."""

    def __init__(self, limiter: Limiter) -> None:
        self._limiter = limiter

    def acquire(self, *, blocking: bool = True) -> bool:
        # All model calls are async; a sync call from a worker thread still gets throttled.
        asyncio.run(self._limiter.acquire())
        return True

    async def aacquire(self, *, blocking: bool = True) -> bool:
        await self._limiter.acquire()
        return True


class LLMRouter:
    def __init__(
        self,
        settings: Settings,
        *,
        limiter: Limiter | None = None,
        callbacks: Sequence[BaseCallbackHandler] = (),
    ) -> None:
        self.settings = settings
        self._rate = SharedRateLimiter(limiter or NullLimiter())
        self.callbacks = list(callbacks)
        self._cache: dict[tuple[str, Role, float | None], BaseChatModel] = {}

    def model_name(self, role: Role) -> str:
        return cast(str, getattr(self.settings, f"llm_model_{role.value}"))

    def _build(self, model: str, role: Role, temperature: float | None) -> BaseChatModel:
        key = (model, role, temperature)
        if key not in self._cache:
            s = self.settings
            kwargs: dict[str, Any] = {
                "model_provider": s.llm_provider,
                "base_url": s.nvidia_nim_base_url,
                "api_key": s.nvidia_nim_api_key.get_secret_value() or "unset",
                "timeout": s.llm_timeout_seconds * ROLE_TIMEOUT_FACTOR[role],
                "max_retries": 1,
                "rate_limiter": self._rate,
            }
            # NIM honours `max_tokens`; with `max_completion_tokens` (what LangChain sends) its guided JSON
            # decoding runs to the limit and fails (verified 2026-09-24). So the limit goes in extra_body.
            extra: dict[str, Any] = {"max_tokens": ROLE_MAX_TOKENS[role]}
            if temperature is not None:
                kwargs["temperature"] = temperature
            if "nemotron" in model and s.llm_provider == "openai":
                thinking = role.value in s.llm_thinking_roles
                extra["chat_template_kwargs"] = {"enable_thinking": thinking}
                if thinking:
                    extra["max_tokens"] = ROLE_MAX_TOKENS[role] + 4000
            if s.llm_provider == "openai":
                kwargs["extra_body"] = extra
            else:
                kwargs["max_tokens"] = ROLE_MAX_TOKENS[role]
            self._cache[key] = cast(BaseChatModel, init_chat_model(model, **kwargs))
        return self._cache[key]

    def chat(self, role: Role, *, temperature: float | None = 0.2) -> Runnable[LanguageModelInput, Any]:
        primary = self._build(self.model_name(role), role, temperature)
        fallback = self._build(self.settings.llm_model_fallback, role, temperature)
        return primary.with_fallbacks([fallback]).with_config(callbacks=self.callbacks, tags=[f"role:{role}"])

    def structured[T: BaseModel](
        self, role: Role, schema: type[T], *, temperature: float | None = 0.2
    ) -> Runnable[LanguageModelInput, T]:
        """Validated Pydantic output. Primary uses the configured method; the fallback model uses json_mode."""
        method = self.settings.llm_structured_method
        # strict=True: without it NIM's grammar allows unbounded whitespace and long outputs run to the
        # token limit (LengthFinishReasonError) — seen live on batched citation judging.
        primary = self._build(self.model_name(role), role, temperature).with_structured_output(
            schema, method=method, **({"strict": True} if method == "json_schema" else {})
        )
        fallback = self._build(self.settings.llm_model_fallback, role, temperature).with_structured_output(
            schema, method="json_mode"
        )
        runnable = primary.with_fallbacks([fallback]).with_config(callbacks=self.callbacks, tags=[f"role:{role}"])
        return cast(Runnable[LanguageModelInput, T], runnable)
