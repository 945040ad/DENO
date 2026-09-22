import uuid

from deno_rag import chunk, is_english, normalise, rrf
from deno_rag.queries import Analyst, analyst_queries
from deno_rag.text import approx_tokens


def test_normalise_strips_boilerplate_and_html() -> None:
    raw = "Churn is killing us &amp; nobody talks about it<br>#saas #growth\nEdit: typo\nhttps://t.co/abc"
    assert normalise(raw) == "Churn is killing us & nobody talks about it"


def test_is_english() -> None:
    assert is_english("I have been struggling with customer churn for months and it is painful")
    assert not is_english("Wir haben seit Monaten Probleme mit der Kundenabwanderung und keiner hilft")
    assert not is_english("顧客離れに何ヶ月も悩んでいて本当に辛いです、誰か助けて")
    assert is_english("SaaS churn tool?")  # too short to judge


def test_short_posts_stay_whole_long_text_splits_with_overlap() -> None:
    assert chunk("one short post") == ["one short post"]
    assert chunk("") == []
    sentences = [f"Sentence number {i} talks about churn and retention in detail." for i in range(300)]
    pieces = chunk(" ".join(sentences))
    assert len(pieces) > 3
    assert all(approx_tokens(p) <= 400 for p in pieces)
    first_tail = pieces[0].split(". ")[-2]
    assert first_tail in pieces[1]  # overlap carries context across the boundary


def test_rrf_rewards_agreement() -> None:
    a, b, c, d = (uuid.uuid4() for _ in range(4))
    assert rrf([a, b, c], [c, d, a])[:2] == [a, c]
    assert rrf([], []) == []


def test_analyst_queries_fill_placeholders() -> None:
    qs = analyst_queries(Analyst.ICP, problem="customer churn", solution="predicts churn", audience="")
    assert qs[0] == "as a founder I deal with customer churn"
    assert all("{" not in q for a in Analyst for q in analyst_queries(a, problem="p", solution="s", audience="x"))
