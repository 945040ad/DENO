"""Per-analyst retrieval query templates. Each analyst runs every template and merges hits."""

from __future__ import annotations

from enum import StrEnum


class Analyst(StrEnum):
    PAIN = "pain"
    DEMAND = "demand"
    COMPETITORS = "competitors"
    ICP = "icp"
    WTP = "wtp"
    RISKS = "risks"
    COMMUNITIES = "communities"


TEMPLATES: dict[Analyst, tuple[str, ...]] = {
    Analyst.PAIN: (
        "{problem} is frustrating, painful, a waste of time",
        "I hate dealing with {problem}; struggling with {problem}",
        "how do you handle {problem}? anyone else have this problem",
    ),
    Analyst.DEMAND: (
        "looking for a tool that {solution}",
        "is there an app or software for {problem}",
        "I would pay for something that {solution}; wish there was a way to {solution}",
    ),
    Analyst.COMPETITORS: (
        "alternatives to existing tools for {problem}",
        "I tried a product for {problem} and it was not good enough",
        "launched a tool that {solution}",
    ),
    Analyst.ICP: (
        "as a {audience} I deal with {problem}",
        "{audience} workflow for {problem}",
    ),
    Analyst.WTP: (
        "how much do you pay for a tool for {problem}; pricing, too expensive, worth it",
        "we budget for {problem}; paid plan subscription for {solution}",
    ),
    Analyst.RISKS: (
        "{problem} is not a big deal, we just use a spreadsheet",
        "tried tools that {solution} and stopped using them",
        "why {solution} does not work; problems with tools for {problem}",
    ),
    Analyst.COMMUNITIES: (
        "{audience} talking about {problem}",
        "where do {audience} discuss {problem}",
    ),
}


def analyst_queries(analyst: Analyst, *, problem: str, solution: str, audience: str) -> list[str]:
    values = {"problem": problem.strip(), "solution": solution.strip(), "audience": audience.strip() or "founder"}
    return [t.format(**values) for t in TEMPLATES[analyst]]
