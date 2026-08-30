"""Shared fixtures.

The fixture suite is deliberately tiny — two characters, two prompts, two seeds,
128px frames. A test suite that takes forty seconds gets run once a day; this one
runs in a couple of seconds, so it gets run on every save.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from identitylock.embeddings import get_embedder
from identitylock.evaluation import Evaluator, SuiteFile, load_suite_file, render_references
from identitylock.providers import build_provider
from identitylock.providers.base import GenerationProvider

TINY_SUITE = """
id: tiny
description: Two characters, two prompts, two seeds.
character: alpha
cohort: [alpha, beta]
characters:
  alpha:
    name: Alpha
    references: references/alpha
  beta:
    name: Beta
    references: references/beta
prompts:
  - id: studio
    text: studio portrait
    tags: [portrait]
  - id: street
    text: street portrait
seeds: [11, 22]
reference_recipe: locked
reference_count: 4
recipes:
  locked:
    name: Locked
    width: 128
    height: 128
    extra: {identity_jitter: 0.02, grain: 0.01}
  loose:
    name: Loose
    width: 128
    height: 128
    extra: {identity_jitter: 0.30, drift_per_frame: 0.02, blur: 0.8, grain: 0.03}
select_k: 2
select_lambda: 0.7
policy:
  identity_min: -1.0
  margin_min: 0.0
  technical_min: 0.0
  consistency_rate_min: 0.0
  identity_p05_min: -1.0
  drift_abs_max: 1.0
  diversity_min: 0.0
"""


@pytest.fixture
def suite_path(tmp_path: Path) -> Path:
    path = tmp_path / "tiny.yaml"
    path.write_text(TINY_SUITE, encoding="utf-8")
    return path


@pytest.fixture
def suite_file(suite_path: Path) -> SuiteFile:
    return load_suite_file(suite_path)


@pytest.fixture
def provider() -> GenerationProvider:
    return build_provider("synthetic")


@pytest.fixture
def bootstrapped(suite_file: SuiteFile, provider: GenerationProvider) -> SuiteFile:
    render_references(suite_file, provider)
    return suite_file


@pytest.fixture
def evaluator(provider: GenerationProvider, suite_file: SuiteFile) -> Evaluator:
    return Evaluator(
        provider=provider,
        embedder=get_embedder(),
        policy=suite_file.policy,
        select_k=suite_file.select_k,
        select_lambda=suite_file.select_lambda,
    )
