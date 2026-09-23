"""Community compliance (ban risk) from the community's actual rules. No invented probabilities."""

from __future__ import annotations

import re

from deno_gates.gate import Finding, GateContext, GateResult

_LINK = re.compile(r"https?://\S+|\b[\w-]+\.(com|io|ai|app|co|dev|so)\b(/\S*)?", re.IGNORECASE)
_PROMO = re.compile(
    r"\b(sign up|signup|free trial|discount|promo code|use code|link in (bio|comments)|check (it|us) out|"
    r"we'?re launching|just launched|our (app|product|tool|startup)|dm me|book a (call|demo)|waitlist)\b",
    re.IGNORECASE,
)
_AI_BANNED = re.compile(
    r"\b(no|ban(ned)?|not allowed|prohibit)\b[^.]{0,40}\b(ai|chatgpt|llm|generated)\b", re.IGNORECASE
)


def compliance(text: str, ctx: GateContext) -> GateResult:
    findings: list[Finding] = []
    rules = ctx.community
    links = list(_LINK.finditer(text))
    promo = list(_PROMO.finditer(text))
    promo_policy = (rules.promo_policy or "").lower() if rules else ""

    if ctx.platform == "reddit":
        for m in links:
            findings.append(
                Finding(
                    "ban.reddit_link",
                    "Link in a Reddit post body",
                    m.group(0),
                    m.start(),
                    m.end(),
                    "Remove the link; answer with it only if someone asks.",
                )
            )
        no_promo = any(k in promo_policy for k in ("no self-promo", "no promotion", "no self promotion", "banned"))
        for m in promo:
            findings.append(
                Finding(
                    "ban.promo",
                    "Self-promotion wording" + (" in a community that bans it" if no_promo else ""),
                    m.group(0),
                    m.start(),
                    m.end(),
                    "Share the experience; leave the product out unless the rules allow it.",
                    severity="block" if (no_promo or not ctx.is_promotional) else "warn",
                )
            )
    elif ctx.platform == "linkedin" and links:
        findings += [
            Finding(
                "ban.linkedin_link",
                "Link in the post body (LinkedIn cuts reach)",
                m.group(0),
                m.start(),
                m.end(),
                "Put the link in the first comment.",
                severity="warn",
            )
            for m in links
        ]
    if rules and rules.ai_policy and _AI_BANNED.search(rules.ai_policy):
        findings.append(
            Finding(
                "ban.ai_policy",
                f"{rules.name or 'This community'} bans AI-written posts",
                "",
                0,
                0,
                "Post only after you have rewritten it yourself, in your own words.",
                severity="warn",
            )
        )
    return GateResult("compliance", not any(f.severity == "block" for f in findings), tuple(findings))
