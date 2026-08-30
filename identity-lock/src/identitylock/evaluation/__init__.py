"""Orchestration: suites, runs, comparisons and where they live on disk."""

from identitylock.evaluation.bootstrap import render_references
from identitylock.evaluation.regression import METRICS, ComparisonError, compare
from identitylock.evaluation.runner import Cohort, EvaluationError, Evaluator, reference_paths
from identitylock.evaluation.store import (
    list_comparisons,
    list_runs,
    load_comparison,
    load_run,
    save_comparison,
    save_run,
)
from identitylock.evaluation.suite import SuiteFile, SuiteFileError, load_suite_file

__all__ = [
    "METRICS",
    "Cohort",
    "ComparisonError",
    "EvaluationError",
    "Evaluator",
    "SuiteFile",
    "SuiteFileError",
    "compare",
    "list_comparisons",
    "list_runs",
    "load_comparison",
    "load_run",
    "load_suite_file",
    "reference_paths",
    "render_references",
    "save_comparison",
    "save_run",
]
