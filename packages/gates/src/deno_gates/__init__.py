"""Deterministic gates for AI-sounding and ban-prone social posts (open-source as `deno-slop-gate`)."""

from deno_gates.compliance import compliance
from deno_gates.gate import CommunityRules, Finding, GateContext, GateResult
from deno_gates.layers import autofix, density, number_words_in, numbers_in, patterns, scrub, structure
from deno_gates.pipeline import GateReport, run_gates
from deno_gates.quality import (
    DEFAULT_THRESHOLD,
    MAX_REGEN_ATTEMPTS,
    DimensionScore,
    QualityVerdict,
    compute_adaptive_threshold,
    score_quality,
)
from deno_gates.voice import VoiceProfile, build_profile, voice

__all__ = [
    "DEFAULT_THRESHOLD",
    "MAX_REGEN_ATTEMPTS",
    "CommunityRules",
    "DimensionScore",
    "Finding",
    "GateContext",
    "GateReport",
    "GateResult",
    "QualityVerdict",
    "VoiceProfile",
    "autofix",
    "build_profile",
    "compliance",
    "compute_adaptive_threshold",
    "density",
    "number_words_in",
    "numbers_in",
    "patterns",
    "run_gates",
    "score_quality",
    "scrub",
    "structure",
    "voice",
]
