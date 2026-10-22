"""Post-generation quality verification (docs/08 Phase 14 safeguard).

Scores a finished draft on ten dimensions, each 0–10:
    D1  Hook strength          – does the opening stop a scroll?
    D2  Specificity            – concrete names, numbers, events vs. vagueness
    D3  Voice authenticity     – how close to the founder's measured style?
    D4  Platform fit           – length, tone, formatting for the target platform
    D5  Engagement potential   – asks a question, invites a reply, has a take
    D6  Story grounding        – uses real Story-Bank details, not invented ones
    D7  Slop cleanliness       – inverse of how many anti-slop hits remain
    D8  Readability            – sentence-length variety, no jargon walls
    D9  Originality            – the Portability Test (non-generic content)
    D10 Community compliance   – follows the community's specific rules

The final score is a weighted average (hook and specificity matter most).  A
``QualityVerdict`` bundles the numeric score with a structured flaw list that
the rewrite prompt can consume directly.

All deterministic checks reuse ``deno_gates`` layers — no LLM calls here.
The LLM quality scorer (``content.quality_scorer`` prompt) adds the subjective
dimensions (hook, engagement, originality) in the content graph.
"""

from __future__ import annotations

import math
import re
import statistics
from dataclasses import dataclass

from deno_gates.compliance import _LINK
from deno_gates.gate import GateContext
from deno_gates.layers import (
    _EXPERIENCE,
    _NUMBER,
    sentences,
    words,
)
from deno_gates.pipeline import GateReport
from deno_gates.voice import VoiceProfile

# ---------------------------------------------------------------------------
# Dimension weights — the weighted average respects what matters most for
# distribution posts.  Hook & specificity are king.
# ---------------------------------------------------------------------------

DIMENSION_WEIGHTS: dict[str, float] = {
    "hook_strength": 1.5,
    "specificity": 1.5,
    "voice_authenticity": 1.2,
    "platform_fit": 1.0,
    "engagement_potential": 1.0,
    "story_grounding": 1.0,
    "slop_cleanliness": 1.3,
    "readability": 0.8,
    "originality": 1.2,
    "community_compliance": 1.0,
}

DEFAULT_THRESHOLD = 7  # 1–10
MAX_REGEN_ATTEMPTS = 3


@dataclass(frozen=True)
class DimensionScore:
    """One axis of the quality rubric."""

    name: str
    score: float  # 0-10
    weight: float
    flaws: tuple[str, ...]  # human-readable fixes for this dimension


@dataclass(frozen=True)
class QualityVerdict:
    """Complete quality evaluation of a draft."""

    dimensions: tuple[DimensionScore, ...]
    overall_score: float  # 1-10 weighted average
    passed: bool
    threshold: int
    flaw_summary: str  # ready-made text block for the rewrite prompt
    explanation: str = ""  # plain-English 1–3 sentence explanation

    def to_dict(self) -> dict[str, object]:
        return {
            "overall_score": round(self.overall_score, 1),
            "passed": self.passed,
            "threshold": self.threshold,
            "dimensions": [
                {"name": d.name, "score": round(d.score, 1), "weight": d.weight, "flaws": list(d.flaws)}
                for d in self.dimensions
            ],
            "flaw_summary": self.flaw_summary,
            "explanation": self.explanation,
        }

    def to_gate_layer(self) -> dict[str, object]:
        """Shape this verdict as a ``gate_layers`` entry for ``UserScope.add_draft``.

        ``findings`` stays the human-readable per-dimension list every other layer uses;
        ``meta`` carries the real per-dimension weight and the explanation, so callers (the
        content graph, the manual-edit re-gate) don't have to reverse-parse either out of a
        message string.

        Every finding is ``severity="info"``, never ``"block"``/``"warn"``: a low quality score
        does not block a draft (``status`` still comes from L1–L5 alone) and quality is not ban
        risk, so these must not count toward the gate findings list or the 0–100 gate score.
        A client shows quality from ``score``/``meta``, which are about quality specifically.
        """
        return {
            "layer": "quality_verification",
            "passed": self.passed,
            "score": self.overall_score,
            "findings": [
                {
                    "rule_id": f"quality.{d.name}",
                    "message": f"{d.name}: {d.score:.1f}/10"
                    + ("" if d.score >= self.threshold else f" (below the {self.threshold}/10 bar)"),
                    "quote": "",
                    "fix": "; ".join(d.flaws) if d.flaws else "OK",
                    "severity": "info",
                }
                for d in self.dimensions
            ],
            "meta": {
                "threshold": self.threshold,
                "explanation": self.explanation,
                "dimensions": [{"name": d.name, "score": d.score, "weight": d.weight} for d in self.dimensions],
            },
        }


# ---------------------------------------------------------------------------
# Deterministic dimension scorers (D2–D4, D6–D10)
# ---------------------------------------------------------------------------


def _score_specificity(text: str, ctx: GateContext | None = None) -> DimensionScore:
    """D2: concrete vs vague — counts hard anchors (numbers, proper nouns, URLs)."""
    ws = words(text)
    n = max(1, len(ws))
    numbers = len(_NUMBER.findall(text))
    # Proper nouns: uppercase words mid-sentence (rough heuristic, skip line starts)

    proper = len(re.findall(r"(?<![.!?]\s)(?<!^)\b[A-Z][a-z]{2,}", text, re.MULTILINE))
    links = len(_LINK.findall(text))
    anchors = numbers + proper + links
    ratio = anchors / n
    flaws: list[str] = []
    if numbers == 0:
        flaws.append("No concrete numbers — add a specific metric, time frame or dollar amount you can stand behind.")
    if proper == 0:
        flaws.append("No named entities — mention a tool, person, company or community by name.")
    # 0–10 scale: ≥4 anchors per 100 words is a 10, 0 anchors is a 2.
    raw = min(10.0, 2.0 + (ratio * 100) * 2.0)
    return DimensionScore("specificity", raw, DIMENSION_WEIGHTS["specificity"], tuple(flaws))


def _score_voice(text: str, profile: VoiceProfile | None) -> DimensionScore:
    """D3: voice authenticity from Burrows' Delta (already computed by the gate)."""
    if profile is None:
        return DimensionScore("voice_authenticity", 7.0, DIMENSION_WEIGHTS["voice_authenticity"], ())
    delta = profile.delta(text)
    if math.isnan(delta):
        return DimensionScore(
            "voice_authenticity",
            5.0,
            DIMENSION_WEIGHTS["voice_authenticity"],
            ("Voice check failed (too short or unstable).",),
        )
    # 10 when delta==0 (perfect match); 0 when delta ≥ 2× threshold
    ratio = delta / max(profile.threshold, 0.01)
    raw = max(0.0, min(10.0, 10.0 - (ratio - 0.5) * 10.0))
    flaws: list[str] = []
    if raw < 7:
        flaws.append(
            f"Voice drift: Delta {delta:.2f} vs your threshold {profile.threshold:.2f}. Use your usual sentence length and opener style."
        )
    return DimensionScore("voice_authenticity", raw, DIMENSION_WEIGHTS["voice_authenticity"], tuple(flaws))


def _score_platform_fit(text: str, ctx: GateContext | None = None) -> DimensionScore:
    """D4: length, format and structure for the target platform."""
    platform = ctx.platform if ctx else "linkedin"
    char_count = len(text)
    ws = words(text)
    flaws: list[str] = []
    score = 10.0

    if platform == "linkedin":
        # Optimal: 900–1,300 chars for "see more" dwell time.
        if char_count < 400:
            score -= 3.0
            flaws.append(f"Too short for LinkedIn ({char_count} chars). Aim for 900–1300 characters.")
        elif char_count < 900:
            score -= 1.5
            flaws.append(f"On the short side for LinkedIn ({char_count} chars). 900–1300 chars is the sweet spot.")
        elif char_count > 2000:
            score -= 2.0
            flaws.append(f"Too long for LinkedIn ({char_count} chars). Cut to under 1300 characters.")
        # Links in the body hurt reach.
        if _LINK.search(text):
            score -= 1.0
            flaws.append("Link in LinkedIn post body — move it to the first comment.")
    elif platform == "reddit":
        # Reddit is more flexible but overly short = low effort.
        if len(ws) < 50:
            score -= 2.0
            flaws.append("Very short for a Reddit post. Add more substance or context.")
        # Markdown is fine on Reddit.
    elif platform == "x":
        if char_count > 280 and not any(text.count(sep) >= 2 for sep in ("\n\n", "\n")):
            score -= 1.0
            flaws.append("Long X post without thread breaks. Split into a thread or keep under 280 chars.")

    return DimensionScore("platform_fit", max(0.0, score), DIMENSION_WEIGHTS["platform_fit"], tuple(flaws))


def _score_story_grounding(text: str, ctx: GateContext | None = None) -> DimensionScore:
    """D6: does the post use real Story Bank material? Penalise invented narratives."""
    if ctx is None or ctx.story_attached is None:
        return DimensionScore("story_grounding", 7.0, DIMENSION_WEIGHTS["story_grounding"], ())
    flaws: list[str] = []
    score = 10.0
    # If there's a story, we expect the post to reference it.
    if ctx.story_attached:
        # Good — story is available. But check if it uses specific anchors.
        experience_matches = list(_EXPERIENCE.finditer(text))
        if not experience_matches:
            score -= 2.0
            flaws.append("You have a Story Bank entry but the post doesn't use it. Weave in a real detail.")
    else:
        # No story — any first-person narrative is fabricated.
        experience_matches = list(_EXPERIENCE.finditer(text))
        if experience_matches:
            score -= 4.0
            flaws.append(
                "Invented first-person story with no Story Bank entry. Remove the narrative or add it to your Story Bank first."
            )
    return DimensionScore("story_grounding", max(0.0, score), DIMENSION_WEIGHTS["story_grounding"], tuple(flaws))


def _score_slop_cleanliness(gate_report: GateReport) -> DimensionScore:
    """D7: inverse of remaining gate findings. A clean report = 10."""
    total_findings = sum(len(r.findings) for r in gate_report.results)
    blockers = sum(len(r.blocking) for r in gate_report.results)
    flaws: list[str] = []
    # 0 findings = 10; each blocker costs 2 points; each warning costs 0.5.
    warnings = total_findings - blockers
    score = max(0.0, 10.0 - blockers * 2.0 - warnings * 0.5)
    if blockers > 0:
        # Collect the first few specific findings as actionable fixes.
        for result in gate_report.results:
            for f in result.blocking[:3]:
                flaws.append(f'{f.rule_id}: "{f.quote[:80]}" → {f.fix}')
    if warnings > 2:
        flaws.append(f"{warnings} warnings from anti-slop gates — tighten the writing.")
    return DimensionScore("slop_cleanliness", score, DIMENSION_WEIGHTS["slop_cleanliness"], tuple(flaws))


def _score_readability(text: str) -> DimensionScore:
    """D8: sentence variety, no jargon walls, natural rhythm."""
    sents = sentences(text)
    if len(sents) < 3:
        return DimensionScore(
            "readability", 5.0, DIMENSION_WEIGHTS["readability"], ("Post has fewer than 3 sentences.",)
        )
    lengths = [len(words(s)) for s in sents]
    mean_len = statistics.mean(lengths)
    flaws: list[str] = []
    score = 10.0

    # Penalise if all sentences are the same length (monotone).
    if len(lengths) >= 4:
        cv = statistics.pstdev(lengths) / max(1.0, mean_len)
        if cv < 0.2:
            score -= 3.0
            flaws.append(
                "Monotone rhythm: every sentence is about the same length. Mix short punchy ones with longer ones."
            )
        elif cv < 0.3:
            score -= 1.0
            flaws.append("Sentence length could be more varied — mix it up.")

    # Penalise very long average sentences (jargon-wall).
    if mean_len > 28:
        score -= 2.0
        flaws.append(f"Average sentence is {mean_len:.0f} words — break some up for readability.")

    # Penalise extremely short average (fragments).
    if mean_len < 6 and len(sents) > 5:
        score -= 2.0
        flaws.append("Mostly fragments — join some into proper sentences.")

    return DimensionScore("readability", max(0.0, score), DIMENSION_WEIGHTS["readability"], tuple(flaws))


def _score_compliance(gate_report: GateReport, ctx: GateContext | None = None) -> DimensionScore:
    """D10: community rule compliance from the compliance gate result."""
    compliance_result = next((r for r in gate_report.results if r.layer == "compliance"), None)
    if compliance_result is None:
        return DimensionScore("community_compliance", 8.0, DIMENSION_WEIGHTS["community_compliance"], ())
    flaws: list[str] = []
    score = 10.0
    for f in compliance_result.findings:
        if f.severity == "block":
            score -= 3.0
            flaws.append(f"{f.rule_id}: {f.message} → {f.fix}")
        else:
            score -= 1.0
            flaws.append(f"{f.rule_id}: {f.message} (warning)")
    return DimensionScore(
        "community_compliance", max(0.0, score), DIMENSION_WEIGHTS["community_compliance"], tuple(flaws)
    )


def _score_originality(text: str) -> DimensionScore:
    """D9: the Portability Test — how many sentences are generic enough to fit any startup?"""
    sents = sentences(text)
    if len(sents) < 3:
        return DimensionScore("originality", 5.0, DIMENSION_WEIGHTS["originality"], ("Too few sentences to evaluate.",))

    generic_count = 0
    for s in sents:
        ws_s = words(s)
        has_number = bool(_NUMBER.search(s))
        has_proper = bool(re.search(r"(?<![.!?]\s)(?<!^)\b[A-Z][a-z]{2,}", s, re.MULTILINE))
        has_experience = bool(_EXPERIENCE.search(s))
        # A sentence is "portable" (generic) if it has no anchoring details.
        if not has_number and not has_proper and not has_experience and len(ws_s) > 5:
            generic_count += 1

    ratio = generic_count / len(sents)
    # 0% generic = 10, 100% generic = 1
    raw = max(1.0, 10.0 - ratio * 9.0)
    flaws: list[str] = []
    if ratio > 0.5:
        flaws.append(
            f"{generic_count}/{len(sents)} sentences are generic enough to fit any startup. Add names, numbers, or a real experience."
        )
    elif ratio > 0.3:
        flaws.append("Some sentences are too generic. Anchor them with specific details.")
    return DimensionScore("originality", raw, DIMENSION_WEIGHTS["originality"], tuple(flaws))


# ---------------------------------------------------------------------------
# Adaptive threshold (#4)
# ---------------------------------------------------------------------------

# Guardrails: the adaptive threshold never goes below MIN or above MAX.
_ADAPTIVE_MIN = 5
_ADAPTIVE_MAX = 9
_ADAPTIVE_HISTORY_SIZE = 20  # how many recent scores to consider


def compute_adaptive_threshold(
    historical_scores: list[float],
    *,
    user_threshold: int | None = None,
) -> int:
    """Compute a threshold that tracks the user's quality trajectory.

    - If the user has set an explicit threshold, honour it (clamped to 5–9).
    - Otherwise, start at DEFAULT_THRESHOLD and nudge up/down based on their
      recent average:  threshold = floor(avg - 0.5), clamped to [5, 9].
      This means users who consistently produce 8+ drafts get a higher bar,
      while new users with sparse Story Banks start lenient.
    """
    if user_threshold is not None:
        return max(_ADAPTIVE_MIN, min(_ADAPTIVE_MAX, user_threshold))
    if len(historical_scores) < 3:
        return DEFAULT_THRESHOLD
    recent = historical_scores[-_ADAPTIVE_HISTORY_SIZE:]
    avg = statistics.mean(recent)
    # Set threshold slightly below their average so ~60-70% of drafts pass
    adaptive = int(avg - 0.5)
    return max(_ADAPTIVE_MIN, min(_ADAPTIVE_MAX, adaptive))


# ---------------------------------------------------------------------------
# Merge custom weights
# ---------------------------------------------------------------------------


def _merge_weights(custom: dict[str, float] | None) -> dict[str, float]:
    """Merge user-provided dimension weights with defaults. Unknown keys are ignored."""
    if not custom:
        return DIMENSION_WEIGHTS
    merged = dict(DIMENSION_WEIGHTS)
    for key, value in custom.items():
        if key in merged and isinstance(value, (int, float)) and 0.0 <= value <= 3.0:
            merged[key] = float(value)
    # All-zero weights would make every draft score the floor and burn every regeneration.
    return merged if any(merged.values()) else DIMENSION_WEIGHTS


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def score_quality(
    text: str,
    gate_report: GateReport,
    ctx: GateContext | None = None,
    *,
    profile: VoiceProfile | None = None,
    llm_scores: dict[str, float] | None = None,
    threshold: int = DEFAULT_THRESHOLD,
    custom_weights: dict[str, float] | None = None,
) -> QualityVerdict:
    """Score a draft on all 10 dimensions and return a structured verdict.

    ``llm_scores`` is an optional dict with keys ``hook_strength``, ``engagement_potential``
    and ``originality_llm`` (each 0-10) provided by the LLM quality scorer prompt.  When
    present they replace or blend with the deterministic scores for those dimensions.

    ``custom_weights`` overrides the default dimension weights (from the user's profile).
    """
    llm_scores = llm_scores or {}
    weights = _merge_weights(custom_weights)

    # Deterministic dimensions --------------------------------------------------
    dims: list[DimensionScore] = [
        _score_specificity(text, ctx),
        _score_voice(text, profile),
        _score_platform_fit(text, ctx),
        _score_story_grounding(text, ctx),
        _score_slop_cleanliness(gate_report),
        _score_readability(text),
        _score_originality(text),
        _score_compliance(gate_report, ctx),
    ]

    # Apply custom weights to deterministic dimensions --------------------------
    dims = [DimensionScore(d.name, d.score, weights.get(d.name, d.weight), d.flaws) for d in dims]

    # LLM-scored subjective dimensions (from the quality_scorer prompt) ---------
    hook_score = llm_scores.get("hook_strength", 6.0)
    hook_flaws: list[str] = []
    if hook_score < 7:
        hook_flaws.append(
            "Opening doesn't grab attention. Lead with a number, a question, a surprise, or a real moment."
        )
    dims.insert(0, DimensionScore("hook_strength", hook_score, weights.get("hook_strength", 1.5), tuple(hook_flaws)))

    engagement_score = llm_scores.get("engagement_potential", 6.0)
    engagement_flaws: list[str] = []
    if engagement_score < 7:
        engagement_flaws.append(
            "Post doesn't invite a response. End with a genuine question or an opinion worth debating."
        )
    dims.insert(
        4,
        DimensionScore(
            "engagement_potential", engagement_score, weights.get("engagement_potential", 1.0), tuple(engagement_flaws)
        ),
    )

    # Blend LLM originality with deterministic originality ----------------------
    if "originality_llm" in llm_scores:
        det_orig = next(d for d in dims if d.name == "originality")
        blended = (det_orig.score + llm_scores["originality_llm"]) / 2
        dims = [d if d.name != "originality" else DimensionScore(d.name, blended, d.weight, d.flaws) for d in dims]

    # Weighted average ----------------------------------------------------------
    total_weight = sum(d.weight for d in dims)
    overall = sum(d.score * d.weight for d in dims) / max(0.01, total_weight)
    # Round once, before comparing: the score shown as 7.0 must not fail a threshold of 7.
    overall = round(max(1.0, min(10.0, overall)), 1)
    passed = overall >= threshold

    # Flaw summary for the rewrite prompt ---------------------------------------
    failing_dims = sorted((d for d in dims if d.score < threshold), key=lambda d: d.score)
    flaw_lines: list[str] = []
    for d in failing_dims:
        flaw_lines.append(f"[{d.name}: {d.score:.1f}/10]")
        for f in d.flaws:
            flaw_lines.append(f"  - {f}")
    flaw_summary = "\n".join(flaw_lines) if flaw_lines else "No major flaws."

    # Natural language explanation -----------------------------------------------
    explanation = _build_explanation(overall, threshold, dims, failing_dims)

    return QualityVerdict(
        dimensions=tuple(dims),
        overall_score=overall,
        passed=passed,
        threshold=threshold,
        flaw_summary=flaw_summary,
        explanation=explanation,
    )


def _build_explanation(
    overall: float, threshold: int, dims: list[DimensionScore], failing: list[DimensionScore]
) -> str:
    """Generate a 1–3 sentence plain-English explanation of the score."""
    if overall >= 9:
        best = max(dims, key=lambda d: d.score * d.weight)
        return f"This post scores {overall:.1f}/10 — excellent. Strongest dimension: {best.name.replace('_', ' ')} ({best.score:.0f}/10)."
    if overall >= threshold:
        weak = min(dims, key=lambda d: d.score)
        return (
            f"This post scores {overall:.1f}/10 and passes the quality bar. "
            f"To push it higher, improve {weak.name.replace('_', ' ')} ({weak.score:.0f}/10)"
            + (f": {weak.flaws[0]}" if weak.flaws else ".")
        )
    # Below threshold
    top_failures = failing[:2]
    parts = []
    for d in top_failures:
        fix = d.flaws[0] if d.flaws else "needs improvement"
        parts.append(f"{d.name.replace('_', ' ')} ({d.score:.0f}/10 — {fix})")
    return f"This post scores {overall:.1f}/10, below the {threshold}/10 bar. Main issues: {'; '.join(parts)}."
