"""Deterministic signals (no LLM). Every value is computed from stored evidence, with its method and inputs."""

from __future__ import annotations

import re
import statistics
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

WTP_PATTERNS = re.compile(
    r"\b(i'?d|i would|we'?d|we would|happy to|willing to|gladly) pay\b"
    r"|\btake my money\b|\bshut up and take\b"
    r"|\bworth (paying|the money|every penny)\b"
    r"|\bpaid (plan|tier|version|tool|for)\b"
    r"|\b(we|i) (pay|spend|budget)\b[^.\n]{0,40}(\$|€|£|per month|a month|/mo|/month|/yr|per year)"
    r"|\bhow much (do|would) (you|people) (pay|charge)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DocView:
    id: str
    source: str
    community: str | None
    published_at: datetime | None
    engagement: dict[str, int]
    text: str

    @property
    def score(self) -> int:
        e = self.engagement
        return int(e.get("score") or e.get("likes") or 0) + int(e.get("comments") or 0)


@dataclass(frozen=True)
class ClaimView:
    id: str
    analyst: str
    stance: str
    document_ids: tuple[str, ...]


@dataclass
class SignalValue:
    name: str
    value: float
    method: str
    inputs: dict[str, Any] = field(default_factory=dict)


def _median_by_group(docs: Sequence[DocView]) -> dict[str, float]:
    groups: dict[str, list[int]] = {}
    for d in docs:
        groups.setdefault(d.community or d.source, []).append(d.score)
    return {k: max(1.0, float(statistics.median(v))) for k, v in groups.items()}


def compute_signals(
    docs: Sequence[DocView], claims: Sequence[ClaimView], *, now: datetime | None = None
) -> list[SignalValue]:
    now = now or datetime.now(UTC)
    by_source = Counter(d.source for d in docs)
    out = [
        SignalValue(
            "mention_volume",
            float(len(docs)),
            "count of distinct public posts collected for this idea's queries (after dedupe)",
            {"by_source": dict(by_source)},
        )
    ]

    last = sum(1 for d in docs if d.published_at and d.published_at >= now - timedelta(days=90))
    prev = sum(
        1 for d in docs if d.published_at and now - timedelta(days=180) <= d.published_at < now - timedelta(days=90)
    )
    dated = sum(1 for d in docs if d.published_at)
    out.append(
        SignalValue(
            "mention_slope_90d",
            round((last - prev) / max(prev, 1), 3),
            "(posts in last 90 days - posts in the 90 days before) / max(previous, 1)",
            {"last_90d": last, "previous_90d": prev, "dated_posts": dated},
        )
    )

    doc_by_id = {d.id: d for d in docs}
    medians = _median_by_group(docs)
    pain_docs = {
        doc_id
        for c in claims
        if c.analyst == "pain" and c.stance == "supports"
        for doc_id in c.document_ids
        if doc_id in doc_by_id
    }
    ratios = [doc_by_id[i].score / medians[doc_by_id[i].community or doc_by_id[i].source] for i in pain_docs]
    out.append(
        SignalValue(
            "engagement_weighted_pain",
            round(statistics.mean(ratios), 3) if ratios else 0.0,
            "mean of (engagement / median engagement in the same community) over posts cited by verified pain claims",
            {"posts": len(ratios)},
        )
    )

    wtp = [d.id for d in docs if WTP_PATTERNS.search(d.text)]
    out.append(
        SignalValue(
            "wtp_phrase_count",
            float(len(wtp)),
            "posts containing explicit willingness-to-pay phrases (e.g. 'I'd pay', 'take my money', budget amounts)",
            {"document_ids": wtp[:20]},
        )
    )
    out.append(
        SignalValue(
            "linkedin_job_count",
            float(by_source.get("linkedin_jobs", 0)),
            "LinkedIn job listings matching the problem's job titles/skills",
        )
    )
    competitor_claims = [c.id for c in claims if c.analyst == "competitors"]
    out.append(
        SignalValue(
            "competitor_mentions",
            float(len(competitor_claims) + by_source.get("producthunt", 0)),
            "verified competitor claims + Product Hunt products found for the category",
            {"claims": len(competitor_claims), "producthunt": by_source.get("producthunt", 0)},
        )
    )
    ph_recent = sum(
        1
        for d in docs
        if d.source == "producthunt" and (d.published_at is None or d.published_at >= now - timedelta(days=365))
    )
    out.append(
        SignalValue(
            "ph_launches_12m",
            float(ph_recent),
            "Product Hunt launches in the last 12 months (undated search results count as recent)",
        )
    )
    communities = Counter(d.community for d in docs if d.community)
    total = sum(communities.values())
    hhi = sum((n / total) ** 2 for n in communities.values()) if total else 0.0
    out.append(
        SignalValue(
            "community_concentration",
            round(hhi, 3),
            "Herfindahl index of posts across communities (1 = all in one place, near 0 = spread out)",
            {"top": communities.most_common(5)},
        )
    )
    diverse = [s for s, n in by_source.items() if n >= 3 and s != "trends"]
    out.append(
        SignalValue("source_diversity", float(len(diverse)), "sources with at least 3 posts", {"sources": diverse})
    )
    support = sum(1 for c in claims if c.stance == "supports")
    refute = sum(1 for c in claims if c.stance == "refutes")
    out.append(SignalValue("claims_supporting", float(support), "verified claims that make the idea more promising"))
    out.append(SignalValue("claims_refuting", float(refute), "verified claims that make the idea less promising"))
    return out
