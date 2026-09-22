"""One-off: generate the synthetic retrieval eval corpus with the NIM LLM (LangChain structured output).

    uv run python scripts/build_retrieval_evalset.py

For each idea the model writes 5 posts that show the target pain/demand (relevant) and
3 hard negatives: same vocabulary and domain, but not about the problem. Every other
idea's posts are also distractors. Output: evals/retrieval/{corpus,queries}.jsonl.
The set is synthetic (labelled `synthetic: true`); swap in real labelled posts as
founders flag claims (Phase 14).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from pydantic import BaseModel, Field

from deno_core.settings import get_settings
from deno_llm import Role, build_stack

OUT = Path(__file__).resolve().parents[1] / "evals" / "retrieval"

IDEAS: list[tuple[str, str]] = [
    ("A tool that predicts SaaS customer churn from support tickets", "SaaS churn you only notice too late"),
    (
        "An AI assistant that writes LinkedIn posts in the founder's own voice",
        "writing LinkedIn posts takes hours and sounds generic",
    ),
    (
        "Automated bookkeeping for freelancers that categorises bank transactions",
        "freelancer bookkeeping and categorising expenses at tax time",
    ),
    (
        "A scheduling tool that finds meeting slots across time zones for remote teams",
        "scheduling meetings across time zones",
    ),
    ("Invoice chasing that sends polite automatic payment reminders", "clients paying invoices late"),
    (
        "A marketplace connecting restaurants with surplus food to local shelters",
        "restaurants throwing away surplus food",
    ),
    ("Flaky test detection for CI pipelines", "flaky tests breaking CI builds"),
    ("A tenant screening app for small landlords", "small landlords getting bad tenants"),
    ("Meal planning for families with kids with allergies", "planning meals around kids' food allergies"),
    ("A podcast editing tool that removes filler words automatically", "editing filler words out of podcast audio"),
    (
        "Price monitoring for Shopify stores watching competitor prices",
        "tracking competitor prices for an online store",
    ),
    ("A habit tracker for ADHD adults with gentle nudges", "ADHD adults failing to keep habits"),
    (
        "Contract review for small businesses that flags risky clauses",
        "small businesses signing contracts with risky clauses",
    ),
    ("An app that helps nurses swap shifts", "nurses struggling to swap shifts"),
    ("Cold email deliverability checker that prevents spam folder placement", "cold emails landing in spam"),
    (
        "A tool that turns customer interviews into a searchable insights database",
        "losing insights from customer interviews",
    ),
    (
        "Receipt scanning for construction contractors to track job costs",
        "construction contractors losing receipts and job costs",
    ),
    (
        "A study planner for medical students preparing for board exams",
        "medical students overwhelmed preparing for boards",
    ),
    ("Kubernetes cost monitoring that finds idle resources", "surprisingly high Kubernetes cloud bills"),
    ("A dog walking scheduler for busy pet owners", "busy pet owners finding reliable dog walkers"),
]


class GenPost(BaseModel):
    text: str = Field(description="A realistic social post (Reddit/X/HN style), 1-4 sentences, first person")


class GenSet(BaseModel):
    relevant: list[GenPost] = Field(
        description="5 posts where the author clearly experiences the problem or asks for a solution"
    )
    hard_negatives: list[GenPost] = Field(
        description="3 posts in the same domain using similar words, but NOT about this problem"
    )


async def main() -> None:
    llm = build_stack(get_settings()).router.structured(Role.STRONG, GenSet, temperature=0.8)
    corpus, queries = [], []
    for i, (idea, problem) in enumerate(IDEAS):
        prompt = (
            f"Idea: {idea}\nProblem: {problem}\n"
            "Write 5 varied posts by different people who have this problem (some angry, some asking for tools, "
            "some describing workarounds), and 3 hard negatives: same industry and vocabulary but about something "
            "else. No hashtags, no emojis, no brand names of real companies. Vary length and tone."
        )
        result = await llm.ainvoke(prompt)
        assert isinstance(result, GenSet)
        rel_ids = []
        for j, p in enumerate(result.relevant[:5]):
            doc_id = f"i{i:02d}-r{j}"
            rel_ids.append(doc_id)
            corpus.append({"id": doc_id, "idea": i, "text": p.text, "synthetic": True})
        for j, p in enumerate(result.hard_negatives[:3]):
            corpus.append({"id": f"i{i:02d}-n{j}", "idea": i, "text": p.text, "synthetic": True})
        queries.append({"idea": i, "idea_text": idea, "query": problem, "relevant": rel_ids})
        print(i, len(result.relevant), len(result.hard_negatives), flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "corpus.jsonl").write_text("".join(json.dumps(c) + "\n" for c in corpus))
    (OUT / "queries.jsonl").write_text("".join(json.dumps(q) + "\n" for q in queries))


if __name__ == "__main__":
    asyncio.run(main())
