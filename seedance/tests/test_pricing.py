"""The token formula is pinned to ByteDance's own published examples.

If a divisor, a frame size or a rate is ever edited wrongly, these fail — which
is the cheap place to find out.
"""

from __future__ import annotations

import pytest

from seedance.models import JobSpec, Resolution
from seedance.pricing import PricingError, RateTable, UnknownProviderError, UnknownRateError

# BytePlus publishes these for a 5 s 16:9 clip without video input.
PUBLISHED_5S = {
    Resolution.R480P: 0.514,
    Resolution.R720P: 1.156,
    Resolution.R1080P: 2.843,
}


@pytest.mark.parametrize(("resolution", "published"), PUBLISHED_5S.items())
def test_direct_rate_matches_published_examples(
    rates: RateTable, resolution: Resolution, published: float
) -> None:
    spec = JobSpec(prompt="x", resolution=resolution, duration_s=5)
    assert rates.estimate("modelark", spec).usd == pytest.approx(published, abs=0.001)


def test_token_count_is_the_documented_formula(rates: RateTable) -> None:
    spec = JobSpec(prompt="x", resolution=Resolution.R720P, duration_s=5, fps=24)
    # 5 s x 1280 x 720 x 24 / 1024
    assert rates.tokens(spec) == 108_000


def test_reference_video_seconds_count_toward_tokens(rates: RateTable) -> None:
    plain = JobSpec(prompt="x", resolution=Resolution.R720P, duration_s=5)
    with_video = JobSpec(
        prompt="x",
        resolution=Resolution.R720P,
        duration_s=5,
        reference_video="https://example.test/clip.mp4",
        reference_video_s=5,
    )
    assert rates.tokens(with_video) == 2 * rates.tokens(plain)


def test_video_input_uses_the_cheaper_token_rate(rates: RateTable) -> None:
    spec = JobSpec(
        prompt="x",
        resolution=Resolution.R720P,
        duration_s=5,
        reference_video="https://example.test/clip.mp4",
        reference_video_s=1,
    )
    rate = rates.provider("modelark")
    assert rate.token_rate(Resolution.R720P, with_video=True) == 6.40
    assert rates.estimate("modelark", spec).basis == "token"


def test_duration_is_linear(rates: RateTable) -> None:
    """Six 5 s clips and one 30 s clip cost the same, bar token rounding.

    Rounding is per job, so the two differ by a few tokens — fractions of a
    cent. There is no volume discount for generating one long take.
    """
    five = rates.estimate("modelark", JobSpec(prompt="x", duration_s=5)).usd
    thirty = rates.estimate("modelark", JobSpec(prompt="x", duration_s=30)).usd
    assert thirty == pytest.approx(five * 6, abs=0.001)


def test_resolution_is_the_expensive_lever(rates: RateTable) -> None:
    cheap = rates.estimate("modelark", JobSpec(prompt="x", resolution=Resolution.R480P)).usd
    dear = rates.estimate("modelark", JobSpec(prompt="x", resolution=Resolution.R720P)).usd
    assert dear / cheap == pytest.approx(2.25, abs=0.01)


def test_per_second_provider_applies_the_video_multiplier(rates: RateTable) -> None:
    spec = JobSpec(prompt="x", resolution=Resolution.R720P, duration_s=5)
    with_video = spec.with_(reference_video="https://example.test/c.mp4", reference_video_s=3)
    assert rates.estimate("fal", spec).usd == pytest.approx(0.4730 * 5)
    assert rates.estimate("fal", with_video).usd == pytest.approx(0.4730 * 5 * 0.6)


def test_missing_rate_is_an_error_not_a_guess(rates: RateTable) -> None:
    spec = JobSpec(prompt="x", resolution=Resolution.R1080P, duration_s=5)
    with pytest.raises(UnknownRateError, match="will not guess"):
        rates.estimate("wavespeed_turbo", spec)


def test_unknown_provider_lists_what_is_known(rates: RateTable) -> None:
    with pytest.raises(UnknownProviderError, match="modelark"):
        rates.estimate("nope", JobSpec(prompt="x"))


def test_compare_sorts_cheapest_first_and_keeps_the_gaps(rates: RateTable) -> None:
    spec = JobSpec(prompt="x", resolution=Resolution.R720P, duration_s=5)
    rows = rates.compare(spec)
    priced = [(row[0].name, row[1].usd) for row in rows if row[1] is not None]

    assert priced[0][0] == "wavespeed_turbo"
    assert [usd for _, usd in priced] == sorted(usd for _, usd in priced)
    # A provider priced in another currency is reported, not silently dropped.
    assert any(row[0].name == "volcano_ark" and row[2] for row in rows)


def test_compare_can_restrict_to_callable_adapters(rates: RateTable) -> None:
    rows = rates.compare(JobSpec(prompt="x", resolution=Resolution.R720P), adapters_only=True)
    assert {row[0].name for row in rows} == {
        "modelark",
        "replicate",
        "wavespeed",
        "wavespeed_turbo",
    }


def test_frame_sizes_come_from_the_table(rates: RateTable) -> None:
    assert rates.frame(Resolution.R720P).pixels == 1280 * 720
    with pytest.raises(PricingError):
        RateTable(resolutions={}, providers={}).frame(Resolution.R720P)
