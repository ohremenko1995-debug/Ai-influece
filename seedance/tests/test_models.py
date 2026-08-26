from __future__ import annotations

import pytest

from seedance.models import JobSpec, Resolution


def test_fingerprint_is_stable_and_provider_scoped() -> None:
    spec = JobSpec(prompt="a cat", seed=7)
    assert spec.fingerprint("modelark") == JobSpec(prompt="a cat", seed=7).fingerprint("modelark")
    assert spec.fingerprint("modelark") != spec.fingerprint("replicate")


def test_fingerprint_changes_with_anything_that_changes_the_bill() -> None:
    spec = JobSpec(prompt="a cat", seed=7)
    for changed in (
        spec.with_(resolution=Resolution.R720P),
        spec.with_(duration_s=10),
        spec.with_(seed=8),
        spec.with_(prompt="a dog"),
    ):
        assert changed.fingerprint("modelark") != spec.fingerprint("modelark")


def test_audio_defaults_on_because_it_is_free() -> None:
    assert JobSpec(prompt="x").audio is True


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"prompt": "  "}, "prompt is empty"),
        ({"prompt": "x", "duration_s": 0}, "duration"),
        ({"prompt": "x", "duration_s": 31}, "duration"),
        ({"prompt": "x", "fps": 0}, "fps"),
    ],
)
def test_invalid_specs_are_rejected(kwargs: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        JobSpec(**kwargs)  # type: ignore[arg-type]


def test_reference_video_without_duration_would_underprice_the_job() -> None:
    with pytest.raises(ValueError, match="reference_video_s"):
        JobSpec(prompt="x", reference_video="https://example.test/c.mp4")
