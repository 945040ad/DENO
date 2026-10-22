"""Rule-based verdict band and confidence. The LLM only explains it."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from deno_graphs.validation.signals import ClaimView

MIN_DOCS = 12
MIN_DIVERSE_SOURCES = 2
# A shortfall with at least this many documents is a near miss: the evidence exists, we just didn't
# gather enough of it, so one broader pass is worth its latency.
NEAR_MISS_DOCS = 5
MAX_COLLECT_ROUNDS = 2  # the planned pass plus at most one broadened retry
# Collection errors that can clear up on a second attempt. A robots.txt/policy block cannot.
RETRYABLE_ERRORS = ("timeout", "slow source", "unavailable", "error")


@dataclass(frozen=True)
class Coverage:
    documents: int
    by_source: dict[str, int]
    diverse_sources: int
    recent_share: float
    ok: bool
    gaps: list[str]


def coverage(by_source: Mapping[str, int], recent: int, *, min_docs: int = MIN_DOCS) -> Coverage:
    total = sum(n for s, n in by_source.items() if s != "trends")
    diverse = sum(1 for s, n in by_source.items() if n >= 3 and s != "trends")
    gaps: list[str] = []
    if total < min_docs:
        gaps.append(f"only {total} relevant public posts found (need at least {min_docs})")
    if diverse < MIN_DIVERSE_SOURCES:
        gaps.append(f"evidence comes from {diverse} source(s) with 3+ posts (need {MIN_DIVERSE_SOURCES})")
    for source in ("reddit", "hn", "x"):
        if by_source.get(source, 0) == 0:
            gaps.append(f"no posts found on {source}")
    return Coverage(
        documents=total,
        by_source=dict(by_source),
        diverse_sources=diverse,
        recent_share=round(recent / total, 3) if total else 0.0,
        ok=total >= min_docs and diverse >= MIN_DIVERSE_SOURCES,
        gaps=gaps,
    )


CoverageAction = Literal["ok", "retry", "insufficient"]
# Why coverage fell short, so the founder is told whether it is about their idea or about us.
CoverageCause = Literal["ok", "sources_failed", "thin", "no_evidence"]


@dataclass(frozen=True)
class CoverageDecision:
    action: CoverageAction
    cause: CoverageCause
    retry_sources: tuple[str, ...] = ()


def decide_coverage(
    cov: Coverage, *, planned: Sequence[str], errors: Mapping[str, str | None], rounds: int
) -> CoverageDecision:
    """Retry when the shortfall looks like ours, answer at once when the evidence isn't there.

    - A source that failed transiently (timeout, upstream outage, blocked search engines) is
      retried: its silence says nothing about the idea.
    - A near miss (``NEAR_MISS_DOCS``+ documents) also broadens the thin sources: evidence exists.
    - Every source answering cleanly with almost nothing is a real signal and stays fast.
    - Never more than ``MAX_COLLECT_ROUNDS`` passes, so latency stays bounded.
    """
    if cov.ok:
        return CoverageDecision("ok", "ok")
    policy_blocked = {s for s, e in errors.items() if e and e.startswith("blocked_by_policy")}
    failed = [s for s in planned if (e := errors.get(s)) and e.startswith(RETRYABLE_ERRORS)]
    near_miss = cov.documents >= NEAR_MISS_DOCS
    cause: CoverageCause = "sources_failed" if failed else "thin" if near_miss else "no_evidence"
    if rounds >= MAX_COLLECT_ROUNDS:
        return CoverageDecision("insufficient", cause)
    thin = [s for s in planned if cov.by_source.get(s, 0) < 3 and s not in policy_blocked and s not in failed]
    retry = failed + (thin if near_miss else [])
    if not retry:
        return CoverageDecision("insufficient", cause)
    return CoverageDecision("retry", cause, tuple(retry))


@dataclass(frozen=True)
class VerdictBand:
    verdict: str  # build | pivot | kill | insufficient_evidence
    confidence: float
    reasons: list[str]


def decide(cov: Coverage, claims: Sequence[ClaimView], signals: Mapping[str, float]) -> VerdictBand:
    def count(analyst: str | None, stance: str) -> int:
        return sum(1 for c in claims if (analyst is None or c.analyst == analyst) and c.stance == stance)

    pain, demand, wtp = count("pain", "supports"), count("demand", "supports"), count("wtp", "supports")
    support, refute = count(None, "supports"), count(None, "refutes")
    wtp_phrases = int(signals.get("wtp_phrase_count", 0))
    reasons: list[str] = []

    if not cov.ok:
        return VerdictBand("insufficient_evidence", 0.0, list(cov.gaps))
    if support + refute < 3:
        why = (
            f"none of the {cov.documents} posts found discuss this idea directly"
            if support + refute == 0
            else f"only {support + refute} claims survived citation checks (need at least 3 to judge)"
        )
        return VerdictBand("insufficient_evidence", 0.0, [why])

    if pain >= 2 and (demand + wtp >= 1 or wtp_phrases >= 2) and refute <= support / 2:
        verdict = "build"
        reasons.append(f"{pain} verified pain claims and {demand + wtp} demand/payment claims")
    elif pain + demand == 0 or refute > support:
        verdict = "kill"
        reasons.append(
            "no verified pain or demand" if pain + demand == 0 else f"{refute} refuting vs {support} supporting claims"
        )
    else:
        verdict = "pivot"
        if pain >= 2:
            reasons.append(f"{pain} verified pain claims, but demand or payment evidence is thin or contested")
        elif pain == 0:
            reasons.append(f"people show interest ({demand + wtp} demand/payment claims) but no verified pain claims")
        else:
            reasons.append("only one verified pain claim; the problem may not hurt enough")
    if wtp_phrases:
        reasons.append(f"{wtp_phrases} posts mention paying")
    comp = int(signals.get("competitor_mentions", 0))
    if comp >= 5:
        reasons.append(f"crowded: {comp} competitor mentions")

    coverage_f = min(1.0, cov.documents / 40)
    diversity_f = min(1.0, cov.diverse_sources / 3)
    agreement_f = abs(support - refute) / (support + refute)
    confidence = round(max(0.0, min(1.0, coverage_f * diversity_f * (0.5 + 0.5 * agreement_f))), 2)
    return VerdictBand(verdict, confidence, reasons)
