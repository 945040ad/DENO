"""seed communities, rules and default quotas

Communities and rules come from docs/05_PLATFORM_RULES_AND_COMMUNITIES.md. They
are *unverified* (verified_at NULL) until Phase 5's rule checker has compared
them with each community's live rules page. Quotas are placeholders until
pricing is decided (PRD open question).

Revision ID: 0002
Revises: 0001
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SEED_NS = uuid.UUID("6f2b8a52-3c3e-4b8e-9a51-0d1f5e3c7a10")
SOURCE = "docs/05_PLATFORM_RULES_AND_COMMUNITIES.md"

# platform, name, url, audience, karma gate, promo policy, ai policy, cadence, min days, value:promo
COMMUNITIES = [
    (
        "reddit",
        "r/SaaS",
        "https://www.reddit.com/r/SaaS/",
        "B2B SaaS founders",
        "50 karma, 14 days",
        "Sundays only; 9:1 value to promo",
        "Zero tolerance for raw AI",
        "1 post / 4 days",
        4,
        9,
    ),
    (
        "reddit",
        "r/SideProject",
        "https://www.reddit.com/r/SideProject/",
        "Indie hackers & builders",
        "10 karma, 7 days",
        "Direct demo allowed with a story",
        "No low-effort synthetic content",
        "1 post / 7 days",
        7,
        None,
    ),
    (
        "reddit",
        "r/startups",
        "https://www.reddit.com/r/startups/",
        "Growth & venture startups",
        "100 comment karma",
        "Strict: feedback thread only",
        "Instant permanent ban",
        "1 post / 14 days",
        14,
        None,
    ),
    (
        "reddit",
        "r/Entrepreneur",
        "https://www.reddit.com/r/Entrepreneur/",
        "Small business & solopreneurs",
        "10 karma",
        "Case studies allowed, no links in post",
        "Heavily flagged",
        "1 post / 5 days",
        5,
        None,
    ),
    (
        "reddit",
        "r/webdev",
        "https://www.reddit.com/r/webdev/",
        "Technical builders",
        "30 karma, 30 days",
        "Showoff Saturday only",
        "Technical substance required",
        "1 post / 7 days",
        7,
        None,
    ),
    (
        "reddit",
        "r/microSaaS",
        "https://www.reddit.com/r/microSaaS/",
        "Micro & solo SaaS",
        "10 karma",
        "Open with verified metrics",
        "Authentic discussions only",
        "1 post / 3 days",
        3,
        None,
    ),
    (
        "reddit",
        "r/ProductHunters",
        "https://www.reddit.com/r/ProductHunters/",
        "Launch audiences",
        "5 karma",
        "Launch announcements allowed",
        "Allowed with a real author",
        "1 post / 2 days",
        2,
        None,
    ),
    (
        "reddit",
        "r/indiehackers",
        "https://www.reddit.com/r/indiehackers/",
        "Bootstrapped founders",
        "20 karma",
        "Open build-in-public",
        "AI flagged by community",
        "1 post / 3 days",
        3,
        None,
    ),
    (
        "linkedin",
        "B2B Founders Network",
        None,
        "B2B executives & angels",
        None,
        "Link in first comment; ~1,100 chars",
        "High sensitivity to buzzwords",
        "3 posts / week",
        2,
        None,
    ),
    (
        "linkedin",
        "SaaS Growth & Marketing",
        None,
        "VPs of marketing & product",
        None,
        "High-density case studies",
        "Slop filter active",
        "2 posts / week",
        3,
        None,
    ),
    (
        "x",
        "#buildinpublic",
        "https://x.com/search?q=%23buildinpublic",
        "Early tech adopters",
        None,
        "Value threads",
        "High velocity",
        "1-2 posts / day",
        1,
        None,
    ),
    (
        "x",
        "#indiehackers",
        "https://x.com/search?q=%23indiehackers",
        "Solopreneurs",
        None,
        "Transparent revenue / metrics",
        "Prefers concise bullets",
        "1 post / day",
        1,
        None,
    ),
]

# plan, kind, monthly_limit, max_concurrent
QUOTAS = [
    ("free", "validation_run", 5, 1),
    ("free", "content_plan", 1, 1),
    ("free", "audit", 200, 1),
    ("pro", "validation_run", 50, 3),
    ("pro", "content_plan", 20, 2),
    ("pro", "audit", 5000, 3),
]


def _id(*parts: str) -> uuid.UUID:
    return uuid.uuid5(SEED_NS, "|".join(parts))


def upgrade() -> None:
    communities = sa.table(
        "communities",
        sa.column("id", sa.Uuid),
        sa.column("platform", sa.String),
        sa.column("name", sa.String),
        sa.column("url", sa.String),
        sa.column("audience", sa.String),
    )
    rules = sa.table(
        "community_rules",
        sa.column("id", sa.Uuid),
        sa.column("community_id", sa.Uuid),
        sa.column("karma_gate", sa.String),
        sa.column("promo_policy", sa.String),
        sa.column("ai_policy", sa.String),
        sa.column("cadence", sa.String),
        sa.column("min_days_between_posts", sa.Integer),
        sa.column("value_to_promo_ratio", sa.Integer),
        sa.column("source_url", sa.String),
    )
    quotas = sa.table(
        "quotas",
        sa.column("plan", sa.String),
        sa.column("kind", sa.String),
        sa.column("monthly_limit", sa.Integer),
        sa.column("max_concurrent", sa.Integer),
    )
    op.bulk_insert(
        communities,
        [{"id": _id(p, n), "platform": p, "name": n, "url": u, "audience": a} for p, n, u, a, *_ in COMMUNITIES],
    )
    op.bulk_insert(
        rules,
        [
            {
                "id": _id(p, n, "rule"),
                "community_id": _id(p, n),
                "karma_gate": k,
                "promo_policy": promo,
                "ai_policy": ai,
                "cadence": cad,
                "min_days_between_posts": days,
                "value_to_promo_ratio": ratio,
                "source_url": SOURCE,
            }
            for p, n, _u, _a, k, promo, ai, cad, days, ratio in COMMUNITIES
        ],
    )
    op.bulk_insert(
        quotas, [{"plan": p, "kind": k, "monthly_limit": lim, "max_concurrent": c} for p, k, lim, c in QUOTAS]
    )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM quotas"))
    ids = [str(_id(p, n)) for p, n, *_ in COMMUNITIES]
    op.execute(
        sa.text("DELETE FROM community_rules WHERE community_id = ANY(CAST(:ids AS uuid[]))").bindparams(ids=ids)
    )
    op.execute(sa.text("DELETE FROM communities WHERE id = ANY(CAST(:ids AS uuid[]))").bindparams(ids=ids))
