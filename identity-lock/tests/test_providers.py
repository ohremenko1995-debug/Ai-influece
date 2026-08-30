"""Providers: determinism, failure messages, and the ComfyUI contract."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from identitylock.domain.models import Character, PromptSpec, Recipe
from identitylock.imaging.loader import load_image
from identitylock.providers import build_provider
from identitylock.providers.base import GenerationRequest, ProviderError
from identitylock.providers.comfyui import (
    apply_placeholders,
    first_image,
    load_workflow,
    placeholders,
)
from identitylock.providers.synthetic import jitter_traits, scene_for, traits_for


def _request(
    tmp_path: Path, *, character: str = "ava", seed: int = 1, index: int = 0, **extra: float
) -> GenerationRequest:
    return GenerationRequest(
        character=Character(id=character, name=character.title()),
        prompt=PromptSpec(id="studio", text="studio portrait"),
        seed=seed,
        index=index,
        recipe=Recipe(id="r", name="R", width=96, height=96, extra=dict(extra)),
        output_dir=tmp_path,
    )


class TestTraits:
    def test_are_stable_for_an_id(self) -> None:
        assert traits_for("ava") == traits_for("ava")

    def test_differ_between_characters(self) -> None:
        assert traits_for("ava") != traits_for("mira")

    def test_zero_jitter_is_the_identity_function(self) -> None:
        rng = np.random.default_rng(0)
        assert jitter_traits(traits_for("ava"), 0.0, rng) == traits_for("ava")

    def test_jitter_moves_the_traits(self) -> None:
        rng = np.random.default_rng(0)
        assert jitter_traits(traits_for("ava"), 0.3, rng) != traits_for("ava")

    def test_jittered_traits_stay_in_range(self) -> None:
        rng = np.random.default_rng(1)
        for _ in range(30):
            traits = jitter_traits(traits_for("ava"), 0.9, rng)
            assert 0.11 <= traits.face_width <= 0.23
            assert 0.0 <= traits.skin_sat <= 1.0
            assert 0.0 <= traits.hair_hue < 1.0


class TestScene:
    def test_is_stable_for_a_cell(self) -> None:
        assert scene_for("studio", 1) == scene_for("studio", 1)

    def test_differs_between_seeds(self) -> None:
        assert scene_for("studio", 1) != scene_for("studio", 2)

    def test_the_neutral_scene_is_restrained(self) -> None:
        neutral = scene_for("studio", 1, neutral=True)
        assert neutral.bg_sat <= 0.12
        assert abs(neutral.shift_x) <= 0.008


class TestSyntheticProvider:
    def test_writes_a_readable_image(self, tmp_path: Path) -> None:
        candidate = build_provider("synthetic").generate(_request(tmp_path))
        assert candidate.image_path.is_file()
        image = load_image(candidate.image_path)
        assert image.shape == (96, 96, 3)

    def test_is_byte_identical_across_calls(self, tmp_path: Path) -> None:
        provider = build_provider("synthetic")
        first = provider.generate(_request(tmp_path / "a"))
        second = provider.generate(_request(tmp_path / "b"))
        assert first.image_sha256 == second.image_sha256

    def test_the_seed_changes_the_frame(self, tmp_path: Path) -> None:
        provider = build_provider("synthetic")
        first = provider.generate(_request(tmp_path / "a", seed=1))
        second = provider.generate(_request(tmp_path / "b", seed=2))
        assert first.image_sha256 != second.image_sha256

    def test_drift_makes_later_frames_differ(self, tmp_path: Path) -> None:
        provider = build_provider("synthetic")
        early = provider.generate(_request(tmp_path / "a", index=0, drift_per_frame=0.05))
        late = provider.generate(_request(tmp_path / "b", index=20, drift_per_frame=0.05))
        assert early.image_sha256 != late.image_sha256

    def test_index_is_inert_without_drift(self, tmp_path: Path) -> None:
        provider = build_provider("synthetic")
        early = provider.generate(_request(tmp_path / "a", index=0))
        late = provider.generate(_request(tmp_path / "b", index=20))
        assert early.image_sha256 == late.image_sha256

    def test_blur_lowers_the_measured_sharpness(self, tmp_path: Path) -> None:
        from identitylock.imaging.stats import sharpness

        provider = build_provider("synthetic")
        sharp = load_image(provider.generate(_request(tmp_path / "a")).image_path)
        soft = load_image(provider.generate(_request(tmp_path / "b", blur=2.5)).image_path)
        assert sharpness(sharp) > sharpness(soft)

    def test_records_the_recipe_revision(self, tmp_path: Path) -> None:
        request = _request(tmp_path)
        candidate = build_provider("synthetic").generate(request)
        assert candidate.recipe_revision == request.recipe.revision

    def test_non_square_frames_are_cropped_to_size(self, tmp_path: Path) -> None:
        request = GenerationRequest(
            character=Character(id="ava", name="Ava"),
            prompt=PromptSpec(id="p", text="p"),
            seed=1,
            index=0,
            recipe=Recipe(id="r", name="R", width=128, height=96),
            output_dir=tmp_path,
        )
        image = load_image(build_provider("synthetic").generate(request).image_path)
        assert image.shape[:2] == (96, 128)


class TestDirectoryProvider:
    def test_finds_a_frame_by_cell_id(self, tmp_path: Path) -> None:
        source = tmp_path / "frames"
        source.mkdir()
        request = _request(tmp_path)
        build_provider("synthetic").generate(request.model_copy(update={"output_dir": source}))
        candidate = build_provider("directory", root=source).generate(request)
        assert candidate.provider == "directory"
        assert candidate.id == request.candidate_id

    def test_a_missing_frame_names_the_cell(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()
        with pytest.raises(ProviderError, match="No image for cell"):
            build_provider("directory", root=empty).generate(_request(tmp_path))

    def test_a_missing_directory_fails_immediately(self, tmp_path: Path) -> None:
        with pytest.raises(ProviderError, match="does not exist"):
            build_provider("directory", root=tmp_path / "nope")

    def test_missing_options_fail_before_any_work(self) -> None:
        with pytest.raises(ProviderError, match="needs root="):
            build_provider("directory")
        with pytest.raises(ProviderError, match="needs base_url="):
            build_provider("comfyui")

    def test_unknown_provider_lists_the_known_ones(self) -> None:
        with pytest.raises(ProviderError, match="synthetic, directory, comfyui"):
            build_provider("magic")


class TestComfyUIContract:
    """The adapter is not exercised against a live host; its logic is."""

    def test_whole_string_placeholders_keep_their_type(self, tmp_path: Path) -> None:
        graph = {"3": {"inputs": {"seed": "{{seed}}", "steps": "{{steps}}"}}}
        result = apply_placeholders(graph, placeholders(_request(tmp_path, seed=42)))
        assert result["3"]["inputs"]["seed"] == 42
        assert isinstance(result["3"]["inputs"]["steps"], int)

    def test_embedded_placeholders_interpolate(self, tmp_path: Path) -> None:
        graph = {"3": {"inputs": {"text": "photo of {{character}}, {{prompt}}"}}}
        result = apply_placeholders(graph, placeholders(_request(tmp_path)))
        assert result["3"]["inputs"]["text"] == "photo of ava, studio portrait"

    def test_untouched_values_survive(self, tmp_path: Path) -> None:
        graph = {"3": {"inputs": {"ckpt_name": "krea2_turbo_fp8.safetensors"}}}
        result = apply_placeholders(graph, placeholders(_request(tmp_path)))
        assert result["3"]["inputs"]["ckpt_name"] == "krea2_turbo_fp8.safetensors"

    def test_an_unknown_placeholder_is_an_error(self, tmp_path: Path) -> None:
        with pytest.raises(ProviderError, match="unknown placeholder"):
            apply_placeholders({"a": "{{nope}}"}, placeholders(_request(tmp_path)))

    def test_prompt_affixes_are_applied(self, tmp_path: Path) -> None:
        request = _request(tmp_path)
        recipe = request.recipe.model_copy(
            update={"prompt_prefix": "raw photo, ", "prompt_suffix": ", 85mm"}
        )
        values = placeholders(request.model_copy(update={"recipe": recipe}))
        assert values["prompt"] == "raw photo, studio portrait, 85mm"

    def test_picks_the_single_output(self) -> None:
        outputs = {"9": {"images": [{"filename": "a.png", "type": "output", "subfolder": ""}]}}
        assert first_image(outputs)["filename"] == "a.png"

    def test_ignores_temp_previews(self) -> None:
        outputs = {
            "8": {"images": [{"filename": "preview.png", "type": "temp"}]},
            "9": {"images": [{"filename": "final.png", "type": "output"}]},
        }
        assert first_image(outputs)["filename"] == "final.png"

    def test_refuses_an_ambiguous_multi_saver_graph(self) -> None:
        outputs = {
            "9": {"images": [{"filename": "a.png", "type": "output"}]},
            "10": {"images": [{"filename": "b.png", "type": "output"}]},
        }
        with pytest.raises(ProviderError, match="several nodes"):
            first_image(outputs)

    def test_no_output_is_an_error(self) -> None:
        with pytest.raises(ProviderError, match="no output images"):
            first_image({})

    def test_the_bundled_template_loads_and_substitutes(self, tmp_path: Path) -> None:
        template = Path(__file__).parent.parent / "suites" / "workflows" / "portrait.api.json"
        graph = load_workflow(template)
        assert not any(key.startswith("_") for key in graph)
        resolved = apply_placeholders(graph, placeholders(_request(tmp_path, seed=101)))
        assert resolved["3"]["inputs"]["seed"] == 101
        assert "{{" not in json.dumps(resolved)
        savers = [node for node in resolved.values() if node["class_type"] == "SaveImage"]
        assert len(savers) == 1

    def test_a_comment_only_workflow_is_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "empty.json"
        path.write_text('{"_comment": "nothing here"}', encoding="utf-8")
        with pytest.raises(ProviderError, match="no nodes"):
            load_workflow(path)

    def test_a_non_object_workflow_is_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "list.json"
        path.write_text("[1, 2, 3]", encoding="utf-8")
        with pytest.raises(ProviderError, match="API-format workflow"):
            load_workflow(path)
