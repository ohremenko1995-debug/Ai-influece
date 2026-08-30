"""Measurement. Takes vectors and frames in, gives numbers out; decides nothing."""

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
    Calibration,
    CharacterCalibration,
    ValidationScores,
    VerificationCurve,
    calibrate,
    calibrate_from_validation,
    leave_one_out,
    score_validation,
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
    drift,
    impostor_margin,
    mean_pairwise_cosine,
    nearest_reference,
    similarity,
)
from identitylock.metrics.space import IdentitySpace

__all__ = [
    "Calibration",
    "CharacterCalibration",
    "IdentitySpace",
    "ReferenceProfile",
    "ValidationScores",
    "VerificationCurve",
    "bootstrap_ci",
    "build_profile",
    "calibrate",
    "calibrate_from_validation",
    "cliffs_delta",
    "distance_matrix",
    "drift",
    "duplicate_pairs",
    "impostor_margin",
    "leave_one_out",
    "linear_trend",
    "mean",
    "mean_pairwise_cosine",
    "mean_pairwise_distance",
    "nearest_reference",
    "percentile",
    "rank_biserial",
    "score_validation",
    "similarity",
    "std",
    "stratified_drift",
    "verification_curve",
    "win_rate",
]
