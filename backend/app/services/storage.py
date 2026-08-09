import logging
import time
from typing import Optional
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.crypto import decrypt_secret

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 30
_cache: Optional[dict] = None
_cache_expires_at: float = 0.0


def invalidate_storage_config_cache() -> None:
    """Call after any admin mutation to storage_config so the new/changed config
    takes effect immediately instead of waiting out the TTL."""
    global _cache, _cache_expires_at
    _cache = None
    _cache_expires_at = 0.0


async def get_active_storage_credentials(db: AsyncSession) -> Optional[dict]:
    """
    Look up active R2 storage configuration from public.storage_config table.
    Cached for _CACHE_TTL_SECONDS (matches ricotdin's lib/storage/config.ts) since
    this is resolved on every presigned-upload call — without the cache it's a
    fresh decrypt + DB round-trip per upload. A resolve failure (no active row,
    decrypt error) is cached as None too, same as a hit, so a persistently broken
    config doesn't hammer the database on every call either.
    """
    global _cache, _cache_expires_at

    now = time.monotonic()
    if _cache is not None and now < _cache_expires_at:
        return _cache

    sql = text("""
        SELECT id, provider, account_id, access_key_id, bucket, secret_ciphertext, secret_iv, secret_auth_tag
        FROM public.storage_config
        WHERE provider = 'r2' AND status = 'active'
        ORDER BY created_at DESC
        LIMIT 1
    """)
    res = await db.execute(sql)
    row = res.fetchone()

    result: Optional[dict] = None
    if row:
        try:
            secret_key = decrypt_secret(row[5], row[6], row[7])
            result = {
                "id": str(row[0]),
                "provider": row[1],
                "account_id": row[2],
                "access_key_id": row[3],
                "bucket": row[4],
                "secret_access_key": secret_key,
            }
        except Exception as e:
            logger.error(f"Failed to decrypt active storage credentials: {e}")
            result = None

    _cache = result
    _cache_expires_at = now + _CACHE_TTL_SECONDS
    return result


def test_r2_connection(
    account_id: str,
    access_key_id: str,
    secret_access_key: str,
    bucket: str,
) -> tuple[bool, str]:
    """
    Cheap connectivity check (HeadBucket) so bad credentials never get silently
    persisted — without this, a typo'd secret or wrong bucket only surfaces the
    first time someone actually tries to upload.
    Returns (ok, detail).
    """
    try:
        import boto3
        from botocore.config import Config
        from botocore.exceptions import ClientError, EndpointConnectionError

        endpoint_url = f"https://{account_id}.r2.cloudflarestorage.com"
        s3_client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            config=Config(signature_version="s3v4"),
            region_name="auto",
        )
        s3_client.head_bucket(Bucket=bucket)
        return True, "Connection OK"
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "Unknown")
        return False, f"R2 rejected the request: {code}"
    except EndpointConnectionError as e:
        return False, f"Could not reach R2 endpoint: {e}"
    except ImportError:
        return False, "boto3 is not installed on the server."
    except Exception as e:
        return False, f"Connection test failed: {e}"


def generate_r2_presigned_upload_url(
    account_id: str,
    access_key_id: str,
    secret_access_key: str,
    bucket: str,
    object_key: str,
    content_type: str = "audio/webm",
    expiration_seconds: int = 3600,
) -> Optional[str]:
    """
    Generate an S3/R2 presigned PUT URL for direct client uploads.
    """
    try:
        import boto3
        from botocore.config import Config

        endpoint_url = f"https://{account_id}.r2.cloudflarestorage.com"
        s3_client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            config=Config(signature_version="s3v4"),
            region_name="auto",
        )

        presigned_url = s3_client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": bucket,
                "Key": object_key,
                "ContentType": content_type,
            },
            ExpiresIn=expiration_seconds,
        )
        return presigned_url
    except Exception as e:
        logger.warning(f"boto3 presigned URL generation failed or not installed: {e}")
        return None
