"""A procedural character renderer, so the harness has something real to measure.

Why this exists: an evaluation tool whose demo ships pre-baked numbers proves
nothing. This provider draws actual images from actual parameters, and every
metric downstream is computed from those pixels. Run the demo and the numbers on
the screen were measured, not stored.

It is a *deterministic simulator of a generation stack*, not a generative model.
It gives the harness the three behaviours a real one has and a test needs:

* an **identity** that is stable across prompts and seeds (the traits),
* **scene variety** driven by prompt and seed (framing, light, palette),
* **controllable failure** — ``identity_jitter`` loosens the character,
  ``drift_per_frame`` makes it slide as the batch goes on, ``blur`` and
  ``exposure_bias`` degrade the frame.

Those knobs live in ``recipe.extra``, so "recipe A vs recipe B" in a demo is a
genuine A/B over two configurations, scored by the same code path a ComfyUI run
would take.
"""

from __future__ import annotations

import colorsys
import hashlib
import time
from dataclasses import dataclass, replace

import numpy as np
from numpy.typing import NDArray
from PIL import Image as PILImage
from PIL import ImageFilter

from identitylock.domain.models import Candidate
from identitylock.imaging.loader import Image, sha256_file
from identitylock.providers.base import GenerationRequest

Grid = NDArray[np.float32]


def _seed_from(*parts: object) -> int:
    digest = hashlib.sha256("|".join(str(part) for part in parts).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def _rng(*parts: object) -> np.random.Generator:
    return np.random.default_rng(_seed_from(*parts))


def _hsv(hue: float, saturation: float, value: float) -> NDArray[np.float32]:
    rgb = colorsys.hsv_to_rgb(
        hue % 1.0, float(np.clip(saturation, 0, 1)), float(np.clip(value, 0, 1))
    )
    return np.asarray(rgb, dtype=np.float32)


@dataclass(frozen=True, slots=True)
class Traits:
    """Everything that makes this character this character."""

    skin_hue: float
    skin_sat: float
    skin_val: float
    hair_hue: float
    hair_sat: float
    hair_val: float
    eye_hue: float
    eye_sat: float
    cloth_hue: float
    cloth_sat: float
    cloth_val: float
    face_width: float
    face_height: float
    eye_spacing: float
    eye_level: float
    eye_size: float
    brow_weight: float
    hair_volume: float
    mouth_width: float


@dataclass(frozen=True, slots=True)
class Scene:
    """Everything that varies between takes without changing who is in them."""

    bg_hue: float
    bg_sat: float
    bg_top: float
    bg_bottom: float
    light_angle: float
    light_strength: float
    zoom: float
    shift_x: float
    shift_y: float
    rim: float


def traits_for(character_id: str) -> Traits:
    """Deterministic traits for a character id. Same id, same face, forever."""
    rng = _rng("traits", character_id)
    return Traits(
        skin_hue=float(rng.uniform(0.02, 0.09)),
        skin_sat=float(rng.uniform(0.22, 0.46)),
        skin_val=float(rng.uniform(0.58, 0.92)),
        hair_hue=float(rng.uniform(0.0, 1.0)),
        hair_sat=float(rng.uniform(0.25, 0.85)),
        hair_val=float(rng.uniform(0.12, 0.72)),
        eye_hue=float(rng.uniform(0.0, 1.0)),
        eye_sat=float(rng.uniform(0.35, 0.85)),
        cloth_hue=float(rng.uniform(0.0, 1.0)),
        cloth_sat=float(rng.uniform(0.15, 0.75)),
        cloth_val=float(rng.uniform(0.18, 0.75)),
        face_width=float(rng.uniform(0.145, 0.185)),
        face_height=float(rng.uniform(0.185, 0.235)),
        eye_spacing=float(rng.uniform(0.052, 0.075)),
        eye_level=float(rng.uniform(-0.015, 0.015)),
        eye_size=float(rng.uniform(0.019, 0.028)),
        brow_weight=float(rng.uniform(0.006, 0.013)),
        hair_volume=float(rng.uniform(1.02, 1.34)),
        mouth_width=float(rng.uniform(0.036, 0.058)),
    )


def scene_for(prompt_id: str, seed: int, *, neutral: bool = False) -> Scene:
    """Deterministic scene for a (prompt, seed) cell.

    ``neutral`` is the studio condition used for reference sets: one backdrop
    family, restrained light, near-fixed framing. Real golden references are shot
    under controlled conditions for exactly this reason — a reference set that
    varies as much as production output produces a centroid that means nothing.
    """
    rng = _rng("scene", prompt_id, seed)
    if neutral:
        return Scene(
            bg_hue=0.58,
            bg_sat=float(rng.uniform(0.05, 0.12)),
            bg_top=float(rng.uniform(0.62, 0.72)),
            bg_bottom=float(rng.uniform(0.24, 0.32)),
            light_angle=float(rng.uniform(-0.5, 0.5)),
            light_strength=float(rng.uniform(0.16, 0.24)),
            zoom=float(rng.uniform(0.99, 1.03)),
            shift_x=float(rng.uniform(-0.008, 0.008)),
            shift_y=float(rng.uniform(-0.008, 0.008)),
            rim=float(rng.uniform(0.0, 0.10)),
        )
    return Scene(
        bg_hue=float(rng.uniform(0.0, 1.0)),
        bg_sat=float(rng.uniform(0.05, 0.42)),
        bg_top=float(rng.uniform(0.35, 0.85)),
        bg_bottom=float(rng.uniform(0.08, 0.45)),
        light_angle=float(rng.uniform(0.0, 2.0 * np.pi)),
        light_strength=float(rng.uniform(0.16, 0.42)),
        zoom=float(rng.uniform(0.92, 1.12)),
        shift_x=float(rng.uniform(-0.035, 0.035)),
        shift_y=float(rng.uniform(-0.03, 0.03)),
        rim=float(rng.uniform(0.0, 0.35)),
    )


def jitter_traits(traits: Traits, amount: float, rng: np.random.Generator) -> Traits:
    """Perturb identity by ``amount``.

    Hues wrap, everything else is scaled by its own plausible range so a single
    knob moves every trait by a comparable *perceptual* amount rather than a
    comparable numeric one.
    """
    if amount <= 0.0:
        return traits

    def shift(value: float, scale: float, *, wrap: bool = False) -> float:
        moved = value + float(rng.normal(0.0, amount * scale))
        return moved % 1.0 if wrap else moved

    return replace(
        traits,
        skin_hue=shift(traits.skin_hue, 0.06, wrap=True),
        skin_sat=float(np.clip(shift(traits.skin_sat, 0.25), 0.05, 0.9)),
        skin_val=float(np.clip(shift(traits.skin_val, 0.25), 0.2, 1.0)),
        hair_hue=shift(traits.hair_hue, 0.35, wrap=True),
        hair_sat=float(np.clip(shift(traits.hair_sat, 0.35), 0.05, 1.0)),
        hair_val=float(np.clip(shift(traits.hair_val, 0.3), 0.05, 0.95)),
        eye_hue=shift(traits.eye_hue, 0.35, wrap=True),
        face_width=float(np.clip(shift(traits.face_width, 0.05), 0.11, 0.23)),
        face_height=float(np.clip(shift(traits.face_height, 0.06), 0.15, 0.28)),
        eye_spacing=float(np.clip(shift(traits.eye_spacing, 0.025), 0.04, 0.09)),
        eye_size=float(np.clip(shift(traits.eye_size, 0.010), 0.013, 0.035)),
        hair_volume=float(np.clip(shift(traits.hair_volume, 0.22), 0.85, 1.6)),
        mouth_width=float(np.clip(shift(traits.mouth_width, 0.020), 0.025, 0.075)),
    )


def _smoothstep(edge0: float, edge1: float, value: Grid) -> Grid:
    span = max(edge1 - edge0, 1e-6)
    t = np.clip((value - edge0) / span, 0.0, 1.0)
    return np.asarray(t * t * (3.0 - 2.0 * t), dtype=np.float32)


def _ellipse(
    xs: Grid, ys: Grid, cx: float, cy: float, rx: float, ry: float, *, soft: float = 0.010
) -> Grid:
    """Anti-aliased filled ellipse mask in [0, 1]."""
    radial = np.sqrt(((xs - cx) / max(rx, 1e-6)) ** 2 + ((ys - cy) / max(ry, 1e-6)) ** 2)
    edge = soft / max(min(rx, ry), 1e-6)
    return 1.0 - _smoothstep(1.0 - edge, 1.0 + edge, radial)


def _over(base: Image, colour: NDArray[np.float32], mask: Grid) -> Image:
    alpha = mask[..., None]
    return np.asarray(base * (1.0 - alpha) + colour[None, None, :] * alpha, dtype=np.float32)


def render(
    traits: Traits, scene: Scene, size: int, *, grain: float, rng: np.random.Generator
) -> Image:
    """Draw one square frame from traits and scene."""
    axis = np.linspace(0.0, 1.0, size, dtype=np.float32)
    xs, ys = np.meshgrid(axis, axis)
    xs = (xs - 0.5) / scene.zoom + 0.5 - scene.shift_x
    ys = (ys - 0.5) / scene.zoom + 0.5 - scene.shift_y

    # Background: vertical gradient, then a soft vignette.
    top = _hsv(scene.bg_hue, scene.bg_sat, scene.bg_top)
    bottom = _hsv(scene.bg_hue + 0.06, scene.bg_sat * 0.8, scene.bg_bottom)
    frame = (
        top[None, None, :] * (1.0 - ys[..., None]) + bottom[None, None, :] * ys[..., None]
    ).astype(np.float32)
    vignette = 1.0 - 0.35 * _smoothstep(0.35, 0.95, np.sqrt((xs - 0.5) ** 2 + (ys - 0.5) ** 2))
    frame *= vignette[..., None]
    glow = 0.16 * (1.0 - _smoothstep(0.05, 0.42, np.sqrt((xs - 0.5) ** 2 + (ys - 0.42) ** 2)))
    frame += glow[..., None].astype(np.float32)

    head_cx, head_cy = 0.5, 0.42
    skin = _hsv(traits.skin_hue, traits.skin_sat, traits.skin_val)
    hair = _hsv(traits.hair_hue, traits.hair_sat, traits.hair_val)
    cloth = _hsv(traits.cloth_hue, traits.cloth_sat, traits.cloth_val)

    # Torso and neck.
    frame = _over(
        frame, cloth, _ellipse(xs, ys, 0.5, 1.06, traits.face_width * 2.35, 0.34, soft=0.02)
    )
    frame = _over(
        frame, skin * 0.93, _ellipse(xs, ys, 0.5, head_cy + 0.21, traits.face_width * 0.52, 0.10)
    )

    # Hair mass behind the head, then the face, then the fringe on top of it.
    hair_mask = _ellipse(
        xs,
        ys,
        head_cx,
        head_cy - 0.02,
        traits.face_width * traits.hair_volume,
        traits.face_height * traits.hair_volume,
    )
    # Directional strands: a low-amplitude sinusoid across the hair mass. It is the
    # only high-frequency texture in the frame, which is what gives the LBP block
    # something character-specific to describe.
    strands = 1.0 + 0.13 * np.sin(
        (xs * np.cos(0.7) + ys * np.sin(0.7)) * 190.0 * traits.hair_volume
    )
    frame = _over(frame, hair, hair_mask)
    frame = np.asarray(
        frame * (1.0 - hair_mask[..., None]) + frame * strands[..., None] * hair_mask[..., None],
        dtype=np.float32,
    )
    face = _ellipse(xs, ys, head_cx, head_cy, traits.face_width, traits.face_height)
    # Form shading: skin darkens toward the silhouette, so the head reads as a
    # volume. Without it the descriptor sees a flat disc and the gradient block
    # carries almost no information about face shape.
    face_radial = np.sqrt(
        ((xs - head_cx) / traits.face_width) ** 2 + ((ys - head_cy) / traits.face_height) ** 2
    )
    shading = np.clip(1.10 - 0.30 * np.clip(face_radial, 0.0, 1.0) ** 2, 0.0, 1.2).astype(
        np.float32
    )
    frame = _over(frame, skin, face)
    frame = np.asarray(
        frame * (1.0 - face[..., None]) + frame * shading[..., None] * face[..., None],
        dtype=np.float32,
    )
    frame = _over(
        frame,
        hair * 0.94,
        _ellipse(
            xs,
            ys,
            head_cx,
            head_cy - traits.face_height * 0.74,
            traits.face_width * 1.02,
            traits.face_height * 0.44,
        ),
    )

    # Eyes: sclera, iris, pupil, catchlight.
    eye_y = head_cy - traits.face_height * 0.10 + traits.eye_level
    iris = _hsv(traits.eye_hue, traits.eye_sat, 0.62)
    for direction in (-1.0, 1.0):
        eye_x = head_cx + direction * traits.eye_spacing
        frame = _over(
            frame,
            np.asarray([0.95, 0.94, 0.93], dtype=np.float32),
            _ellipse(xs, ys, eye_x, eye_y, traits.eye_size, traits.eye_size * 0.58, soft=0.004),
        )
        frame = _over(
            frame,
            iris,
            _ellipse(
                xs, ys, eye_x, eye_y, traits.eye_size * 0.52, traits.eye_size * 0.52, soft=0.003
            ),
        )
        frame = _over(
            frame,
            np.asarray([0.05, 0.05, 0.06], dtype=np.float32),
            _ellipse(
                xs, ys, eye_x, eye_y, traits.eye_size * 0.22, traits.eye_size * 0.22, soft=0.002
            ),
        )
        frame = _over(
            frame,
            np.asarray([1.0, 1.0, 1.0], dtype=np.float32),
            _ellipse(
                xs,
                ys,
                eye_x - traits.eye_size * 0.2,
                eye_y - traits.eye_size * 0.2,
                traits.eye_size * 0.10,
                traits.eye_size * 0.10,
                soft=0.002,
            ),
        )
        brow = _ellipse(
            xs,
            ys,
            eye_x,
            eye_y - traits.eye_size * 1.75,
            traits.eye_size * 1.25,
            traits.brow_weight,
            soft=0.004,
        )
        frame = _over(frame, hair * 0.8, brow)

    # Nose shadow and mouth.
    frame = _over(
        frame,
        skin * 0.82,
        _ellipse(
            xs,
            ys,
            head_cx,
            head_cy + traits.face_height * 0.24,
            traits.face_width * 0.16,
            traits.face_height * 0.10,
        ),
    )
    lips = _hsv(traits.skin_hue - 0.01, min(1.0, traits.skin_sat * 1.9), traits.skin_val * 0.78)
    frame = _over(
        frame,
        lips,
        _ellipse(
            xs,
            ys,
            head_cx,
            head_cy + traits.face_height * 0.52,
            traits.mouth_width,
            traits.mouth_width * 0.36,
            soft=0.005,
        ),
    )

    # Directional light and rim.
    light = (
        1.0
        + scene.light_strength
        * (np.cos(scene.light_angle) * (xs - 0.5) + np.sin(scene.light_angle) * (0.5 - ys))
        * 2.0
    )
    frame *= light[..., None].astype(np.float32)
    if scene.rim > 0.0:
        edge = _ellipse(
            xs, ys, head_cx, head_cy, traits.face_width * 1.05, traits.face_height * 1.05
        ) - _ellipse(xs, ys, head_cx, head_cy, traits.face_width * 0.94, traits.face_height * 0.94)
        frame += (scene.rim * np.clip(edge, 0.0, 1.0))[..., None]

    if grain > 0.0:
        frame += rng.normal(0.0, grain, size=frame.shape).astype(np.float32)

    return np.asarray(np.clip(frame, 0.0, 1.0), dtype=np.float32)


def _degrade(frame: Image, *, blur: float, exposure_bias: float) -> Image:
    if blur > 0.0:
        pil = PILImage.fromarray((frame * 255.0 + 0.5).astype(np.uint8), mode="RGB")
        blurred = pil.filter(ImageFilter.GaussianBlur(radius=blur))
        frame = np.asarray(blurred, dtype=np.float32) / 255.0
    if exposure_bias != 0.0:
        frame = frame * float(2.0**exposure_bias)
    return np.asarray(np.clip(frame, 0.0, 1.0), dtype=np.float32)


class SyntheticProvider:
    """Deterministic procedural renderer. No network, no GPU, no model weights."""

    name = "synthetic"

    def generate(self, request: GenerationRequest) -> Candidate:
        started = time.perf_counter()
        recipe = request.recipe
        extra = recipe.extra

        jitter = float(extra.get("identity_jitter", 0.0))
        drift_per_frame = float(extra.get("drift_per_frame", 0.0))
        grain = float(extra.get("grain", 0.015))
        blur = float(extra.get("blur", 0.0))
        exposure_bias = float(extra.get("exposure_bias", 0.0))

        rng = _rng(recipe.revision, request.character.id, request.prompt.id, request.seed)
        traits = traits_for(request.character.id)
        total_jitter = jitter + drift_per_frame * float(request.index)
        traits = jitter_traits(traits, total_jitter, rng)
        scene = scene_for(
            request.prompt.id, request.seed, neutral=bool(extra.get("neutral_scene", False))
        )

        side = max(recipe.width, recipe.height)
        frame = render(traits, scene, side, grain=grain, rng=rng)
        frame = _degrade(frame, blur=blur, exposure_bias=exposure_bias)

        if (recipe.width, recipe.height) != (side, side):
            top = (side - recipe.height) // 2
            left = (side - recipe.width) // 2
            frame = np.ascontiguousarray(
                frame[top : top + recipe.height, left : left + recipe.width]
            )

        path = request.output_dir / f"{request.candidate_id}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        PILImage.fromarray((frame * 255.0 + 0.5).astype(np.uint8), mode="RGB").save(
            path, format="PNG"
        )

        return Candidate(
            id=request.candidate_id,
            prompt_id=request.prompt.id,
            prompt=request.prompt.text,
            seed=request.seed,
            recipe_revision=recipe.revision,
            provider=self.name,
            image_path=path,
            image_sha256=sha256_file(path),
            latency_ms=round((time.perf_counter() - started) * 1000.0, 3),
        )
