"""Rule tables for L1 (scrub) and L2 (hard-fail patterns).

Sources: petergyang/no-ai-slop cut lists and structural patterns, sergebulaev/linkedin-skills
humanizer FORENSIC/STRICT rules, and Deno v1 ``anti_slop.py`` (all 16 patterns kept, plus the
two it was missing: "Negative Parallelism" and "Copula Avoidance"). Every match is reported.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Rule:
    id: str
    pattern: re.Pattern[str]
    message: str
    fix: str
    severity: str = "block"


def _r(rule_id: str, regex: str, message: str, fix: str, severity: str = "block", flags: int = re.IGNORECASE) -> Rule:
    return Rule(rule_id, re.compile(regex, flags), message, fix, severity)


# ---- L1: model leakage and placeholders (auto-fixable where safe) -------------------------

SCRUB_RULES: tuple[Rule, ...] = (
    _r(
        "L1.leak.assistant",
        r"\b(as an ai( language model)?|i'?m an ai|as a large language model|i cannot browse)\b",
        "Model self-reference",
        "Delete the sentence.",
    ),
    _r(
        "L1.leak.preamble",
        r"^\s*(certainly|sure|absolutely|of course)[!,.]?\s+(here'?s|here is|below is)\b[^\n]*\n?",
        "Chatbot preamble",
        "Delete the preamble line.",
        flags=re.IGNORECASE | re.MULTILINE,
    ),
    _r(
        "L1.leak.meta",
        r"^\s*(here'?s|here is) (a|an|the|your) (linkedin|reddit|x|twitter)? ?(post|draft|version|thread)\b[^\n]*\n?",
        "Draft-about-the-draft line",
        "Delete the line.",
        flags=re.IGNORECASE | re.MULTILINE,
    ),
    _r(
        "L1.leak.closer",
        r"\b(i hope (this|that) helps|let me know if you('d| would) like|feel free to (adjust|tweak|customi[sz]e))\b[^\n]*",
        "Chatbot closer",
        "Delete it.",
    ),
    _r(
        "L1.placeholder",
        r"\[(your|insert|company|name|product|link|x|number)[^\]]{0,30}\]|\{\{[a-z_ ]{2,30}\}\}|<(insert|your)[^>]{0,30}>",
        "Unfilled placeholder",
        "Replace with the real detail from your Story Bank, or cut the sentence.",
    ),
    _r("L1.markdown.bold", r"\*\*[^*\n]{1,80}\*\*", "Markdown bold (renders as asterisks)", "Remove the asterisks."),
    _r(
        "L1.markdown.header",
        r"^#{1,6}\s+\S",
        "Markdown header in a social post",
        "Remove the #.",
        flags=re.MULTILINE,
    ),
)

# ---- L2: hard-fail patterns ---------------------------------------------------------------

_VOCAB = (
    r"delve|delving|tapestry|testament to|game[- ]?changer|game[- ]?changing|unlock(ing)? (the|your)|"
    r"elevate (your|the)|seamless(ly)?|robust|leverag(e|ing)|navigat(e|ing) the|ever[- ]evolving|"
    r"fast[- ]paced (world|landscape)|in today'?s (digital|fast|competitive|ever)|landscape of|realm of|"
    r"harness(ing)? the power|embark(ing)? on|a journey of|paradigm shift|synergy|cutting[- ]edge|"
    r"revolutioni[sz]e|supercharge|unleash|empower(ing)? (you|teams|businesses)|holistic|"
    r"multifaceted|pivotal|intricate|meticulous(ly)?|underscore[sd]?|showcas(e|ing)|foster(ing)?|"
    r"transformative|actionable insights|dive (deep|into)|deep dive|let'?s dive in|buckle up|"
    r"at its core|the power of|not just (a|an) |more than just"
)

PATTERN_RULES: tuple[Rule, ...] = (
    _r("L2.vocab", rf"\b({_VOCAB})\b", "AI-typical vocabulary", "Use the plain word you'd say out loud."),
    _r(
        "L2.opener.announce",
        r"^\s*(i'?m (so )?(thrilled|excited|humbled|honou?red|delighted) to (announce|share)|big news|exciting news)",
        "Announcement opener",
        "Start with the thing itself.",
        flags=re.IGNORECASE | re.MULTILINE,
    ),
    _r(
        "L2.opener.hook",
        r"^\s*(unpopular opinion|hot take|here'?s the thing|let me be (honest|clear)|the uncomfortable truth|truth be told|"
        r"stop scrolling|read that again|i'?ll say it)\b",
        "Throat-clearing hook",
        "Cut the setup and lead with the claim.",
        flags=re.IGNORECASE | re.MULTILINE,
    ),
    _r(
        "L2.binary_contrast",
        r"\b(it'?s|this is|that'?s) not (just )?(about )?[^.\n]{2,60}[.,;:]\s*(it'?s|this is|that'?s) (about )?",
        "Binary contrast (\"It's not X. It's Y.\")",
        "State Y directly.",
    ),
    _r(
        "L2.negative_parallelism",
        r"\bnot (because|only|just) [^.\n]{2,50},? but (because|also)?\b",
        'Negative parallelism ("not X, but Y")',
        "Say what it is.",
        severity="warn",
    ),
    _r(
        "L2.faux_insight",
        r"\b(what (nobody|no one|most people) (tells you|gets wrong|realize)|the part (everyone|most people) (misses|skips)|"
        r"here'?s what (most|nobody)|the real (secret|reason) is)\b",
        "Faux-insight setup",
        "Drop the pedestal; give the insight.",
    ),
    _r(
        "L2.colon_reveal",
        r"\b(the (detail|secret|key|catch|best part|kicker|twist|lesson|result|truth)):\s",
        "Colon drama reveal",
        "Write it as a normal sentence.",
    ),
    _r(
        "L2.trailing_participle",
        r",\s*(highlighting|underscoring|reflecting|showcasing|demonstrating|emphasi[sz]ing|ensuring|fostering)\s+(the|their|its|how|a)\b",
        "Superficial trailing analysis",
        "Replace with the concrete consequence, or cut.",
    ),
    _r(
        "L2.puffery",
        r"\b(stands as a|marks a pivotal|plays a (vital|crucial|key|pivotal) role|solidif(y|ies) (its|their) position|"
        r"cannot be overstated|a crucial (step|role))\b",
        "Importance puffery",
        "State the fact; let the reader judge.",
    ),
    _r(
        "L2.metadiscourse",
        r"\b(that (last part|detail) matters|as you can see|the key (point|takeaway) (here )?is|in other words|this distinction matters|"
        r"it'?s (important|worth) (to note|noting|mentioning))\b",
        "Authorial coaching",
        "Delete it.",
    ),
    _r(
        "L2.weasel",
        r"\b(experts (agree|say)|(industry )?(reports|studies|research) (show|suggest)s?|many (argue|believe)|widely regarded)\b",
        "Weasel attribution",
        "Name the source, or cut the claim.",
    ),
    _r(
        "L2.copula_avoidance",
        r"\b(serves as (a|an|the)|stands as (a|an|the)|functions as (a|an|the)|acts as (a|an) (catalyst|bridge|testament))\b",
        "Copula avoidance",
        'Use "is".',
    ),
    _r(
        "L2.fake_strong_verb",
        r"\b(has the ability to|is designed to function as|is able to effectively)\b",
        "Padded verb",
        'Use "can".',
        severity="warn",
    ),
    _r(
        "L2.negative_listing",
        r"\bnot (a|an) [^.,\n]+, not (a|an) [^.,\n]+,? (but|just) ",
        "Negative listing",
        "Say what it is.",
    ),
    _r(
        "L2.staccato",
        r"\b(that'?s it\. that'?s the (whole )?(thing|secret|story)|short\. punchy\. done|code\. ship\. repeat|no fluff\.)",
        "Staccato theatrics",
        "Write normal sentences.",
    ),
    _r(
        "L2.rhetorical_theatre",
        r"\b(what if i told you|think about (it|that) for a (second|moment)|plot twist|spoiler( alert)?:|guess what\??)\b",
        "Rhetorical theatrics",
        "Just explain it.",
    ),
    _r(
        "L2.kicker",
        r"(at the end of the day|the future belongs to|the rest is history|and that'?s the (real )?(lesson|point)|"
        r"let that sink in|food for thought)[.!]?\s*$",
        "Aphorism kicker",
        "End on a concrete detail or a real question.",
        flags=re.IGNORECASE | re.MULTILINE,
    ),
    _r(
        "L2.recap",
        r"\b(in conclusion|in summary|to (sum|wrap) (it|things) up|the key takeaway|tl;?dr:?\s*$|bottom line:)\b",
        "Summary recap",
        "Cut the recap.",
    ),
    _r(
        "L2.emoji_bullets",
        r"^[\s]*[🚀🔥💡✨🎯📌⚡👉✅🔑📈💪🙌➡️▶️•]\s*\S",
        "Emoji bullets / headers",
        "Use plain lines.",
        flags=re.MULTILINE,
    ),
    _r(
        "L2.engagement_bait",
        r"\b(agree\?|thoughts\?|what do you think\?|drop a comment|comment below|like (and|&) share|repost if|follow for more|"
        r"tag someone who)\s*$",
        "Engagement bait",
        "Ask a specific question, or none.",
        severity="warn",
        flags=re.IGNORECASE | re.MULTILINE,
    ),
    _r(
        "L2.hashtag_wall",
        r"(#\w+\s*){4,}",
        "Hashtag wall",
        "Two hashtags at most, or none.",
    ),
)

HEDGES = re.compile(
    r"\b(arguably|perhaps|potentially|it seems|somewhat|in many ways|to some extent|generally speaking|"
    r"it could be argued|may or may not)\b",
    re.IGNORECASE,
)
ABSTRACT_NOUNS = re.compile(
    r"\b(innovation|excellence|success|growth|value|impact|journey|mindset|strategy|solutions?|ecosystem|"
    r"transformation|efficiency|productivity|potential|opportunit(y|ies)|alignment|engagement|outcomes?)\b",
    re.IGNORECASE,
)
