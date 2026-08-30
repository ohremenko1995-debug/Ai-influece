"""Deriving thresholds from the reference set instead of inventing them.

A gate written as ``identity >= 0.72`` is only meaningful if somebody can say
where 0.72 came from. Here it comes from the references themselves.

The construction is leave-one-out verification. For each reference image, build
the centroid of the *other* references and score the held-out one against it.
That distribution is what "the same character, measured by this backend" actually
looks like for this character. A generated take is asked to be no less on-model
than the references are to each other — a claim that can be checked, argued with
and re-derived on someone else's data.

The same pass measures whether the cohort is separable at all. If a character's
references score no better against their own centroid than against another
character's, the identity gate is measuring "is this a portrait", not "is this
our portrait", and the calibration says so instead of emitting a number.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from identitylock.domain.policy import Policy
from identitylock.embeddings.base import Vector, cosine, l2_normalise
from identitylock.metrics.aggregate import mean, percentile, std
from identitylock.metrics.identity import ReferenceProfile

IDENTITY_SLACK = 0.05
"""How far below the reference floor a generated take may sit before rejection."""

MARGIN_FRACTION = 0.30
"""Fraction of the observed own-vs-impostor separation demanded as margin."""

MIN_REFERENCES = 4
"""Below this, leave-one-out estimates are too noisy to calibrate from."""

TARGET_FAR = 0.02
"""Default operating point: accept at most 2% of impostor frames.

Chosen, not inherited. On the bundled cohort a 1% target costs roughly 17% of
genuine frames and a 5% target buys back only a little; 2% sits at the knee. The
right value is a business decision — how expensive is an off-model frame reaching
a feed versus a good frame being re-rendered — and the sweep to re-derive it is
one command."""

CONSISTENCY_SLACK = 0.05
"""Headroom between the observed genuine pass rate and the batch gate."""


@dataclass(frozen=True, slots=True)
class CharacterCalibration:
    """What the references say about one character."""

    character_id: str
    n_references: int
    coherence: float
    loo_mean: float
    loo_std: float
    loo_p05: float
    loo_min: float
    impostor_max: float
    impostor_id: str | None
    separation: float

    @property
    def separable(self) -> bool:
        return self.separation > 0.0


@dataclass(frozen=True, slots=True)
class Calibration:
    """Per-character calibration plus the policy it implies."""

    characters: tuple[CharacterCalibration, ...]
    suggested: Policy
    warnings: tuple[str, ...]

    def table(self) -> list[dict[str, float | str | int | None]]:
        return [
            {
                "character": item.character_id,
                "references": item.n_references,
                "coherence": round(item.coherence, 4),
                "loo_mean": round(item.loo_mean, 4),
                "loo_p05": round(item.loo_p05, 4),
                "impostor_max": round(item.impostor_max, 4),
                "impostor": item.impostor_id,
                "separation": round(item.separation, 4),
            }
            for item in self.characters
        ]


def leave_one_out(profile: ReferenceProfile) -> tuple[float, ...]:
    """Each reference scored against the centroid of the others.

    Scoring a reference against a centroid it helped build inflates the number —
    that is the leak this function exists to avoid.
    """
    count = profile.size
    if count < 2:
        return ()
    stacked = np.stack(profile.vectors)
    total = stacked.sum(axis=0)
    scores: list[float] = []
    for index in range(count):
        others = l2_normalise(((total - stacked[index]) / (count - 1)).astype(np.float32))
        scores.append(cosine(stacked[index], others))
    return tuple(scores)


def calibrate(profiles: Sequence[ReferenceProfile], *, base: Policy | None = None) -> Calibration:
    """Derive a policy from a cohort of reference profiles."""
    if not profiles:
        raise ValueError("calibration needs at least one reference profile")

    per_character: list[CharacterCalibration] = []
    warnings: list[str] = []
    pooled_loo: list[float] = []

    for profile in profiles:
        scores = leave_one_out(profile)
        others = [item for item in profiles if item.character_id != profile.character_id]
        impostor_scores = [
            (max(cosine(vector, other.centroid) for vector in profile.vectors), other.character_id)
            for other in others
        ]
        impostor_max, impostor_id = (
            max(impostor_scores, key=lambda item: item[0]) if impostor_scores else (0.0, None)
        )

        loo_mean = mean(scores) if scores else 1.0
        calibration = CharacterCalibration(
            character_id=profile.character_id,
            n_references=profile.size,
            coherence=profile.coherence,
            loo_mean=loo_mean,
            loo_std=std(scores) if scores else 0.0,
            loo_p05=percentile(scores, 5.0) if scores else 1.0,
            loo_min=min(scores) if scores else 1.0,
            impostor_max=impostor_max,
            impostor_id=impostor_id,
            separation=loo_mean - impostor_max,
        )
        per_character.append(calibration)
        pooled_loo.extend(scores)

        if profile.size < MIN_REFERENCES:
            warnings.append(
                f"{profile.character_id}: only {profile.size} reference image(s); "
                f"leave-one-out needs at least {MIN_REFERENCES} to be stable."
            )
        if profile.coherence < 0.15:
            warnings.append(
                f"{profile.character_id}: reference coherence {profile.coherence:.3f} is low — "
                "the references may not agree on one look, which makes the centroid meaningless."
            )
        if others and not calibration.separable:
            warnings.append(
                f"{profile.character_id}: not separable from '{impostor_id}' "
                f"(own {loo_mean:.3f} vs impostor {impostor_max:.3f}). "
                "The identity gate would not be measuring identity with this backend."
            )

    if len(profiles) < 2:
        warnings.append(
            "Cohort of one: no impostor margin can be computed, so the margin gate is skipped. "
            "Add other characters' reference sets to make identity claims falsifiable."
        )

    floor = percentile(pooled_loo, 5.0) if pooled_loo else 0.0
    separations = [item.separation for item in per_character if item.impostor_id is not None]
    median_separation = float(np.median(separations)) if separations else 0.0

    template = base or Policy()
    suggested = template.model_copy(
        update={
            "identity_min": round(max(-1.0, floor - IDENTITY_SLACK), 4),
            "identity_p05_min": round(max(-1.0, floor - 2 * IDENTITY_SLACK), 4),
            "margin_min": round(max(0.02, MARGIN_FRACTION * median_separation), 4),
        }
    )
    return Calibration(
        characters=tuple(per_character), suggested=suggested, warnings=tuple(warnings)
    )


# --------------------------------------------------------------------------- #
# Verification calibration
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class VerificationCurve:
    """Genuine-versus-impostor score distributions and the curve they trace.

    This is the calibration that survives contact with production. Reference
    leave-one-out says how tight the golden set is; it does *not* say where to put
    a threshold, because production frames differ from reference frames in every
    way except the character — background, light, framing, crop. Scoring a labelled
    validation set and reading the threshold off the ROC curve is the standard
    face-verification answer to that problem, and it is the one used here.

    ``genuine`` holds scores of frames against their own character's centroid,
    ``impostor`` scores of the same frames against every other centroid.
    """

    genuine: tuple[float, ...]
    impostor: tuple[float, ...]
    auc: float
    eer: float
    eer_threshold: float

    def rates_at(self, threshold: float) -> tuple[float, float]:
        """``(false accept rate, false reject rate)`` at a threshold."""
        far = float(np.mean(np.asarray(self.impostor) >= threshold)) if self.impostor else 0.0
        frr = float(np.mean(np.asarray(self.genuine) < threshold)) if self.genuine else 0.0
        return (far, frr)

    def threshold_at_far(self, target: float) -> float:
        """Lowest threshold whose false-accept rate is at most ``target``.

        Lowest, not any: raising the threshold further only rejects more genuine
        frames for no gain in security, and the operating point should be the
        cheapest one that meets the requirement.
        """
        if not self.impostor:
            return float(np.min(self.genuine)) if self.genuine else 0.0
        impostors = np.sort(np.asarray(self.impostor, dtype=np.float64))
        allowed = int(np.floor(target * impostors.size))
        if allowed >= impostors.size:
            return float(impostors[0])
        index = impostors.size - allowed - 1
        return float(np.nextafter(impostors[index], np.inf))


def verification_curve(genuine: Sequence[float], impostor: Sequence[float]) -> VerificationCurve:
    """Build the curve from two score sets.

    AUC is computed from the Mann-Whitney U statistic — the rank-based identity
    ``AUC = P(genuine > impostor) + 0.5 * P(tie)`` — which is exact and needs no
    threshold sweep. EER is found by sweeping every observed score, which is
    O(n log n) and avoids the interpolation error of a coarse grid.
    """
    genuine_array = np.asarray(list(genuine), dtype=np.float64)
    impostor_array = np.asarray(list(impostor), dtype=np.float64)
    if genuine_array.size == 0 or impostor_array.size == 0:
        return VerificationCurve(
            genuine=tuple(float(value) for value in genuine_array),
            impostor=tuple(float(value) for value in impostor_array),
            auc=0.5,
            eer=0.5,
            eer_threshold=0.0,
        )

    pooled = np.concatenate([genuine_array, impostor_array])
    order = np.argsort(pooled, kind="stable")
    ranks = np.empty(pooled.size, dtype=np.float64)
    ranks[order] = np.arange(1, pooled.size + 1, dtype=np.float64)
    # Average ranks within ties so a tie contributes 0.5, not 1.0.
    unique, inverse, counts = np.unique(pooled, return_inverse=True, return_counts=True)
    if np.any(counts > 1):
        sums = np.zeros(unique.size, dtype=np.float64)
        np.add.at(sums, inverse, ranks)
        ranks = (sums / counts)[inverse]
    rank_sum = float(np.sum(ranks[: genuine_array.size]))
    u_statistic = rank_sum - genuine_array.size * (genuine_array.size + 1) / 2.0
    auc = float(u_statistic / (genuine_array.size * impostor_array.size))

    observed = np.unique(pooled)
    # Candidates include a point just above each observed score. With ties in the
    # score sets the FAR curve is a step function and no threshold makes FAR equal
    # FRR exactly, so EER is defined as min over thresholds of max(FAR, FRR) —
    # the standard treatment for a discontinuous DET curve.
    thresholds = np.unique(np.concatenate([observed, np.nextafter(observed, np.inf)]))
    best = np.inf
    eer = 0.5
    eer_threshold = float(thresholds[0])
    for threshold in thresholds:
        far = float(np.mean(impostor_array >= threshold))
        frr = float(np.mean(genuine_array < threshold))
        worst = max(far, frr)
        if worst < best:
            best = worst
            eer = worst
            eer_threshold = float(threshold)

    return VerificationCurve(
        genuine=tuple(float(value) for value in genuine_array),
        impostor=tuple(float(value) for value in impostor_array),
        auc=round(auc, 6),
        # Capped at 0.5: when the two distributions coincide exactly, no fixed
        # threshold can do better than always being wrong one way, but a coin flip
        # achieves 0.5 — reporting 1.0 would overstate the failure.
        eer=round(min(eer, 0.5), 6),
        eer_threshold=round(eer_threshold, 6),
    )


@dataclass(frozen=True, slots=True)
class ValidationScores:
    """Everything a labelled validation set tells us, kept together."""

    curve: VerificationCurve
    margins: tuple[float, ...]
    per_character: dict[str, tuple[float, ...]]
    """Genuine scores in render order, so drift can be measured on known-good frames."""


def score_validation(
    profiles: Sequence[ReferenceProfile],
    validation: Mapping[str, Sequence[Vector]],
) -> ValidationScores:
    """Score a labelled validation set against the cohort.

    Returns the verification curve and the list of genuine *margins* (own score
    minus best impostor score), which is what the margin gate is calibrated on.
    The validation frames must come from seeds the evaluated suite does not use —
    a threshold fitted on the frames it will later judge is not a threshold, it is
    a memory.
    """
    by_id = {profile.character_id: profile for profile in profiles}
    unknown = set(validation) - set(by_id)
    if unknown:
        raise ValueError(f"validation set names characters with no profile: {sorted(unknown)}")

    genuine: list[float] = []
    impostor: list[float] = []
    margins: list[float] = []
    per_character: dict[str, tuple[float, ...]] = {}

    for character_id, vectors in validation.items():
        own = by_id[character_id]
        others = [profile for profile in profiles if profile.character_id != character_id]
        series: list[float] = []
        for vector in vectors:
            own_score = cosine(vector, own.centroid)
            genuine.append(own_score)
            series.append(own_score)
            other_scores = [cosine(vector, profile.centroid) for profile in others]
            impostor.extend(other_scores)
            if other_scores:
                margins.append(own_score - max(other_scores))
        per_character[character_id] = tuple(series)

    return ValidationScores(
        curve=verification_curve(genuine, impostor),
        margins=tuple(margins),
        per_character=per_character,
    )


def calibrate_from_validation(
    profiles: Sequence[ReferenceProfile],
    validation: Mapping[str, Sequence[Vector]],
    *,
    target_far: float = TARGET_FAR,
    base: Policy | None = None,
) -> tuple[Calibration, VerificationCurve]:
    """Derive a policy from a labelled validation set instead of the references.

    The identity threshold is read off the ROC curve at ``target_far``; the margin
    threshold is the 5th percentile of genuine margins, floored at 0.02 so it stays
    a real constraint. The run-level p05 floor is set one slack below the candidate
    threshold, because a batch is allowed to have a worst frame near the gate
    without the whole batch failing.

    ``drift_abs_max`` and ``diversity_min`` are deliberately *not* derived here.
    Drift is tested for significance against a permutation null computed on the
    batch itself, so it needs a practical limit rather than a fitted one, and
    diversity is a content-space quantity this identity-space calibration has no
    view of. Both are stated in the suite file where a human can argue with them.
    """
    reference_calibration = calibrate(profiles, base=base)
    scores = score_validation(profiles, validation)
    curve = scores.curve

    threshold = curve.threshold_at_far(target_far)
    far, frr = curve.rates_at(threshold)
    margin_floor = max(0.02, percentile(scores.margins, 5.0)) if scores.margins else 0.02

    # The batch gate cannot demand a pass rate the descriptor does not reach on
    # known-good frames: at FAR `target_far` it rejects `frr` of genuine frames, so
    # anything above 1 - frr would fail a perfect generator.
    consistency_floor = float(np.clip(1.0 - frr - CONSISTENCY_SLACK, 0.50, 0.95))

    suggested = (base or Policy()).model_copy(
        update={
            "identity_min": round(threshold, 4),
            "identity_p05_min": round(threshold - IDENTITY_SLACK, 4),
            "margin_min": round(margin_floor, 4),
            "consistency_rate_min": round(consistency_floor, 4),
        }
    )

    warnings = list(reference_calibration.warnings)
    if curve.auc < 0.90:
        warnings.append(
            f"Verification AUC is {curve.auc:.3f}. Below ~0.9 the descriptor is barely "
            "separating these characters; the identity gate will reject good frames and "
            "accept bad ones roughly at random. Use a learned embedder."
        )
    if frr > 0.25:
        warnings.append(
            f"At FAR {far:.1%} the false-reject rate is {frr:.1%} — a quarter of genuine "
            "frames would be rejected. Either loosen target_far or improve the descriptor."
        )
    if scores.margins and min(scores.margins) <= 0.0:
        below = sum(1 for value in scores.margins if value <= 0.0)
        warnings.append(
            f"{below}/{len(scores.margins)} validation frames sit closer to another character "
            "than to their own. Those are descriptor failures, not generation failures."
        )

    return (
        Calibration(
            characters=reference_calibration.characters,
            suggested=suggested,
            warnings=tuple(warnings),
        ),
        curve,
    )
