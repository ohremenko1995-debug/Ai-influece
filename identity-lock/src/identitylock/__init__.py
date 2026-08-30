"""Identity Lock — measurable identity consistency for generated character imagery.

The package is organised in one direction only:

    domain  <-  imaging / embeddings  <-  metrics  <-  selection  <-  evaluation
                                                                        |
                                                        reporting / api / cli

Nothing in ``domain`` imports from a layer above it, and no layer reaches back
down into a provider. See ``docs/architecture.md``.
"""

__version__ = "0.1.0"

REPORT_SCHEMA_VERSION = 1
"""Version of the JSON report contract. Bumped when the shape changes."""

__all__ = ["REPORT_SCHEMA_VERSION", "__version__"]
