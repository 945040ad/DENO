"""How a source reports failure when several of its searches run at once."""

from deno_graphs.validation.nodes import ERROR_PRIORITY, worst_error


def test_no_errors_is_no_error() -> None:
    assert worst_error([]) is None


def test_policy_block_outranks_everything() -> None:
    """A host we are not allowed to read is the one thing an operator can act on."""
    assert worst_error(["error: ValueError", "unavailable: 503", "blocked_by_policy", "timeout"]) == "blocked_by_policy"


def test_timeout_outranks_a_single_broken_query() -> None:
    assert worst_error(["error: KeyError", "timeout"]) == "timeout"
    assert worst_error(["unavailable: upstream", "timeout"]) == "timeout"


def test_detail_is_preserved_for_the_reported_error() -> None:
    assert worst_error(["unavailable: blocked by upstream (HTTP 403)"]) == "unavailable: blocked by upstream (HTTP 403)"


def test_unrecognised_error_still_reported() -> None:
    """Never swallow a failure just because it doesn't match a known prefix."""
    assert worst_error(["something new"]) == "something new"


def test_priority_covers_every_error_collect_can_emit() -> None:
    """The metric label is error.split(":")[0], so these prefixes must stay in sync with collect()."""
    assert ERROR_PRIORITY == ("blocked_by_policy", "timeout", "slow source", "unavailable", "error")
