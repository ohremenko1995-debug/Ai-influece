"""Statistics and identity measurement, checked against analytic answers."""

from __future__ import annotations

from typing import ClassVar

import numpy as np
import pytest

from identitylock.embeddings.base import l2_normalise
from identitylock.metrics.aggregate import (
    bootstrap_ci,
    cliffs_delta,
    linear_trend,
    mean,
    percentile,
    rank_biserial,
    std,
    stratified_drift,
    win_rate,
)
from identitylock.metrics.calibration import (
    calibrate,
    calibrate_from_validation,
    leave_one_out,
    verification_curve,
)
from identitylock.metrics.diversity import (
    distance_matrix,
    duplicate_pairs,
    mean_pairwise_distance,
)
from identitylock.metrics.identity import (
    ReferenceProfile,
    build_profile,
    impostor_margin,
    mean_pairwise_cosine,
    nearest_reference,
    similarity,
)
from identitylock.metrics.space import IdentitySpace


def _cluster(centre: np.ndarray, count: int, spread: float, seed: int) -> list[np.ndarray]:
    rng = np.random.default_rng(seed)
    return [
        l2_normalise((centre + rng.normal(0, spread, size=centre.size)).astype(np.float32))
        for _ in range(count)
    ]


class TestBasicStatistics:
    def test_mean_and_std(self) -> None:
        assert mean([1, 2, 3]) == 2.0
        assert std([1, 2, 3]) == pytest.approx(1.0)

    def test_empty_inputs_are_zero_not_nan(self) -> None:
        assert mean([]) == 0.0
        assert std([]) == 0.0
        assert percentile([], 5) == 0.0

    def test_std_of_a_single_value_is_zero(self) -> None:
        assert std([4.2]) == 0.0

    def test_percentile_interpolates(self) -> None:
        assert percentile([0, 10], 50) == pytest.approx(5.0)


class TestBootstrap:
    def test_is_deterministic_given_a_seed(self) -> None:
        values = [0.1, 0.4, 0.2, 0.9, 0.5]
        assert bootstrap_ci(values, seed=7) == bootstrap_ci(values, seed=7)

    def test_a_constant_sample_has_a_degenerate_interval(self) -> None:
        assert bootstrap_ci([0.5] * 12) == (0.5, 0.5)

    def test_brackets_the_mean(self) -> None:
        rng = np.random.default_rng(1)
        values = list(rng.normal(0.5, 0.1, size=60))
        low, high = bootstrap_ci(values)
        assert low < mean(values) < high

    def test_a_wider_level_gives_a_wider_interval(self) -> None:
        rng = np.random.default_rng(2)
        values = list(rng.normal(0.5, 0.2, size=40))
        narrow = bootstrap_ci(values, level=0.80)
        wide = bootstrap_ci(values, level=0.99)
        assert (wide[1] - wide[0]) > (narrow[1] - narrow[0])

    def test_single_observation_degenerates_cleanly(self) -> None:
        assert bootstrap_ci([0.3]) == (0.3, 0.3)


class TestEffectSizes:
    def test_win_rate_counts_ties_as_half(self) -> None:
        assert win_rate([1.0, -1.0, 0.0, 0.0]) == 0.5

    def test_win_rate_of_an_empty_set_is_zero(self) -> None:
        assert win_rate([]) == 0.0

    def test_rank_biserial_is_bounded_and_signed(self) -> None:
        assert rank_biserial([1.0, 2.0, 3.0]) == pytest.approx(1.0)
        assert rank_biserial([-1.0, -2.0, -3.0]) == pytest.approx(-1.0)
        assert rank_biserial([0.0, 0.0]) == 0.0

    def test_rank_biserial_ignores_zero_differences(self) -> None:
        assert rank_biserial([1.0, 2.0, 0.0]) == rank_biserial([1.0, 2.0])

    def test_cliffs_delta_detects_full_dominance(self) -> None:
        assert cliffs_delta([1, 2, 3], [4, 5, 6]) == 1.0
        assert cliffs_delta([4, 5, 6], [1, 2, 3]) == -1.0
        assert cliffs_delta([], [1]) == 0.0


class TestLinearTrend:
    def test_recovers_a_known_slope(self) -> None:
        slope, r_squared = linear_trend([0, 1, 2, 3, 4], per=1)
        assert slope == pytest.approx(1.0)
        assert r_squared == pytest.approx(1.0)

    def test_scales_by_the_step_size(self) -> None:
        assert linear_trend([0, 1, 2, 3, 4], per=10)[0] == pytest.approx(10.0)

    def test_a_flat_series_has_no_trend(self) -> None:
        assert linear_trend([2.0] * 8) == (0.0, 0.0)

    def test_too_few_points_is_not_a_trend(self) -> None:
        assert linear_trend([1.0]) == (0.0, 0.0)


class TestStratifiedDrift:
    """The confound this project exists to avoid measuring."""

    GROUPS: ClassVar[list[str]] = [prompt for _ in range(6) for prompt in "ABCD"]

    def test_prompt_difficulty_alone_is_not_drift(self) -> None:
        hard = {"A": 0.0, "B": 0.0, "C": 0.0, "D": -0.3}
        values = [0.5 + hard[group] for group in self.GROUPS]
        slope, _, p_value = stratified_drift(values, self.GROUPS)
        assert slope == pytest.approx(0.0, abs=1e-9)
        assert p_value > 0.5

    def test_real_drift_survives_the_correction(self) -> None:
        hard = {"A": 0.0, "B": 0.0, "C": 0.0, "D": -0.3}
        values = [0.5 + hard[g] - 0.01 * i for i, g in enumerate(self.GROUPS)]
        slope, r_squared, p_value = stratified_drift(values, self.GROUPS)
        assert slope < -0.05
        assert r_squared > 0.9
        assert p_value < 0.01

    def test_noise_is_not_significant(self) -> None:
        rng = np.random.default_rng(4)
        _, _, p_value = stratified_drift(list(rng.random(24)), self.GROUPS)
        assert p_value > 0.05

    def test_is_deterministic(self) -> None:
        values = [0.5 - 0.01 * i for i in range(24)]
        assert stratified_drift(values, self.GROUPS) == stratified_drift(values, self.GROUPS)

    def test_works_without_groups(self) -> None:
        slope, _, p_value = stratified_drift([1.0, 0.9, 0.8, 0.7, 0.6, 0.5])
        assert slope < 0
        assert p_value < 0.1

    def test_rejects_mismatched_groups(self) -> None:
        with pytest.raises(ValueError, match="same length"):
            stratified_drift([1.0, 2.0, 3.0], ["a", "b"])

    def test_too_few_points_is_inert(self) -> None:
        assert stratified_drift([1.0, 2.0]) == (0.0, 0.0, 1.0)


class TestIdentitySpace:
    def test_centring_spreads_similarities_out(self) -> None:
        """Raw histogram descriptors all look alike; centring is what fixes that."""
        base = np.abs(np.random.default_rng(9).normal(size=32)).astype(np.float32) + 1.0
        left = l2_normalise(base + np.array([0.3] + [0.0] * 31, dtype=np.float32))
        right = l2_normalise(base + np.array([0.0, 0.3] + [0.0] * 30, dtype=np.float32))
        raw = float(np.dot(left, right))
        space = IdentitySpace.fit([left, right])
        centred = float(np.dot(space.project(left), space.project(right)))
        assert centred < raw

    def test_the_unit_space_is_a_no_op(self) -> None:
        vector = l2_normalise(np.array([1.0, 2.0, 3.0], dtype=np.float32))
        assert np.allclose(IdentitySpace.unit(3).project(vector), vector)

    def test_fingerprints_differ_between_fits(self) -> None:
        first = IdentitySpace.fit([np.array([1.0, 0.0], dtype=np.float32)])
        second = IdentitySpace.fit([np.array([0.0, 1.0], dtype=np.float32)])
        assert first.fingerprint() != second.fingerprint()

    def test_refuses_to_fit_on_nothing(self) -> None:
        with pytest.raises(ValueError, match="zero vectors"):
            IdentitySpace.fit([])


class TestReferenceProfile:
    def test_coherence_is_higher_for_a_tighter_set(self) -> None:
        centre = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
        tight = build_profile("c", _cluster(centre, 6, 0.05, 1))
        loose = build_profile("c", _cluster(centre, 6, 0.8, 1))
        assert tight.coherence > loose.coherence

    def test_a_single_reference_is_trivially_coherent(self) -> None:
        assert mean_pairwise_cosine([np.array([1.0, 0.0], dtype=np.float32)]) == 1.0

    def test_refuses_an_empty_reference_set(self) -> None:
        with pytest.raises(ValueError, match="no reference images"):
            build_profile("c", [])

    def test_nearest_reference_is_at_least_the_centroid_score(self) -> None:
        profile = build_profile(
            "c", _cluster(np.array([1.0, 0.2, 0.0], dtype=np.float32), 5, 0.2, 3)
        )
        probe = profile.vectors[0]
        assert nearest_reference(probe, profile) >= similarity(probe, profile) - 1e-6


class TestImpostorMargin:
    def test_is_positive_for_the_right_character(self) -> None:
        alpha = build_profile(
            "alpha", _cluster(np.array([1.0, 0.0, 0.0], dtype=np.float32), 5, 0.05, 1)
        )
        beta = build_profile(
            "beta", _cluster(np.array([0.0, 1.0, 0.0], dtype=np.float32), 5, 0.05, 2)
        )
        margin, best, who = impostor_margin(alpha.vectors[0], alpha, [alpha, beta])
        assert margin is not None and margin > 0
        assert who == "beta"
        assert best is not None

    def test_is_negative_when_the_frame_belongs_to_someone_else(self) -> None:
        alpha = build_profile(
            "alpha", _cluster(np.array([1.0, 0.0, 0.0], dtype=np.float32), 5, 0.05, 1)
        )
        beta = build_profile(
            "beta", _cluster(np.array([0.0, 1.0, 0.0], dtype=np.float32), 5, 0.05, 2)
        )
        margin, _, _ = impostor_margin(beta.vectors[0], alpha, [alpha, beta])
        assert margin is not None and margin < 0

    def test_a_cohort_of_one_has_no_margin(self) -> None:
        alpha = build_profile("alpha", _cluster(np.array([1.0, 0.0], dtype=np.float32), 4, 0.05, 1))
        assert impostor_margin(alpha.vectors[0], alpha, [alpha]) == (None, None, None)


class TestDiversity:
    def test_identical_vectors_have_no_diversity(self) -> None:
        vector = l2_normalise(np.array([1.0, 1.0], dtype=np.float32))
        assert mean_pairwise_distance([vector, vector, vector]) == pytest.approx(0.0, abs=1e-6)

    def test_orthogonal_vectors_are_maximally_apart(self) -> None:
        left = np.array([1.0, 0.0], dtype=np.float32)
        right = np.array([0.0, 1.0], dtype=np.float32)
        assert mean_pairwise_distance([left, right]) == pytest.approx(1.0)

    def test_fewer_than_two_vectors_is_zero(self) -> None:
        assert mean_pairwise_distance([np.array([1.0], dtype=np.float32)]) == 0.0

    def test_the_matrix_has_a_zero_diagonal(self) -> None:
        vectors = _cluster(np.array([1.0, 0.0, 0.0], dtype=np.float32), 4, 0.1, 5)
        matrix = distance_matrix(vectors)
        assert np.allclose(np.diag(matrix), 0.0, atol=1e-6)

    def test_finds_near_duplicates(self) -> None:
        vector = l2_normalise(np.array([1.0, 0.5], dtype=np.float32))
        other = l2_normalise(np.array([0.0, 1.0], dtype=np.float32))
        assert duplicate_pairs([vector, vector, other]) == ((0, 1),)


class TestVerificationCurve:
    def test_separable_scores_give_a_perfect_curve(self) -> None:
        curve = verification_curve([0.9, 0.8, 0.85], [0.1, 0.2, 0.15])
        assert curve.auc == 1.0
        assert curve.eer == 0.0

    def test_identical_distributions_are_chance(self) -> None:
        curve = verification_curve([0.5, 0.6, 0.4], [0.5, 0.6, 0.4])
        assert curve.auc == pytest.approx(0.5)
        assert curve.eer <= 0.5

    def test_the_threshold_meets_the_target_far(self) -> None:
        rng = np.random.default_rng(6)
        genuine = list(rng.normal(0.8, 0.05, size=200))
        impostor = list(rng.normal(0.2, 0.05, size=200))
        curve = verification_curve(genuine, impostor)
        threshold = curve.threshold_at_far(0.01)
        far, _ = curve.rates_at(threshold)
        assert far <= 0.01

    def test_empty_inputs_do_not_crash(self) -> None:
        curve = verification_curve([], [])
        assert curve.auc == 0.5


class TestCalibration:
    def _profiles(self) -> list[ReferenceProfile]:
        return [
            build_profile(
                "alpha", _cluster(np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32), 8, 0.15, 1)
            ),
            build_profile(
                "beta", _cluster(np.array([0.0, 1.0, 0.0, 0.0], dtype=np.float32), 8, 0.15, 2)
            ),
        ]

    def test_leave_one_out_never_scores_against_itself(self) -> None:
        profile = self._profiles()[0]
        scores = leave_one_out(profile)
        assert len(scores) == profile.size
        assert all(score < 1.0 for score in scores)

    def test_a_lone_reference_yields_no_scores(self) -> None:
        profile = build_profile("solo", [np.array([1.0, 0.0], dtype=np.float32)])
        assert leave_one_out(profile) == ()

    def test_warns_about_a_cohort_of_one(self) -> None:
        calibration = calibrate(self._profiles()[:1])
        assert any("Cohort of one" in warning for warning in calibration.warnings)

    def test_warns_about_a_thin_reference_set(self) -> None:
        thin = build_profile("thin", _cluster(np.array([1.0, 0.0], dtype=np.float32), 2, 0.05, 1))
        assert any("reference image" in w for w in calibrate([thin]).warnings)

    def test_warns_when_characters_are_not_separable(self) -> None:
        centre = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        overlapping = [
            build_profile("alpha", _cluster(centre, 6, 0.3, 1)),
            build_profile("beta", _cluster(centre, 6, 0.3, 2)),
        ]
        assert any("not separable" in w for w in calibrate(overlapping).warnings)

    def test_validation_calibration_produces_a_usable_policy(self) -> None:
        profiles = self._profiles()
        validation = {
            "alpha": _cluster(np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32), 10, 0.2, 11),
            "beta": _cluster(np.array([0.0, 1.0, 0.0, 0.0], dtype=np.float32), 10, 0.2, 12),
        }
        calibration, curve = calibrate_from_validation(profiles, validation)
        assert curve.auc > 0.9
        assert -1.0 <= calibration.suggested.identity_min <= 1.0
        assert calibration.suggested.margin_min >= 0.02
        assert 0.5 <= calibration.suggested.consistency_rate_min <= 0.95

    def test_a_tighter_far_target_raises_the_threshold(self) -> None:
        profiles = self._profiles()
        validation = {
            "alpha": _cluster(np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32), 20, 0.25, 11),
            "beta": _cluster(np.array([0.0, 1.0, 0.0, 0.0], dtype=np.float32), 20, 0.25, 12),
        }
        strict, _ = calibrate_from_validation(profiles, validation, target_far=0.01)
        loose, _ = calibrate_from_validation(profiles, validation, target_far=0.20)
        assert strict.suggested.identity_min >= loose.suggested.identity_min

    def test_rejects_validation_for_an_unknown_character(self) -> None:
        with pytest.raises(ValueError, match="no profile"):
            calibrate_from_validation(self._profiles(), {"ghost": []})
