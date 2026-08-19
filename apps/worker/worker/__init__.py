"""ARQ worker process.

Holds the worker's runtime settings and nothing else. The domain — models,
services, repositories — lives in `apps/api/app` and is imported from there, so
there is one source of truth for the rules regardless of which process type is
executing them (docs/adr/0001-modular-monolith.md).
"""
