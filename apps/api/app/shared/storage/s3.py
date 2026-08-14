"""Object storage client.

Scope note: this slice provides connection handling and the health probe only.
Presigned upload/download URLs and asset ingestion arrive with the Asset Library
(MVP step 3) — the surface is intentionally not stubbed out ahead of that work.

boto3 is synchronous. Its calls are dispatched to a thread so an async request
handler is never blocked.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import boto3
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import Settings
from app.shared.observability.logging import get_logger

if TYPE_CHECKING:  # pragma: no cover - typing only
    from mypy_boto3_s3.client import S3Client

_logger = get_logger(__name__)


class ObjectStorage:
    """Bucket-scoped wrapper over an S3-compatible endpoint."""

    def __init__(self, client: S3Client, bucket: str) -> None:
        self._client = client
        self._bucket = bucket

    @property
    def bucket(self) -> str:
        return self._bucket

    async def check_bucket(self) -> bool:
        """Liveness probe: does the configured bucket exist and answer?"""
        try:
            await asyncio.to_thread(self._client.head_bucket, Bucket=self._bucket)
        except (ClientError, BotoCoreError) as exc:
            _logger.warning("object_storage_unreachable", bucket=self._bucket, error=str(exc))
            return False
        return True

    async def ensure_bucket(self) -> None:
        """Create the bucket when missing. Used by local bootstrap, not by requests."""
        if await self.check_bucket():
            return
        await asyncio.to_thread(self._client.create_bucket, Bucket=self._bucket)
        _logger.info("object_storage_bucket_created", bucket=self._bucket)


def build_object_storage(settings: Settings) -> ObjectStorage:
    """Construct an `ObjectStorage` for the configured endpoint.

    `s3_endpoint_url` is what the server can reach; `s3_public_endpoint_url` is
    what a browser can reach. They differ under Docker Compose, which is why
    presigning (step 3) must sign against the public endpoint.
    """
    client_kwargs: dict[str, Any] = {
        "endpoint_url": settings.s3_endpoint_url,
        "region_name": settings.s3_region,
        "aws_access_key_id": settings.s3_access_key_id,
        "aws_secret_access_key": settings.s3_secret_access_key,
        "config": Config(
            signature_version="s3v4",
            s3={"addressing_style": "path" if settings.s3_force_path_style else "auto"},
            retries={"max_attempts": 3, "mode": "standard"},
        ),
    }
    client: S3Client = boto3.client("s3", **client_kwargs)
    return ObjectStorage(client, settings.s3_bucket)
