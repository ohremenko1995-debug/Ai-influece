"""Identity Lock — measurable identity consistency for generated character imagery.

The package is organised in one direction only:

    domain  <-  imaging / embeddings  <-  metrics  <-  selection  <-  evaluation
                                                                        |
                                                        reporting / api / cli

Nothing in ``domain`` imports from a layer above it, and no layer reaches back
down into a provider. See ``docs/architecture.md``.
"""

__version__ = "0.1.0"

REPORT_SCHEMA_VERSION = 2
"""Version of the JSON report contract. Bumped when the shape changes.

2 — the manifest carries the `Policy` a run was judged under and the fingerprint
    of the fitted identity space, so a report can draw its own gate lines and a
    comparison can refuse two runs centred differently. A version-1 `run.json`
    does not load: both fields are required and neither can be inferred.
1 — initial."""

__all__ = ["REPORT_SCHEMA_VERSION", "__version__"]
