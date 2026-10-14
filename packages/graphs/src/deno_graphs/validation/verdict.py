"""Rule-based verdict band and confidence. The LLM only explains it."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from deno_graphs.validation.signals import ClaimView

MIN_DOCS = 12
MIN_DIVERSE_SOURCES = 2


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
