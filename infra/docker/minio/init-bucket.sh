#!/bin/sh
# Provisions the asset bucket in MinIO. Idempotent: safe to re-run.
#
# Deliberately does NOT grant anonymous read. Assets are private and always
# served through short-lived presigned URLs issued by the API.
set -eu

BUCKET="${S3_BUCKET:-influenceros-assets}"

mc alias set local "${S3_ENDPOINT_URL:-http://minio:9000}" \
  "${S3_ACCESS_KEY_ID:-influenceros}" "${S3_SECRET_ACCESS_KEY:-influenceros}"

if mc ls "local/${BUCKET}" >/dev/null 2>&1; then
  echo "init-bucket: bucket ${BUCKET} already exists"
else
  mc mb "local/${BUCKET}"
  echo "init-bucket: created bucket ${BUCKET}"
fi

# Versioning gives us object-level recovery for generated production assets.
mc version enable "local/${BUCKET}" || echo "init-bucket: versioning unavailable, continuing"

# Browser uploads go straight to MinIO via presigned PUT, so the bucket needs
# permissive CORS for the local web origin only.
mc anonymous set none "local/${BUCKET}"

echo "init-bucket: done"
