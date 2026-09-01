"""HTTP surface. Optional: install the ``api`` extra to use it."""

__all__ = ["create_app"]


def __getattr__(name: str) -> object:
    """Import lazily so ``identitylock`` stays importable without fastapi."""
    if name == "create_app":
        from identitylock.api.app import create_app

        return create_app
    raise AttributeError(name)
