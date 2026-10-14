from deno_graphs.validation.verdict import coverage, decide


def test_zero_claims_says_posts_were_off_topic_not_a_missing_source() -> None:
    cov = coverage({"hn": 38, "reddit": 3}, recent=41)
    assert cov.ok
    band = decide(cov, [], {})
    assert band.verdict == "insufficient_evidence"
    assert band.reasons == ["none of the 41 posts found discuss this idea directly"]
