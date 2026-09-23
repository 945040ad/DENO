"""Voice check with Burrows' Delta (the standard stylometric distance).

Delta between texts A and B = mean over the N most frequent function words of |z_A(w) - z_B(w)|, where
z(w) = (relative frequency of w in the text - corpus mean) / corpus standard deviation. The corpus is
the author's own samples plus a small bundled reference of general English, so z-scores measure how
this author differs from typical writing.

A draft passes when its Delta to the author's profile (the mean z-vector of their samples) is closer to
the author's own spread (leave-one-out Deltas) than to other writers' (the reference texts): the
threshold is the midpoint between the two means.
"""

from __future__ import annotations

import math
import re
import statistics
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from deno_gates.gate import Finding, GateContext, GateResult

_TOKEN = re.compile(r"[a-z]+(?:'[a-z]+)?")
MFW = 30
TOLERANCE = 1.15
MIN_SAMPLES = 3

# Generic English reference texts (public-domain style prose) so z-scores have a baseline even with
# few author samples. Kept short; they only anchor the mean/std of common function words.
REFERENCE = (
    "I think the main problem with the way we did it was that nobody owned the process. We had a meeting "
    "every week and the same things came up, and then we went back to our desks and did what we always did.",
    "It took me a while to figure out what was going on. The numbers looked fine but the customers kept "
    "leaving, and when I finally called a few of them they all said the same thing: it was too hard to set up.",
    "We shipped the first version in March. It was rough, and a lot of it was held together with scripts, "
    "but people used it, and that told us more than any of the interviews had.",
    "If you are going to hire your first salesperson, make sure you have sold the thing yourself first. "
    "Otherwise you won't know what good looks like, and you will blame them for problems that are yours.",
    "The report was due on Friday, so on Thursday night I was still at the office reading through old "
    "tickets. Most of them were about billing. Almost none were about the feature we had spent a year on.",
    "My advice is boring: talk to users, write things down, and don't build what you can fake by hand. "
    "It worked for us, though I am sure there are teams it would not work for.",
    "The committee has reviewed the proposal and recommends that the organization adopt the revised "
    "framework. Implementation will require coordination across departments and should be completed by "
    "the end of the fiscal year, subject to budget approval.",
    "Our platform enables teams to streamline their workflows and improve collaboration. With integrated "
    "analytics, managers can monitor performance and make informed decisions that drive measurable results.",
    "lol yeah we tried that. didn't work. ended up just emailing people one by one which is dumb but it's "
    "the only thing that got replies so far. might try calls next week idk",
    "Quick question for anyone who has done this before: how did you price your first plan? We are "
    "thinking about a flat monthly fee but I'm worried it's too low for bigger teams.",
)

# Function words: the standard Delta feature set (topic-independent, frequent enough to be stable).
FUNCTION_WORDS = tuple(
    """the a an and or but if so because as than then that this these those it its it's i i'm i've i'd me my
    we we're our us you you're your he she they they're them their his her who whom which what when where why
    how all any some no not never just only also very really too much many more most less few one two
    of in on at to for from with about into over after before under between through during without
    is are was were be been being am do does did doing have has had having will would can could should
    may might must shall there here now still even yet again ever always often maybe though although while
    until since like well lol yeah ok okay honestly actually basically anyway pretty kind sort""".split()  # noqa: SIM905
)


def tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.lower().replace("’", "'"))


def _rel_freq(text: str, vocab: Sequence[str]) -> list[float]:
    toks = tokens(text)
    counts = Counter(toks)
    n = max(1, len(toks))
    return [counts[w] / n for w in vocab]


@dataclass(frozen=True)
class VoiceProfile:
    vocab: tuple[str, ...]
    means: tuple[float, ...]
    stds: tuple[float, ...]
    centroid: tuple[float, ...]  # mean z-vector of the author's samples
    threshold: float
    sample_deltas: tuple[float, ...]
    strong: bool = False  # ≥5 samples averaging 80+ words: stable enough to block, otherwise advisory

    def z(self, text: str) -> list[float]:
        return [(f - m) / s for f, m, s in zip(_rel_freq(text, self.vocab), self.means, self.stds, strict=True)]

    def delta(self, text: str) -> float:
        z = self.z(text)
        return sum(abs(a - b) for a, b in zip(z, self.centroid, strict=True)) / len(z)

    def to_dict(self) -> dict[str, object]:
        return {
            "vocab": list(self.vocab),
            "means": list(self.means),
            "stds": list(self.stds),
            "centroid": list(self.centroid),
            "threshold": self.threshold,
            "sample_deltas": list(self.sample_deltas),
            "strong": self.strong,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> VoiceProfile:
        return cls(
            vocab=tuple(data["vocab"]),  # type: ignore[arg-type]
            means=tuple(data["means"]),  # type: ignore[arg-type]
            stds=tuple(data["stds"]),  # type: ignore[arg-type]
            centroid=tuple(data["centroid"]),  # type: ignore[arg-type]
            threshold=float(data["threshold"]),  # type: ignore[arg-type]
            sample_deltas=tuple(data["sample_deltas"]),  # type: ignore[arg-type]
            strong=bool(data.get("strong", False)),
        )


def build_profile(samples: Sequence[str], *, mfw: int = MFW) -> VoiceProfile:
    samples = [s for s in samples if len(tokens(s)) >= 20]
    if len(samples) < MIN_SAMPLES:
        raise ValueError(f"need at least {MIN_SAMPLES} samples of 20+ words to build a voice profile")
    corpus = [*samples, *REFERENCE]
    counts = Counter(t for text in corpus for t in tokens(text) if t in FUNCTION_WORDS)
    vocab = tuple(w for w, _ in counts.most_common(mfw))
    freqs = [_rel_freq(t, vocab) for t in corpus]
    means = [statistics.mean(col) for col in zip(*freqs, strict=True)]
    stds = [max(statistics.pstdev(col), 1e-4) for col in zip(*freqs, strict=True)]

    def zvec(text: str) -> list[float]:
        return [(f - m) / s for f, m, s in zip(_rel_freq(text, vocab), means, stds, strict=True)]

    zs = [zvec(s) for s in samples]
    centroid = [statistics.mean(col) for col in zip(*zs, strict=True)]
    # Leave-one-out: how far is each sample from the centroid of the others?
    deltas = []
    for i, zi in enumerate(zs):
        others = [z for j, z in enumerate(zs) if j != i]
        c = [statistics.mean(col) for col in zip(*others, strict=True)]
        deltas.append(sum(abs(a - b) for a, b in zip(zi, c, strict=True)) / len(vocab))

    # Calibrate against other writers: the threshold sits halfway between how far the author's own posts
    # are from their centroid and how far the reference (other people's) texts are.
    def delta_to_centroid(text: str) -> float:
        return float(sum(abs(a - b) for a, b in zip(zvec(text), centroid, strict=True))) / len(vocab)

    own = statistics.mean(delta_to_centroid(t) for t in samples)
    foreign = statistics.mean(delta_to_centroid(t) for t in REFERENCE)
    threshold = (own + foreign) / 2 if foreign > own else max(deltas) * TOLERANCE
    strong = len(samples) >= 5 and statistics.mean(len(tokens(t)) for t in samples) >= 80
    return VoiceProfile(
        vocab,
        tuple(means),
        tuple(stds),
        tuple(centroid),
        round(threshold, 4),
        tuple(round(d, 4) for d in deltas),
        strong,
    )


def voice(text: str, ctx: GateContext | None = None, *, profile: VoiceProfile | None = None) -> GateResult:
    if profile is None:
        if not ctx or len(ctx.voice_samples) < MIN_SAMPLES:
            return GateResult("voice", True, (), score=None)  # no profile yet: nothing to compare against
        profile = build_profile(ctx.voice_samples)
    if len(tokens(text)) < 50:
        return GateResult("voice", True, (), score=None)  # too short for a stable Delta
    d = profile.delta(text)
    if math.isnan(d) or d <= profile.threshold:
        return GateResult("voice", True, (), score=round(d, 4))
    return GateResult(
        "voice",
        not profile.strong,
        (
            Finding(
                "voice.delta",
                f"Doesn't sound like you (Delta {d:.2f}, your own posts vary up to {profile.threshold:.2f})",
                "",
                0,
                0,
                "Rewrite in your own words: your usual openers, sentence length and small words.",
                severity="block" if profile.strong else "warn",
            ),
        ),
        score=round(d, 4),
    )
