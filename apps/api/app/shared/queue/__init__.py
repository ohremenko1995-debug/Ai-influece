"""Redis-backed job queue (ARQ).

Only workers execute generation jobs. The API enqueues and reads status; it never
calls a generation provider itself — see docs/adr/0004-comfyui-adapter.md.
"""

from app.shared.queue.redis import (
    JobQueue,
    build_redis_settings,
    check_redis,
)

__all__ = ["JobQueue", "build_redis_settings", "check_redis"]
