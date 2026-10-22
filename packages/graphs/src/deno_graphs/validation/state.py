"""Graph state. Large data (documents, chunks, claims) lives in Postgres; state keeps ids and summaries."""

from __future__ import annotations

import operator
from typing import Annotated, Any, NotRequired, TypedDict


class CollectResult(TypedDict):
    source: str
    queries: list[str]
    posts: list[dict[str, Any]]  # serialised deno_sources.Post
    error: str | None
    seconds: float
    # Queries that never got an answer (timed out, upstream down) - retried first on a second pass.
    # NotRequired: runs checkpointed before this field existed must still resume.
    failed_queries: NotRequired[list[str]]


class AnalystResult(TypedDict):
    analyst: str
    claim_ids: list[str]  # persisted claims (DB ids)


class ValidationState(TypedDict, total=False):
    idea: str
    brief: dict[str, Any]
    rejected: str | None
    perspectives: list[dict[str, Any]]
    plan: dict[str, Any]
    collected: Annotated[list[CollectResult], operator.add]  # a retry pass appends to the first
    collect_round: int  # 1 for the planned pass, 2 after one broadened retry
    retry: dict[str, Any]  # per source: the broadened queries/subreddits for the retry pass
    ingest: dict[str, Any]
    coverage: dict[str, Any]
    analysts: Annotated[list[AnalystResult], operator.add]
    validation: dict[str, Any]
    signals: dict[str, Any]
    critic_round: int
    critique: list[dict[str, Any]]
    verdict: dict[str, Any]
    review: dict[str, Any]
