"""Deterministic gates for AI-sounding and ban-prone social posts (open-source as `deno-slop-gate`)."""

from deno_gates.compliance import compliance
from deno_gates.gate import CommunityRules, Finding, GateContext, GateResult
from deno_gates.layers import autofix, density, number_words_in, numbers_in, patterns, scrub, structure
from deno_gates.pipeline import GateReport, run_gates
from deno_gates.voice import VoiceProfile, build_profile, voice

__all__ = [
    "CommunityRules",
    "Finding",
    "GateContext",
    "GateReport",
    "GateResult",
    "VoiceProfile",
    "autofix",
    "build_profile",
    "compliance",
    "density",
    "number_words_in",
    "numbers_in",
    "patterns",
    "run_gates",
    "scrub",
    "structure",
    "voice",
]
