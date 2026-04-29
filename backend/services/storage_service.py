from __future__ import annotations

import logging
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


def upload_to_r2(session_id: str, filename: str, content: Union[bytes, str]) -> str | None:
    key = f"sessions/{session_id}/{filename}"
    print("\n[DEBUG R2 UPLOAD]")
    print("session_id:", session_id)
    print("filename:", filename)
    print("content length:", len(content) if content else 0)

    if not content:
        print("[ERROR] Empty content. Skipping upload.")
        return None

    try:
        _get_s3_client().put_object(
            Bucket=settings.CLOUDFLARE_R2_BUCKET_NAME,
            Key=key,
            Body=_coerce_bytes(content),
        )
        print("[SUCCESS] Uploaded to R2:", key)
        return key
    except Exception as exc:
        logger.exception("R2 upload failed for key %s", key)
        print("[ERROR] R2 upload failed:", str(exc))
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
            print("[CLEANUP] No files found for session:", session_id)
            return

        client.delete_objects(
            Bucket=settings.CLOUDFLARE_R2_BUCKET_NAME,
            Delete={
                "Objects": objects,
                "Quiet": True,
            },
        )
        print(f"[CLEANUP] Deleted {len(objects)} R2 files for session:", session_id)
    except Exception as exc:
        logger.exception("R2 delete failed for session %s", session_id)
        print("[CLEANUP ERROR] R2 delete failed:", str(exc))
