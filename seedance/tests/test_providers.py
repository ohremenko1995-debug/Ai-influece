"""Adapter wire formats.

Egress was blocked while these were written, so the payload shapes come from
published docs rather than live calls. These tests pin the shape this code
believes in — when a provider's docs disagree, the fix is one adapter and one
test, not a hunt through the pipeline.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from seedance.config import Settings, isolated_settings
from seedance.models import JobSpec, JobStatus, Resolution
from seedance.providers import (
    FatalProviderError,
    MissingCredentialError,
    RetryableProviderError,
    UnknownAdapterError,
    get_provider,
)
from seedance.providers.modelark import ModelArkProvider
from seedance.providers.replicate import ReplicateProvider
from seedance.providers.wavespeed import WaveSpeedProvider, WaveSpeedTurboProvider


def test_registry_rejects_a_provider_with_no_adapter(settings: Settings) -> None:
    with pytest.raises(UnknownAdapterError, match="comparison only"):
        get_provider("fal", settings)


# ---------------------------------------------------------------------------
# ModelArk
# ---------------------------------------------------------------------------
def test_modelark_puts_parameters_in_the_prompt_as_commands(settings: Settings) -> None:
    spec = JobSpec(prompt="a slow push-in", resolution=Resolution.R720P, duration_s=8, seed=42)
    request = ModelArkProvider(settings).prepare_submit(spec)

    assert request.url.endswith("/contents/generations/tasks")
    assert request.json is not None
    text = request.json["content"][0]["text"]
    assert text.startswith("a slow push-in ")
    assert "--resolution 720p" in text
    assert "--duration 8" in text
    assert "--seed 42" in text
    assert "--watermark false" in text


def test_modelark_attaches_first_frame_and_references_with_roles(settings: Settings) -> None:
    spec = JobSpec(
        prompt="x",
        image_url="https://example.test/first.png",
        reference_images=("https://example.test/a.png", "https://example.test/b.png"),
    )
    content = ModelArkProvider(settings).prepare_submit(spec).json["content"]  # type: ignore[index]
    roles = [part.get("role") for part in content[1:]]
    assert roles == ["first_frame", "reference_image", "reference_image"]


def test_modelark_reports_the_tokens_it_charged(settings: Settings) -> None:
    status = ModelArkProvider(settings).parse_poll(
        {
            "status": "succeeded",
            "content": {"video_url": "https://cdn.example.test/v.mp4"},
            "usage": {"completion_tokens": 108000},
        }
    )
    assert status.status is JobStatus.SUCCEEDED
    assert status.tokens == 108000
    assert status.video_url == "https://cdn.example.test/v.mp4"


def test_modelark_surfaces_the_failure_message(settings: Settings) -> None:
    status = ModelArkProvider(settings).parse_poll(
        {"status": "failed", "error": {"message": "prompt rejected"}}
    )
    assert status.status is JobStatus.FAILED
    assert status.error == "prompt rejected"


def test_missing_credentials_fail_before_the_request() -> None:
    bare = isolated_settings(modelark_api_key="")
    with pytest.raises(MissingCredentialError, match="ARK_API_KEY"):
        ModelArkProvider(bare).prepare_submit(JobSpec(prompt="x"))


def test_credentials_are_masked_when_a_request_is_shown(settings: Settings) -> None:
    request = ModelArkProvider(settings).prepare_submit(JobSpec(prompt="x"))
    assert settings.modelark_api_key in request.headers["Authorization"]
    assert request.redacted().headers["Authorization"] == "***"


# ---------------------------------------------------------------------------
# Replicate
# ---------------------------------------------------------------------------
def test_replicate_sends_a_typed_input_object(settings: Settings) -> None:
    spec = JobSpec(prompt="x", resolution=Resolution.R720P, duration_s=5, seed=3)
    request = ReplicateProvider(settings).prepare_submit(spec)
    assert request.json == {
        "input": {
            "prompt": "x",
            "resolution": "720p",
            "duration": 5,
            "aspect_ratio": "16:9",
            "fps": 24,
            "audio": True,
            "camera_fixed": False,
            "seed": 3,
        }
    }


@pytest.mark.parametrize(
    "output",
    ["https://cdn.example.test/v.mp4", ["https://cdn.example.test/v.mp4"]],
)
def test_replicate_accepts_either_output_shape(settings: Settings, output: object) -> None:
    status = ReplicateProvider(settings).parse_poll({"status": "succeeded", "output": output})
    assert status.video_url == "https://cdn.example.test/v.mp4"


# ---------------------------------------------------------------------------
# WaveSpeed
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("spec", "endpoint"),
    [
        (JobSpec(prompt="x"), "text-to-video"),
        (JobSpec(prompt="x", image_url="https://example.test/a.png"), "image-to-video"),
        (
            JobSpec(prompt="x", reference_images=("https://example.test/a.png",)),
            "reference-to-video",
        ),
    ],
)
def test_wavespeed_picks_the_endpoint_from_the_inputs(
    settings: Settings, spec: JobSpec, endpoint: str
) -> None:
    assert WaveSpeedProvider(settings).prepare_submit(spec).url.endswith(endpoint)


def test_turbo_is_a_different_model_not_a_flag(settings: Settings) -> None:
    spec = JobSpec(prompt="x")
    standard = WaveSpeedProvider(settings).prepare_submit(spec).url
    turbo = WaveSpeedTurboProvider(settings).prepare_submit(spec).url
    assert "seedance-2.5/" in standard
    assert "seedance-2.5-turbo/" in turbo


def test_wavespeed_unwraps_the_data_envelope(settings: Settings) -> None:
    provider = WaveSpeedProvider(settings)
    assert provider.parse_submit({"code": 200, "data": {"id": "task-1"}}) == "task-1"
    status = provider.parse_poll(
        {"data": {"status": "completed", "outputs": ["https://cdn.example.test/v.mp4"]}}
    )
    assert status.status is JobStatus.SUCCEEDED
    assert status.video_url == "https://cdn.example.test/v.mp4"


# ---------------------------------------------------------------------------
# Error classification — the runner depends on this split
# ---------------------------------------------------------------------------
@respx.mock
async def test_rate_limit_is_retryable(settings: Settings) -> None:
    respx.post(url__regex=r".*/contents/generations/tasks").mock(
        return_value=httpx.Response(429, text="slow down")
    )
    async with httpx.AsyncClient() as client:
        with pytest.raises(RetryableProviderError, match="429"):
            await ModelArkProvider(settings).submit(client, JobSpec(prompt="x"))


@respx.mock
async def test_bad_credentials_are_fatal(settings: Settings) -> None:
    respx.post(url__regex=r".*/contents/generations/tasks").mock(
        return_value=httpx.Response(401, text="bad key")
    )
    async with httpx.AsyncClient() as client:
        with pytest.raises(FatalProviderError, match="401"):
            await ModelArkProvider(settings).submit(client, JobSpec(prompt="x"))


@respx.mock
async def test_a_successful_round_trip(settings: Settings) -> None:
    respx.post(url__regex=r".*/contents/generations/tasks").mock(
        return_value=httpx.Response(200, json={"id": "cgt-1"})
    )
    respx.get(url__regex=r".*/contents/generations/tasks/cgt-1").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "succeeded",
                "content": {"video_url": "https://cdn.example.test/v.mp4"},
                "usage": {"completion_tokens": 48038},
            },
        )
    )
    provider = ModelArkProvider(settings)
    async with httpx.AsyncClient() as client:
        task_id = await provider.submit(client, JobSpec(prompt="x"))
        status = await provider.poll(client, task_id)

    assert task_id == "cgt-1"
    assert status.tokens == 48038
