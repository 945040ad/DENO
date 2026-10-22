"""A founder's quality settings are validated where they enter, not silently ignored later.

The contract suite found PATCH /me storing `{"x-schemathesis-additional": 0.0}` in
profiles.quality_weights: any key was accepted, and a JSON `false` became weight 0.0.
"""

import pytest
from pydantic import ValidationError

from deno_api.v1.schemas import MeUpdate, QualityWeights
from deno_gates.quality import DIMENSION_WEIGHTS


def test_api_dimensions_match_the_scorer() -> None:
    """If a dimension is added to the scorer, founders must be able to weight it too."""
    assert set(QualityWeights.__annotations__) == set(DIMENSION_WEIGHTS)


@pytest.mark.parametrize(
    "weights",
    [{"hook_strength": 2}, {"hook_strength": 2.5, "readability": 0}, {"originality": 3.0}, {}],
)
def test_valid_weights_are_accepted_as_partial_updates(weights: dict[str, float]) -> None:
    dumped = MeUpdate(quality_weights=weights).model_dump(exclude_unset=True)  # type: ignore[arg-type]
    assert dumped["quality_weights"] == {k: float(v) for k, v in weights.items()}


@pytest.mark.parametrize(
    ("weights", "error"),
    [
        ({"x-schemathesis-additional": 1.0}, "extra_forbidden"),
        ({"hook_strength": False}, "float_type"),  # was silently stored as 0.0
        ({"hook_strength": "2"}, "float_type"),
        ({"hook_strength": 3.5}, "less_than_equal"),
        ({"hook_strength": -1}, "greater_than_equal"),
    ],
)
def test_invalid_weights_are_rejected(weights: dict[str, object], error: str) -> None:
    with pytest.raises(ValidationError) as exc:
        MeUpdate(quality_weights=weights)  # type: ignore[arg-type]
    assert exc.value.errors()[0]["type"] == error


@pytest.mark.parametrize("threshold", [4, 10, True])
def test_threshold_outside_the_clamp_is_rejected(threshold: object) -> None:
    with pytest.raises(ValidationError):
        MeUpdate(quality_threshold=threshold)  # type: ignore[arg-type]
