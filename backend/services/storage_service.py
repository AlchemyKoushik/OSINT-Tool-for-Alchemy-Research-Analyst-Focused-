from __future__ import annotations

import logging
import time
from typing import Union

import boto3

from config.settings import settings

_s3_client = None
logger = logging.getLogger(__name__)


def _ensure_r2_config() -> None:
    required_values = {
        "CLOUDFLARE_R2_ACCOUNT_ID": settings.CLOUDFLARE_R2_ACCOUNT_ID,
        "CLOUDFLARE_R2_ACCESS_KEY_ID": settings.CLOUDFLARE_R2_ACCESS_KEY_ID,
        "CLOUDFLARE_R2_SECRET_ACCESS_KEY": settings.CLOUDFLARE_R2_SECRET_ACCESS_KEY,
        "CLOUDFLARE_R2_BUCKET_NAME": settings.CLOUDFLARE_R2_BUCKET_NAME,
    }
    missing = [key for key, value in required_values.items() if not str(value).strip()]
    if missing:
        raise RuntimeError(f"Missing R2 configuration: {', '.join(missing)}")


def _get_s3_client():
    global _s3_client
    if _s3_client is not None:
        return _s3_client

    _ensure_r2_config()
    endpoint = f"https://{settings.CLOUDFLARE_R2_ACCOUNT_ID.strip()}.r2.cloudflarestorage.com"
    _s3_client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=settings.CLOUDFLARE_R2_ACCESS_KEY_ID,
        aws_secret_access_key=settings.CLOUDFLARE_R2_SECRET_ACCESS_KEY,
        region_name=settings.CLOUDFLARE_R2_REGION,
    )
    return _s3_client


def _coerce_bytes(content: Union[bytes, str]) -> bytes:
    if isinstance(content, bytes):
        return content
    return content.encode("utf-8")


def _retry_delay_seconds(retry_index: int) -> int:
    return min(2**retry_index, 4)


def upload_to_r2(session_id: str, filename: str, content: Union[bytes, str]) -> str | None:
    key = f"sessions/{session_id}/{filename}"
    if not content:
        logger.warning("R2 upload skipped for empty content key=%s", key)
        return None

    last_error: Exception | None = None
    for retry_index in range(settings.CLEANUP_MAX_RETRIES + 1):
        try:
            _get_s3_client().put_object(
                Bucket=settings.CLOUDFLARE_R2_BUCKET_NAME,
                Key=key,
                Body=_coerce_bytes(content),
            )
            logger.info("R2 upload succeeded key=%s", key)
            return key
        except Exception as exc:
            last_error = exc
            logger.warning("R2 upload failed key=%s attempt=%s error=%s", key, retry_index + 1, exc)
            if retry_index < settings.CLEANUP_MAX_RETRIES:
                time.sleep(_retry_delay_seconds(retry_index))

    logger.exception("R2 upload failed key=%s", key, exc_info=last_error)
    return None


def read_from_r2(key: str) -> bytes:
    try:
        response = _get_s3_client().get_object(
            Bucket=settings.CLOUDFLARE_R2_BUCKET_NAME,
            Key=key,
        )
        return response["Body"].read()
    except Exception:
        logger.exception("R2 read failed for key %s", key)
        raise


def delete_session_prefix(session_id: str) -> None:
    prefix = f"sessions/{session_id}/"
    last_error: Exception | None = None

    for retry_index in range(settings.CLEANUP_MAX_RETRIES + 1):
        try:
            client = _get_s3_client()
            continuation_token = None
            objects = []

            while True:
                request_kwargs = {
                    "Bucket": settings.CLOUDFLARE_R2_BUCKET_NAME,
                    "Prefix": prefix,
                }
                if continuation_token:
                    request_kwargs["ContinuationToken"] = continuation_token

                response = client.list_objects_v2(**request_kwargs)
                contents = response.get("Contents", [])
                objects.extend({"Key": item["Key"]} for item in contents if str(item.get("Key", "")).strip())

                if not response.get("IsTruncated"):
                    break
                continuation_token = response.get("NextContinuationToken")

            if not objects:
                logger.info("Session deleted session_id=%s store=r2 objects=0", session_id)
                return

            client.delete_objects(
                Bucket=settings.CLOUDFLARE_R2_BUCKET_NAME,
                Delete={
                    "Objects": objects,
                    "Quiet": True,
                },
            )
            logger.info("Session deleted session_id=%s store=r2 objects=%s", session_id, len(objects))
            return
        except Exception as exc:
            last_error = exc
            logger.warning(
                "Cleanup failed session_id=%s store=r2 attempt=%s error=%s",
                session_id,
                retry_index + 1,
                exc,
            )
            if retry_index < settings.CLEANUP_MAX_RETRIES:
                time.sleep(_retry_delay_seconds(retry_index))

    logger.exception("Cleanup failed session_id=%s store=r2", session_id, exc_info=last_error)
    raise RuntimeError(f"R2 delete failed for session {session_id}") from last_error
