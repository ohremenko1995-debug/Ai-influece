"""Bounded contexts.

Each module owns its models, schemas, repository, domain service and router.
Cross-module reads go through the other module's service or repository, never by
reaching into its tables — see docs/adr/0001-modular-monolith.md.
"""
