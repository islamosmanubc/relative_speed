"""Batch video processing for SEI detection and download."""

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

try:
    import psutil

    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

from .config import (
    ADAPTIVE_BATCH_ENABLED,
    ADAPTIVE_BATCH_MAX,
    ADAPTIVE_BATCH_MIN,
    ADAPTIVE_BATCH_MEMORY_THRESHOLD_LOW,
    ADAPTIVE_BATCH_MEMORY_THRESHOLD_MEDIUM,
    DEFAULT_BATCH_SIZE,
)
from .s3_downloader import check_s3_video_exists, download_video_from_s3
from .sei_extractor import check_video_has_sei

logger = logging.getLogger(__name__)


def load_analysis_results(json_path: Path) -> dict[str, Any]:
    """Load analysis results from JSON file.

    Args:
        json_path: Path to analysis results JSON

    Returns:
        Analysis results dictionary
    """
    with open(json_path) as f:
        return json.load(f)


def save_analysis_results(data: dict[str, Any], json_path: Path) -> None:
    """Save analysis results to JSON file.

    Args:
        data: Analysis results dictionary
        json_path: Path to save JSON file
    """
    with open(json_path, "w") as f:
        json.dump(data, f, indent=2, default=str)
    logger.info(f"Updated analysis results saved to {json_path}")


def _get_unchecked_dmps(dmps: list[dict[str, Any]], videos_dir: Path = None) -> list[dict[str, Any]]:
    """Filter DMPs that haven't been checked yet or have download failures.

    Args:
        dmps: List of DMP records
        videos_dir: Optional videos directory (unused, kept for compatibility)

    Returns:
        List of unchecked DMPs (haven't been checked or have download_failed flag)
    """
    unchecked = []
    for dmp in dmps:
        if not dmp.get("video_uris", {}).get("front"):
            continue

        sei_checked = dmp.get("sei_checked")
        download_failed = dmp.get("download_failed")

        # Skip if already checked and no download failure
        if sei_checked is True and not download_failed:
            # Already processed - skip it
            continue

        # Include if not checked or has download failure
        unchecked.append(dmp)

    return unchecked


def get_optimal_batch_size() -> int:
    """Calculate optimal batch size based on system resources.

    Returns:
        Optimal batch size (between ADAPTIVE_BATCH_MIN and ADAPTIVE_BATCH_MAX)
    """
    if not ADAPTIVE_BATCH_ENABLED or not PSUTIL_AVAILABLE:
        return DEFAULT_BATCH_SIZE

    try:
        cpu_count = os.cpu_count() or 4
        memory_gb = psutil.virtual_memory().total / (1024**3)

        if memory_gb < ADAPTIVE_BATCH_MEMORY_THRESHOLD_LOW:
            optimal = ADAPTIVE_BATCH_MIN
        elif memory_gb < ADAPTIVE_BATCH_MEMORY_THRESHOLD_MEDIUM:
            optimal = 5
        else:
            optimal = min(ADAPTIVE_BATCH_MAX, cpu_count * 2)

        logger.debug(f"Adaptive batch size: {optimal} (CPU: {cpu_count}, Memory: {memory_gb:.1f}GB)")
        return optimal
    except Exception as e:
        logger.warning(f"Error calculating optimal batch size, using default: {e}")
        return DEFAULT_BATCH_SIZE


def check_videos_for_sei(
    json_path: Path,
    videos_dir: Path,
    batch_size: int = None,
    start_index: int = 0,
    process_all: bool = False,
) -> dict[str, Any]:
    """Check videos for SEI data and update JSON.

    Processes videos in batches, checks for SEI, and updates JSON with results.
    Skips videos that already exist locally and reuses existing files.
    Only processes videos that haven't been checked yet.

    Args:
        json_path: Path to analysis results JSON
        videos_dir: Directory to store videos
        batch_size: Number of videos to process concurrently in each batch.
            If None, uses adaptive batch sizing based on system resources.
        start_index: Starting index in unchecked DMPs list (for resuming)
        process_all: If True, process all remaining videos automatically

    Returns:
        Updated analysis results dictionary with batch_stats key added
    """
    # Use adaptive batch sizing if not specified
    if batch_size is None:
        batch_size = get_optimal_batch_size()
    results = load_analysis_results(json_path)
    dmps = results.get("dmps", [])

    videos_dir.mkdir(parents=True, exist_ok=True)

    total_batch_checked = 0
    total_batch_with_sei = 0
    current_index = start_index
    first_iteration = True

    while True:
        unchecked_dmps = _get_unchecked_dmps(dmps, videos_dir)

        if not unchecked_dmps:
            logger.info("All videos have been checked for SEI data")
            break

        if process_all and not first_iteration:
            current_index = 0

        if current_index >= len(unchecked_dmps):
            logger.info("Reached end of unchecked videos")
            break

        logger.info(f"Found {len(unchecked_dmps)} videos remaining to check (starting from index {current_index})")
        logger.info(f"Processing batch of {batch_size} videos concurrently...")

        batch = unchecked_dmps[current_index : current_index + batch_size]
        if not batch:
            logger.info("No more videos to process in this batch")
            break

        batch_checked, batch_with_sei = asyncio.run(
            _process_batch_async(batch, unchecked_dmps, videos_dir, current_index)
        )

        total_batch_checked += batch_checked
        total_batch_with_sei += batch_with_sei
        current_index += batch_checked
        first_iteration = False

        results["dmps"] = dmps
        save_analysis_results(results, json_path)

        total_checked = sum(1 for dmp in dmps if dmp.get("sei_checked"))
        total_with_sei = sum(1 for dmp in dmps if dmp.get("sei_available"))

        logger.info(f"Progress: {total_checked}/{len(dmps)} videos checked, {total_with_sei} with SEI data")

        if not process_all:
            break
    total_checked = sum(1 for dmp in dmps if dmp.get("sei_checked"))
    total_with_sei = sum(1 for dmp in dmps if dmp.get("sei_available"))
    results["_batch_stats"] = {
        "batch_checked": total_batch_checked,
        "batch_with_sei": total_batch_with_sei,
        "total_checked": total_checked,
        "total_with_sei": total_with_sei,
        "total_dmps": len(dmps),
    }

    return results


async def _process_batch_async(
    batch: list[dict[str, Any]],
    unchecked_dmps: list[dict[str, Any]],
    videos_dir: Path,
    start_index: int,
) -> tuple[int, int]:
    """Process a batch of videos asynchronously.

    Args:
        batch: List of DMP records to process
        unchecked_dmps: Full list of unchecked DMPs (for progress tracking)
        videos_dir: Directory to store videos
        start_index: Starting index for progress tracking

    Returns:
        Tuple of (batch_checked_count, batch_with_sei_count)
    """
    batch_checked = 0
    batch_with_sei = 0

    # Semaphore to limit concurrent downloads to 2 at a time
    semaphore = asyncio.Semaphore(2)

    async def _process_with_limit(idx: int, dmp: dict[str, Any]) -> tuple[int, bool]:
        """Wrapper to process video with semaphore limit."""
        async with semaphore:
            return await _process_single_video_async(dmp, idx, len(unchecked_dmps), videos_dir)

    # Create tasks for concurrent processing (limited to 2 downloads at a time)
    tasks = []
    for idx, dmp in enumerate(batch, start=start_index):
        task = _process_with_limit(idx, dmp)
        tasks.append(task)

    # Process all videos with limited concurrency
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Process results
    for result in results:
        if isinstance(result, Exception):
            logger.error(f"Error processing video: {result}")
            continue

        checked, has_sei = result
        batch_checked += checked
        if has_sei:
            batch_with_sei += 1

    return batch_checked, batch_with_sei


async def _process_single_video_async(dmp: dict[str, Any], idx: int, total: int, videos_dir: Path) -> tuple[int, bool]:
    """Process a single video asynchronously.

    Skips download and S3 checks if video already exists locally.
    Reuses existing results if video was already processed.

    Args:
        dmp: DMP record to process
        idx: Index for progress tracking
        total: Total number of unchecked videos
        videos_dir: Directory to store videos

    Returns:
        Tuple of (1 if checked else 0, True if has SEI else False)
    """
    dmp_id = dmp["dmp_id"]
    video_uri = dmp.get("video_uris", {}).get("front")

    if not video_uri:
        logger.warning(f"DMP {dmp_id} has no front video URI, skipping")
        dmp["sei_checked"] = True
        dmp["sei_available"] = False
        return (1, False)

    # Determine local video path - use stored path if available, otherwise construct it
    stored_path = dmp.get("local_video_path")
    if stored_path and Path(stored_path).exists():
        local_video_path = Path(stored_path)
        logger.debug(f"DMP {dmp_id}: Using stored local video path: {local_video_path}")
    else:
        video_filename = Path(video_uri).name
        local_video_path = videos_dir / f"dmp_{dmp_id}_{video_filename}"

    # If video already exists locally, skip S3 check and download
    if local_video_path.exists():
        logger.info(f"[{idx + 1}/{total}] Checking DMP {dmp_id}... (video already exists locally)")

        # If already checked and we have the result, skip processing
        if dmp.get("sei_checked") is True and dmp.get("sei_available") is not None:
            logger.debug(
                f"DMP {dmp_id}: Already checked, result: SEI={'available' if dmp.get('sei_available') else 'not available'}"
            )
            # Ensure local_video_path is stored
            if not stored_path:
                dmp["local_video_path"] = str(local_video_path)
            return (1, dmp.get("sei_available", False))

        # Video exists but not checked yet - check for SEI without downloading
        has_sei = check_video_has_sei(local_video_path)
        dmp["sei_checked"] = True
        dmp["sei_available"] = has_sei
        dmp["local_video_path"] = str(local_video_path)

        if dmp.get("download_failed"):
            logger.info(f"DMP {dmp_id}: Found existing video, clearing download_failed flag")
            dmp.pop("download_failed", None)

        if has_sei:
            logger.info(f"DMP {dmp_id}: SEI data found ✓ (from existing file)")
            return (1, True)
        logger.info(f"DMP {dmp_id}: No SEI data found (from existing file)")
        # Don't delete the file - it might be needed for other purposes
        return (1, False)

    # Video doesn't exist locally - check S3 and download
    logger.info(f"[{idx + 1}/{total}] Checking DMP {dmp_id}...")

    if not await check_s3_video_exists(video_uri):
        logger.warning(f"Video not found in S3 for DMP {dmp_id}: {video_uri}")
        dmp["sei_checked"] = True
        dmp["sei_available"] = False
        return (1, False)

    download_success = await download_video_from_s3(video_uri, local_video_path)

    if download_success:
        if dmp.get("download_failed"):
            logger.info(f"DMP {dmp_id}: Retry successful, clearing download_failed flag")
            dmp.pop("download_failed", None)

        has_sei = check_video_has_sei(local_video_path)
        dmp["sei_checked"] = True
        dmp["sei_available"] = has_sei

        if has_sei:
            logger.info(f"DMP {dmp_id}: SEI data found ✓")
            dmp["local_video_path"] = str(local_video_path)
            return (1, True)
        logger.info(f"DMP {dmp_id}: No SEI data found")
        if local_video_path.exists():
            local_video_path.unlink()
        return (1, False)
    logger.error(f"Failed to download video for DMP {dmp_id} after retries")
    dmp["sei_checked"] = True
    dmp["sei_available"] = False
    dmp["download_failed"] = True
    return (1, False)
