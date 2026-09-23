"""Deterministic gate layers L1–L4. Each is ``(text, ctx) -> GateResult`` and reports every match."""

from __future__ import annotations

import re
import statistics

from deno_gates.gate import Finding, GateContext, GateResult
from deno_gates.rules import ABSTRACT_NOUNS, HEDGES, PATTERN_RULES, SCRUB_RULES, Rule

_SENTENCE = re.compile(r"[^.!?\n]+[.!?]*")
_WORD = re.compile(r"[A-Za-z][A-Za-z'’-]*")
_NUMBER = re.compile(r"(?<![\w.])\$?\d[\d,]*(?:\.\d+)?%?[kKmM]?")
_NUMBER_WORD = re.compile(
    r"\b(two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|"
    r"seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundreds?|thousands?|"
    r"millions?|dozens?|half a dozen|a dozen|a couple of)\b",
    re.IGNORECASE,
)
_EXPERIENCE = re.compile(
    r"\b(here'?s what (i|we) did"
    r"|(i|we)(\s+(just|finally|then|once|really|actually|still|even|never|always|also))?\s+"
    r"(was|were|had|did|got|went|made|sent|told|wrote|felt|thought|knew|kept|left|took|gave|came|sat|stood|ran|lost|"
    r"found|saw|built|spent|paid|began|heard|chose|met|became|used to|[a-z]{2,}ed)\b"
    r"|(i|we)'d (been|had|done|spent)\b"
    r"|my (client|customer|cofounder|co-founder|boss|manager|team|agency|startup|first (client|customer|hire))\s+(said|told|asked|wrote|was|had|[a-z]{2,}ed)\b"
    r"|(last|this past) (week|month|quarter|year|spring|summer|fall|winter|monday|friday)\b"
    r"|after (a|one|two|three) (week|month)s?\b"
    r"|a (client|customer|user|founder) (told|said|asked|wrote) me"
    r"|(i|we)'?ve (talked|spoken|worked|chatted) (to|with)\b"
    r"|(one|some|most|many) of (them|those|the \w+) (told|said|asked|wrote)( me)?\b"
    r"|\bone (put it|told me|said to me)\b)",
    re.IGNORECASE,
)
_HOOK_LABEL = re.compile(r"^\s*F\d{1,2}\s*[:.)-]\s*", re.MULTILINE)
_DASH = re.compile(r"—|–")  # typed hyphens (" - ", "--") are how people write; the typographic dash is the tell


def _matches(rule: Rule, text: str) -> list[Finding]:
    return [
        Finding(
            rule_id=rule.id,
            message=rule.message,
            quote=m.group(0).strip()[:160],
            start=m.start(),
            end=m.end(),
            fix=rule.fix,
            severity="block" if rule.severity == "block" else "warn",
        )
        for m in rule.pattern.finditer(text)
    ]


def number_words_in(text: str) -> set[str]:
    return {m.group(0).lower() for m in _NUMBER_WORD.finditer(text)}


def numbers_in(text: str) -> set[str]:
    """Normalised numbers as the L1 unsourced-number check compares them ("$12,000" → "12000")."""
    return {m.group(0).strip("$%").replace(",", "").lower() for m in _NUMBER.finditer(text)}


def words(text: str) -> list[str]:
    return _WORD.findall(text)


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE.findall(text) if len(words(s)) > 0]


def paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


# ---- L1 -----------------------------------------------------------------------------------


MARKDOWN_OK = {"reddit", "hn"}


def scrub(text: str, ctx: GateContext | None = None) -> GateResult:
    platform = ctx.platform if ctx else "linkedin"
    findings = [
        f
        for rule in SCRUB_RULES
        if not (rule.id.startswith("L1.markdown") and platform in MARKDOWN_OK)
        for f in _matches(rule, text)
    ]
    n_words = max(1, len(words(text)))
    dashes = list(_DASH.finditer(text))
    if len(dashes) > max(1, n_words // 150):  # at most ~1 dash per 150 words
        findings += [
            Finding("L1.em_dash", "Em-dash overuse", m.group(0), m.start(), m.end(), "Use a comma, colon or full stop.")
            for m in dashes
        ]
    findings += [
        Finding(
            "L1.leak.hook_label",
            "Internal hook label left in the post",
            m.group(0).strip(),
            m.start(),
            m.end(),
            "Delete it.",
        )
        for m in _HOOK_LABEL.finditer(text)
    ]
    if ctx and ctx.story_attached is False:
        findings += [
            Finding(
                "L1.unsourced_story",
                "First-person story with no Story Bank entry behind it",
                m.group(0),
                m.start(),
                m.end(),
                "Add the real story to your Story Bank, or turn this into an opinion or a question.",
            )
            for m in _EXPERIENCE.finditer(text)
        ]
    if ctx and ctx.check_numbers:
        for m in _NUMBER_WORD.finditer(text):
            if m.group(0).lower() not in ctx.allowed_number_words:
                findings.append(
                    Finding(
                        "L1.unsourced_number",
                        "Spelled-out number that isn't in your Story Bank",
                        m.group(0),
                        m.start(),
                        m.end(),
                        "Only use counts you can stand behind (add the story first), or say it without a number.",
                    )
                )
        for m in _NUMBER.finditer(text):
            value = m.group(0).strip("$%").replace(",", "").lower()
            if value not in ctx.allowed_numbers and not (value.isdigit() and 1900 <= int(value) <= 2100):
                findings.append(
                    Finding(
                        "L1.unsourced_number",
                        "Number that isn't in your Story Bank or evidence",
                        m.group(0),
                        m.start(),
                        m.end(),
                        "Use a real number you can stand behind, or say it without one.",
                    )
                )
    findings.sort(key=lambda f: f.start)
    return GateResult("L1_scrub", not any(f.severity == "block" for f in findings), tuple(findings))


def autofix(text: str) -> str:
    """Safe mechanical fixes only: leakage lines, markdown, dashes, curly spacing. Never rewrites meaning."""
    out = _HOOK_LABEL.sub("", text)
    for rule in SCRUB_RULES:
        if rule.id in {"L1.leak.preamble", "L1.leak.meta", "L1.leak.closer"}:
            out = rule.pattern.sub("", out)
        elif rule.id == "L1.markdown.bold":
            out = rule.pattern.sub(lambda m: m.group(0).strip("*"), out)
        elif rule.id == "L1.markdown.header":
            out = re.sub(r"^#{1,6}\s+", "", out, flags=re.MULTILINE)
    out = re.sub(r"\s*[—–]\s*", ", ", out)
    out = re.sub(r"\s+--\s+", ", ", out)
    out = re.sub(r",\s*,", ",", out)
    out = re.sub(r"[ \t]+\n", "\n", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


# ---- L2 -----------------------------------------------------------------------------------


def patterns(text: str, ctx: GateContext | None = None) -> GateResult:
    findings = sorted((f for rule in PATTERN_RULES for f in _matches(rule, text)), key=lambda f: f.start)
    return GateResult("L2_patterns", not any(f.severity == "block" for f in findings), tuple(findings))


# ---- L3 -----------------------------------------------------------------------------------

DENSITY_LIMIT = 6.0  # weighted tells per 100 words in any paragraph


def density(text: str, ctx: GateContext | None = None) -> GateResult:
    """Per paragraph: (warn-level pattern hits + hedges + abstract nouns without a concrete anchor) per 100 words."""
    findings: list[Finding] = []
    worst = 0.0
    offset = 0
    for para in paragraphs(text):
        start = text.find(para, offset)
        offset = start + len(para)
        n = len(words(para))
        if n < 12:
            continue
        hedges = HEDGES.findall(para)
        abstract = ABSTRACT_NOUNS.findall(para)
        concrete = len(_NUMBER.findall(para)) + len(re.findall(r"(?<!^)(?<![.!?]\s)\b[A-Z][a-z]+", para))
        abstract_weight = max(0, len(abstract) - concrete)
        score = (len(hedges) * 1.5 + abstract_weight) * 100 / n
        worst = max(worst, score)
        if score > DENSITY_LIMIT:
            findings.append(
                Finding(
                    "L3.density",
                    f"Paragraph is vague: {len(hedges)} hedges, {len(abstract)} abstract nouns, {concrete} concrete details",
                    para[:160],
                    start,
                    start + len(para),
                    "Swap abstractions for a specific person, number, tool or moment.",
                )
            )
    return GateResult("L3_density", not findings, tuple(findings), score=round(worst, 2))


# ---- L4 -----------------------------------------------------------------------------------

_TRIAD = re.compile(r"\b(\w+(?: \w+)?), (\w+(?: \w+)?),? and (\w+(?: \w+)?)\b")
_CONTRAST = re.compile(r"\b(not|isn'?t|wasn'?t|aren'?t)\b[^.\n]{1,50}\b(but|—|instead)\b", re.IGNORECASE)


def structure(text: str, ctx: GateContext | None = None) -> GateResult:
    findings: list[Finding] = []
    sents = sentences(text)
    lengths = [len(words(s)) for s in sents]
    n_words = sum(lengths)

    triads = list(_TRIAD.finditer(text))
    if len(triads) >= 3:
        findings += [
            Finding(
                "L4.triads", "Rule-of-three lists stacked up", m.group(0), m.start(), m.end(), "Keep one list, max."
            )
            for m in triads
        ]
    contrasts = list(_CONTRAST.finditer(text))
    if len(contrasts) >= 2:
        findings += [
            Finding("L4.contrasts", "Repeated not-X-but-Y framing", m.group(0), m.start(), m.end(), "Say it straight.")
            for m in contrasts
        ]
    if len(lengths) >= 8:
        fragments = sum(1 for n in lengths if n <= 3)
        if fragments / len(lengths) > 0.4:
            findings.append(
                Finding(
                    "L4.fragments",
                    f"{fragments} of {len(lengths)} sentences are fragments",
                    "",
                    0,
                    0,
                    "Join fragments into normal sentences.",
                )
            )
        spread = statistics.pstdev(lengths) / max(1.0, statistics.mean(lengths))
        if spread < 0.25 and n_words > 60:
            findings.append(
                Finding(
                    "L4.monotone",
                    "Every sentence is about the same length",
                    "",
                    0,
                    0,
                    "Mix a short sentence with a longer one; people don't write in even beats.",
                    severity="warn",
                )
            )
    lines = [ln for ln in text.split("\n") if ln.strip()]
    if len(lines) >= 10 and sum(1 for ln in lines if len(sentences(ln)) <= 1) / len(lines) > 0.9 and n_words < 250:
        findings.append(
            Finding(
                "L4.broetry",
                "One sentence per line all the way down",
                "",
                0,
                0,
                "Group related sentences into short paragraphs.",
            )
        )
    questions = text.count("?")
    if questions >= 3 and questions / max(1, len(sents)) > 0.3:
        findings.append(
            Finding("L4.questions", "Too many rhetorical questions", "", 0, 0, "Answer them instead.", severity="warn")
        )
    return GateResult("L4_structure", not any(f.severity == "block" for f in findings), tuple(findings))
