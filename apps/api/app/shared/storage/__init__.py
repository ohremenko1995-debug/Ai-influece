"""S3-compatible object storage (MinIO locally, S3 in production)."""

from app.shared.storage.s3 import ObjectStorage, build_object_storage

__all__ = ["ObjectStorage", "build_object_storage"]
