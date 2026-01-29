"""Async S3 video download utilities using aioboto3 and BytesIO."""

import asyncio
import functools
import logging
from io import BytesIO
import os
from pathlib import Path
from typing import Any, Callable, TypeVar
from urllib.parse import urlparse

import aioboto3
from botocore.exceptions import ClientError

from .config import (
    S3_INITIAL_RETRY_DELAY,
    S3_MAX_RETRIES,
    S3_MAX_RETRY_DELAY,
)

logger = logging.getLogger(__name__)

# Retry configuration (aliases for backward compatibility)
MAX_RETRIES = S3_MAX_RETRIES
INITIAL_RETRY_DELAY = S3_INITIAL_RETRY_DELAY
MAX_RETRY_DELAY = S3_MAX_RETRY_DELAY

_session = None

T = TypeVar("T")


def get_session(aws_key, aws_secret) -> aioboto3.Session:
    """Get or create shared aioboto3 session instance."""
    global _session  # noqa: PLW0603
    if _session is None:
        _session = aioboto3.Session(
            aws_access_key_id=aws_key,
            aws_secret_access_key=aws_secret,
            region_name='us-west-2'
        )
    return _session


def parse_s3_uri(s3_uri: str) -> tuple[str, str]:
    """Parse S3 URI into bucket and key.

    Args:
        s3_uri: S3 URI (e.g., s3://bucket/path/to/file.mp4)

    Returns:
        Tuple of (bucket, key)

    Raises:
        ValueError: If URI format is invalid
    """
    if not s3_uri.startswith("s3://"):
        raise ValueError(f"Invalid S3 URI format: {s3_uri}")

    parsed = urlparse(s3_uri)
    bucket = parsed.netloc
    key = parsed.path.lstrip("/")

    if not bucket or not key:
        raise ValueError(f"Invalid S3 URI: missing bucket or key in {s3_uri}")

    return bucket, key


def _is_retryable_error(error: Exception) -> bool:
    """Check if an error is retryable (transient network issues).

    Args:
        error: Exception to check

    Returns:
        True if error is retryable, False otherwise
    """
    # Retry on connection errors, timeouts, and incomplete payloads
    error_str = str(error).lower()
    retryable_keywords = [
        "connection reset",
        "connection timeout",
        "timeout",
        "not enough data",
        "contentlengtherror",
        "connectionerror",
    ]
    return any(keyword in error_str for keyword in retryable_keywords)


def _calculate_retry_delay(attempt: int) -> float:
    """Calculate exponential backoff delay for retry attempt.

    Args:
        attempt: Retry attempt number (0-indexed, so first retry is attempt=1)

    Returns:
        Delay in seconds (capped at S3_MAX_RETRY_DELAY)
    """
    return min(S3_INITIAL_RETRY_DELAY * (2 ** (attempt - 1)), S3_MAX_RETRY_DELAY)


def async_retry(
    max_retries: int = S3_MAX_RETRIES,
    is_retryable: Callable[[Exception], bool] = _is_retryable_error,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator for async functions with retry logic and exponential backoff.

    Args:
        max_retries: Maximum number of retry attempts
        is_retryable: Function to check if an error is retryable

    Returns:
        Decorator function
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_error = None
            for attempt in range(max_retries + 1):
                try:
                    if attempt > 0:
                        delay = _calculate_retry_delay(attempt)
                        logger.info(
                            f"Retrying {func.__name__} (attempt {attempt + 1}/{max_retries + 1}) after {delay}s..."
                        )
                        await asyncio.sleep(delay)
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_error = e
                    # Check if error is retryable and we haven't exhausted retries
                    if not is_retryable(e) or attempt >= max_retries:
                        logger.error(f"{func.__name__} failed after {attempt + 1} attempts: {e}")
                        raise
                    logger.warning(f"Retryable error in {func.__name__} on attempt {attempt + 1}: {e}")

            # Should not reach here, but just in case
            if last_error:
                raise last_error
            raise RuntimeError(f"{func.__name__} failed after {max_retries + 1} attempts")

        return wrapper

    return decorator


def _is_s3_retryable_error(error: Exception) -> bool:
    """Check if S3 error is retryable, excluding 404 errors.

    Args:
        error: Exception to check

    Returns:
        True if error is retryable, False otherwise
    """
    # 404 errors are not retryable
    if isinstance(error, ClientError):
        error_code = error.response.get("Error", {}).get("Code", "")
        if error_code == "404":
            return False
    return _is_retryable_error(error)


async def _download_video_core(s3_uri: str, local_path: Path, aws_key: str, aws_secret: str) -> bool:
    """Core download logic without retry handling.

    Args:
        s3_uri: S3 URI of the video file
        local_path: Local path to save the video

    Returns:
        True if download successful, False otherwise

    Raises:
        ClientError: For S3 errors (404 will be caught by caller)
        Exception: For other errors
    """
    bucket, key = parse_s3_uri(s3_uri)
    session = get_session(aws_key, aws_secret)

    logger.info(f"Downloading {s3_uri} to {local_path}")

    async with session.client("s3") as s3_client:
        # Download to BytesIO buffer first (more efficient)
        buffer = BytesIO()
        await s3_client.download_fileobj(bucket, key, buffer)

        # Write buffer to file
        buffer.seek(0)
        with open(local_path, "wb") as f:
            f.write(buffer.getvalue())

    logger.info(f"Successfully downloaded to {local_path}")
    return True


@async_retry(max_retries=S3_MAX_RETRIES, is_retryable=_is_s3_retryable_error)
async def download_video_from_s3(s3_uri: str, local_path: Path, max_retries: int = S3_MAX_RETRIES) -> bool:
    """Download video file from S3 to local path.

    Implements retry logic with exponential backoff for transient errors.
    Skips download if file already exists locally.

    Args:
        s3_uri: S3 URI of the video file
        local_path: Local path to save the video
        max_retries: Maximum number of retry attempts (ignored, uses decorator value)

    Returns:
        True if download successful, False otherwise
    """
    try:
        bucket, key = parse_s3_uri(s3_uri)
    except ValueError as e:
        logger.error(f"Invalid S3 URI: {e}")
        return False



    try:
        return await _download_video_core(s3_uri, local_path)
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "")
        if error_code == "404":
            logger.error(f"Video not found in S3: {s3_uri}")
            return False
        raise
    except Exception:
        raise


async def check_s3_video_exists(s3_uri: str, aws_key: str, aws_secret: str) -> bool:
    """Check if video file exists in S3 using async/await.

    Args:
        s3_uri: S3 URI of the video file

    Returns:
        True if file exists, False otherwise
    """
    try:
        bucket, key = parse_s3_uri(s3_uri)
    except ValueError:
        return False

    session = get_session(aws_key, aws_secret)
    try:
        async with session.client("s3") as s3_client:
            await s3_client.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "")
        if error_code == "404":
            logger.warning(f"Video not found in S3: {s3_uri}")
        else:
            logger.error(f"Error checking S3 video: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error checking S3 video: {e}")
        return False


# Synchronous wrapper functions for backward compatibility
def download_video_from_s3_sync(s3_uri: str, local_path: Path, aws_key: str, aws_secret: str) -> bool:
    """Synchronous wrapper for download_video_from_s3.

    Args:
        s3_uri: S3 URI of the video file
        local_path: Local path to save the video

    Returns:
        True if download successful, False otherwise
    """
    return asyncio.run(download_video_from_s3(s3_uri, local_path, aws_key, aws_secret))


def check_s3_video_exists_sync(s3_uri: str, aws_key: str, aws_secret: str) -> bool:
    """Synchronous wrapper for check_s3_video_exists.

    Args:
        s3_uri: S3 URI of the video file

    Returns:
        True if file exists, False otherwise
    """
    return asyncio.run(check_s3_video_exists(s3_uri, aws_key, aws_secret))
