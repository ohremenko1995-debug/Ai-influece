"""ComfyUI adapter — submit a workflow, wait, fetch the frame.

Written against ComfyUI's documented HTTP API (``POST /prompt``, ``GET /history``,
``GET /view``). **Not exercised in this repository's CI**: the test container has
no GPU and no ComfyUI host, and a green test against a mock would only prove the
mock works. The contract tests that do run pin the placeholder substitution and
the output-selection logic, which is where the real bugs live.

Workflows are supplied as ComfyUI *API-format* JSON with placeholders in widget
values::

    "text":  "{{prompt}}"          ->  the prompt for this cell
    "seed":  "{{seed}}"            ->  the seed, as an integer
    "width": "{{width}}"           ->  from the recipe

A placeholder that occupies the whole string is replaced by a typed value; one
embedded in a longer string is interpolated as text. Anything the template does
not reference is left exactly as the artist saved it — this adapter never invents
graph structure.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from identitylock.domain.models import Candidate
from identitylock.imaging.loader import sha256_file
from identitylock.providers.base import GenerationRequest, ProviderError

DEFAULT_TIMEOUT = 600.0
POLL_INTERVAL = 1.5


def load_workflow(path: Path) -> dict[str, Any]:
    """Read an API-format workflow, dropping top-level keys that start with ``_``.

    ComfyUI's API format is a flat map of node id to node, with no place to write
    down what a template is for. Reserving the ``_`` prefix gives a template room
    for a comment without posting a node ComfyUI would reject.
    """
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ProviderError(f"{path} is not an API-format workflow (expected a JSON object)")
    graph = {key: value for key, value in raw.items() if not key.startswith("_")}
    if not graph:
        raise ProviderError(f"{path} contains no nodes")
    return graph


def placeholders(request: GenerationRequest) -> dict[str, str | int | float]:
    """The values a workflow template may reference."""
    recipe = request.recipe
    return {
        "prompt": f"{recipe.prompt_prefix}{request.prompt.text}{recipe.prompt_suffix}".strip(),
        "negative": recipe.negative_prompt,
        "seed": request.seed,
        "width": recipe.width,
        "height": recipe.height,
        "steps": recipe.steps,
        "cfg": recipe.cfg,
        "sampler": recipe.sampler,
        "scheduler": recipe.scheduler,
        "model": recipe.model,
        "character": request.character.id,
    }


def apply_placeholders(node: Any, values: dict[str, str | int | float]) -> Any:
    """Recursively substitute ``{{name}}`` markers in a workflow graph.

    A string that *is* a placeholder becomes the typed value, so ``"{{seed}}"``
    reaches ComfyUI as the integer its node expects rather than as text.
    """
    if isinstance(node, dict):
        return {key: apply_placeholders(value, values) for key, value in node.items()}
    if isinstance(node, list):
        return [apply_placeholders(item, values) for item in node]
    if isinstance(node, str):
        stripped = node.strip()
        if stripped.startswith("{{") and stripped.endswith("}}"):
            key = stripped[2:-2].strip()
            if key in values:
                return values[key]
            raise ProviderError(f"Workflow references unknown placeholder '{{{{{key}}}}}'")
        for key, value in values.items():
            node = node.replace(f"{{{{{key}}}}}", str(value))
        return node
    return node


def first_image(outputs: dict[str, Any]) -> dict[str, str]:
    """Pick the image to score out of a history entry's outputs.

    ComfyUI returns every saving node's results keyed by node id. Preferring the
    lowest node id makes the choice deterministic across runs instead of
    dictionary-order dependent, and a workflow with several savers should be
    telling the harness which one matters — so a multi-output graph is an error,
    not a coin flip.
    """
    images = [
        (node_id, image)
        for node_id, payload in sorted(outputs.items(), key=lambda item: str(item[0]))
        for image in payload.get("images", [])
        if image.get("type") == "output"
    ]
    if not images:
        raise ProviderError("ComfyUI returned no output images for this prompt")
    if len({node_id for node_id, _ in images}) > 1:
        nodes = ", ".join(sorted({node_id for node_id, _ in images}))
        raise ProviderError(
            f"Workflow saved output from several nodes ({nodes}); "
            "keep exactly one SaveImage node so the scored frame is unambiguous."
        )
    return dict(images[0][1])


class ComfyUIProvider:
    """Run a ComfyUI workflow once per suite cell."""

    name = "comfyui"

    def __init__(
        self,
        base_url: str,
        workflow_path: Path,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        poll_interval: float = POLL_INTERVAL,
    ) -> None:
        try:
            import httpx
        except ImportError as error:  # pragma: no cover - optional extra
            raise ProviderError(
                "The comfyui provider needs httpx. Install it with: pip install httpx"
            ) from error

        self._httpx = httpx
        self._base_url = base_url.rstrip("/")
        self._workflow = load_workflow(Path(workflow_path))
        self._timeout = timeout
        self._poll_interval = poll_interval
        self._client_id = str(uuid.uuid4())
        self.name = f"comfyui:{self._base_url}"

    def _submit(self, client: Any, graph: dict[str, Any]) -> str:
        response = client.post(
            f"{self._base_url}/prompt", json={"prompt": graph, "client_id": self._client_id}
        )
        if response.status_code >= 400:
            raise ProviderError(
                f"ComfyUI rejected the workflow ({response.status_code}): {response.text[:400]}"
            )
        prompt_id = response.json().get("prompt_id")
        if not prompt_id:
            raise ProviderError("ComfyUI accepted the workflow but returned no prompt_id")
        return str(prompt_id)

    def _await_history(self, client: Any, prompt_id: str) -> dict[str, Any]:
        deadline = time.monotonic() + self._timeout
        while time.monotonic() < deadline:
            response = client.get(f"{self._base_url}/history/{prompt_id}")
            if response.status_code == 200:
                history = response.json().get(prompt_id)
                if history and history.get("outputs"):
                    return dict(history)
                status = (history or {}).get("status", {})
                if status.get("status_str") == "error":
                    raise ProviderError(
                        f"ComfyUI reported an execution error: {json.dumps(status)[:400]}"
                    )
            time.sleep(self._poll_interval)
        raise ProviderError(
            f"ComfyUI did not finish prompt {prompt_id} within {self._timeout:.0f}s"
        )

    def generate(self, request: GenerationRequest) -> Candidate:
        started = time.perf_counter()
        graph = apply_placeholders(self._workflow, placeholders(request))

        with self._httpx.Client(timeout=self._timeout) as client:
            prompt_id = self._submit(client, graph)
            history = self._await_history(client, prompt_id)
            reference = first_image(history["outputs"])
            image = client.get(
                f"{self._base_url}/view",
                params={
                    "filename": reference["filename"],
                    "subfolder": reference.get("subfolder", ""),
                    "type": reference.get("type", "output"),
                },
            )
            if image.status_code != 200:
                raise ProviderError(
                    f"Could not fetch {reference['filename']} ({image.status_code})"
                )

        path = (
            request.output_dir
            / f"{request.candidate_id}{Path(reference['filename']).suffix or '.png'}"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(image.content)

        return Candidate(
            id=request.candidate_id,
            prompt_id=request.prompt.id,
            prompt=request.prompt.text,
            seed=request.seed,
            recipe_revision=request.recipe.revision,
            provider=self.name,
            image_path=path,
            image_sha256=sha256_file(path),
            latency_ms=round((time.perf_counter() - started) * 1000.0, 3),
        )
