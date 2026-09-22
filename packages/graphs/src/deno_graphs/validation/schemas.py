"""Structured-output schemas for the validation graph's LLM nodes."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class IdeaBrief(BaseModel):
    is_coherent: bool = Field(description="False for empty, gibberish, non-business or harmful ideas")
    reject_reason: str | None = Field(default=None, description="One sentence, only when not coherent")
    problem: str = Field(default="", description="The pain, in the words of someone who has it")
    solution: str = Field(default="", description="What the product does, in one line")
    audience: str = Field(default="", description="Who has the problem (role, company type)")
    category: str = Field(default="", description="Product category in 2-4 words")
    keywords: list[str] = Field(default_factory=list, description="3-8 short phrases people would use")


class Perspective(BaseModel):
    name: str
    questions: list[str]


class Perspectives(BaseModel):
    perspectives: list[Perspective] = Field(description="4-6 distinct perspectives")


class QueryPlan(BaseModel):
    subreddits: list[str] = Field(description="3-6 subreddit names without r/")
    reddit: list[str]
    hn: list[str]
    x: list[str]
    linkedin_posts: list[str]
    linkedin_jobs: list[str] = Field(description="job titles or skills")
    competitors: str = Field(description="product category in 2-3 words")


class DraftClaim(BaseModel):
    claim: str
    stance: Literal["supports", "refutes", "neutral"]
    source_ids: list[str] = Field(description="ids like S3 of the sources that support the claim")


class AnalystOutput(BaseModel):
    claims: list[DraftClaim]


class Judgement(BaseModel):
    pair_id: str
    entailed: bool
    score: float = Field(ge=0, le=1)


class Judgements(BaseModel):
    judgements: list[Judgement]


class Issue(BaseModel):
    claim_id: str
    problem: str


class Critique(BaseModel):
    issues: list[Issue]


class RefinedClaim(BaseModel):
    claim_id: str
    claim: str
    stance: Literal["supports", "refutes", "neutral"]


class Refinement(BaseModel):
    claims: list[RefinedClaim]


class Rationale(BaseModel):
    rationale: str
