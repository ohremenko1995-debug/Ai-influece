"""Shortlisting: relevance traded against novelty."""

from __future__ import annotations

import numpy as np
import pytest

from identitylock.embeddings.base import l2_normalise
from identitylock.selection.selector import select_takes


def _unit(*values: float) -> np.ndarray:
    return l2_normalise(np.asarray(values, dtype=np.float32))


class TestSelectTakes:
    def test_picks_the_best_first(self) -> None:
        vectors = [_unit(1, 0), _unit(0, 1), _unit(1, 1)]
        result = select_takes([0.1, 0.9, 0.5], vectors, k=1)
        assert result.indices == (1,)

    def test_never_exceeds_k(self) -> None:
        vectors = [_unit(1, 0), _unit(0, 1), _unit(1, 1), _unit(-1, 1)]
        assert len(select_takes([1, 2, 3, 4], vectors, k=2)) == 2

    def test_never_exceeds_the_pool(self) -> None:
        assert len(select_takes([1.0], [_unit(1, 0)], k=9)) == 1

    def test_honours_the_acceptance_gate(self) -> None:
        """A rejected take is never shortlisted, however good its score."""
        vectors = [_unit(1, 0), _unit(0, 1)]
        result = select_takes([9.0, 0.1], vectors, k=2, eligible=[False, True])
        assert result.indices == (1,)

    def test_returns_nothing_when_all_are_rejected(self) -> None:
        vectors = [_unit(1, 0), _unit(0, 1)]
        assert select_takes([1.0, 2.0], vectors, k=2, eligible=[False, False]).indices == ()

    def test_zero_k_selects_nothing(self) -> None:
        assert select_takes([1.0], [_unit(1, 0)], k=0).indices == ()

    def test_diversity_beats_a_near_duplicate(self) -> None:
        """Two great near-identical takes plus one decent different take: the
        shortlist should not be the same picture twice."""
        vectors = [_unit(1, 0), _unit(0.999, 0.045), _unit(0, 1)]
        greedy = select_takes([1.0, 0.99, 0.6], vectors, k=2, lambda_=0.5)
        assert greedy.indices == (0, 2)

    def test_lambda_one_ignores_diversity(self) -> None:
        vectors = [_unit(1, 0), _unit(0.999, 0.045), _unit(0, 1)]
        pure = select_takes([1.0, 0.99, 0.6], vectors, k=2, lambda_=1.0)
        assert pure.indices == (0, 1)

    def test_reports_the_diversity_achieved(self) -> None:
        vectors = [_unit(1, 0), _unit(0, 1)]
        assert select_takes([1.0, 1.0], vectors, k=2).mean_distance == pytest.approx(1.0)

    def test_equal_scores_do_not_crash_the_normalisation(self) -> None:
        vectors = [_unit(1, 0), _unit(0, 1), _unit(1, 1)]
        assert len(select_takes([0.5, 0.5, 0.5], vectors, k=2)) == 2

    def test_rejects_mismatched_inputs(self) -> None:
        with pytest.raises(ValueError, match="same length"):
            select_takes([1.0, 2.0], [_unit(1, 0)], k=1)

    def test_rejects_a_lambda_outside_the_unit_interval(self) -> None:
        with pytest.raises(ValueError, match="lambda_"):
            select_takes([1.0], [_unit(1, 0)], k=1, lambda_=1.4)
