#!/usr/bin/env python3
"""Check a single video for SEI and disengagement data."""

import argparse
import csv
import logging
import os
import sys
from pathlib import Path
from typing import Any, Optional

from sei_data.src.logging_config import setup_logging
from sei_data.src.s3_downloader import download_video_from_s3_sync, check_s3_video_exists_sync, parse_s3_uri
from sei_data.src.sei_extractor import check_video_has_sei, extract_sei_from_video
from sei_data.src.utils import generate_timestamp


def setup_csv_outputs(output_dir: Path) -> tuple[Path, Path]:
    """Create output CSV file paths for SEI and disengagement data.

    Args:
        output_dir: Base output directory

    Returns:
        Tuple of (sei_csv_path, disengagement_csv_path)
    """
    timestamp = generate_timestamp()
    sei_csv_path = output_dir + f"/sei_data_{timestamp}.csv"
    disengagement_csv_path = output_dir + f"/disengagement_data_{timestamp}.csv"
    return sei_csv_path, disengagement_csv_path


def save_sei_to_csv(sei_data: list[dict[str, Any]], csv_path: Path) -> None:
    """Save SEI metadata to CSV file.

    Args:
        sei_data: List of SEI metadata dictionaries
        csv_path: Path to save CSV file
    """
    if not sei_data:
        logging.getLogger(__name__).warning(f"No SEI data to save to {csv_path}")
        return

    # Flatten the nested dictionary structure
    flattened_data = []
    for frame_data in sei_data:
        flat_row = {}
        for key, value in frame_data.items():
            if isinstance(value, dict):
                for subkey, subvalue in value.items():
                    flat_row[f"{key}_{subkey}"] = subvalue
            elif isinstance(value, (list, dict)):
                flat_row[key] = str(value)
            else:
                flat_row[key] = value
        flattened_data.append(flat_row)

    if flattened_data:
        fieldnames = set()
        for row in flattened_data:
            fieldnames.update(row.keys())

        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=sorted(fieldnames))
            writer.writeheader()
            writer.writerows(flattened_data)

        logger = logging.getLogger(__name__)
        logger.info(f"Saved {len(sei_data)} SEI frames to {csv_path}")


def save_disengagement_to_csv(
    dmp_id: int,
    org_id: str,
    key_id: str,
    vin: Optional[str],
    disengagement_events: list[dict[str, Any]],
    csv_path: Path,
) -> None:
    """Save disengagement events to CSV file.

    Args:
        dmp_id: DMP ID
        org_id: Organization ID
        key_id: Key ID
        vin: Vehicle VIN (optional)
        disengagement_events: List of disengagement event dictionaries
        csv_path: Path to save CSV file
    """
    logger = logging.getLogger(__name__)

    if not disengagement_events:
        logger.warning(f"No disengagement events to save to {csv_path}")
        return

    # Prepare rows with DMP metadata
    rows = []
    for event in disengagement_events:
        row = {
            "dmp_id": dmp_id,
            "org_id": org_id,
            "key_id": key_id,
            "vin": vin,
            "event_id": event.get("event_id", ""),
            "event": event.get("event", ""),
            "timestamp": event.get("timestamp", ""),
        }
        rows.append(row)

    if rows:
        fieldnames = ["dmp_id", "org_id", "key_id", "vin", "event_id", "event", "timestamp"]
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

        logger.info(f"Saved {len(disengagement_events)} disengagement events to {csv_path}")


def get_sei_data(video_uri, output_dir = "sei_data", aws_key=None, aws_secret=None, dmp_id= 0, org_id="unknown", key_id="unknown", vin=None):
    """Main function to check a single video for SEI and disengagement data."""




    timestamp = generate_timestamp()
    log_path = output_dir + f"/check_single_video_{timestamp}.log"

    try:
        os.mkdir(output_dir)
    except (OSError, PermissionError) as e:
        print(f"Error: Cannot create log file directory: {e}", file=sys.stderr)
        return False, '', ''

    setup_logging(log_file=str(log_path))
    logger = logging.getLogger(__name__)

    logger.info(f"Starting single video check for: {video_uri}")

    try:
        # Check if video exists on S3
        logger.info("Checking if video exists on S3...")
        video_exists = check_s3_video_exists_sync(video_uri, aws_key, aws_secret)
        if not video_exists:
            logger.error(f"Video does not exist on S3: {video_uri}")
            print(f"this file has no dmps with disengagement tags")
            return False, '', ''

        logger.info("Video found on S3. Downloading...")

        # Download video
        videos_dir = output_dir + "/video"
        os.mkdir(videos_dir)
        
        # Extract filename from S3 URI
        try:
            _, key = parse_s3_uri(video_uri)
            filename = key.split("/")[-1]
        except ValueError:
            filename = "downloaded_video.mp4"
        
        video_path = videos_dir +'/'+ filename
        success = download_video_from_s3_sync(video_uri, video_path, aws_key, aws_secret)

        if not success:
            logger.error(f"Failed to download video from S3: {video_uri}")
            print(f"this file has no dmps with disengagement tags")
            return False, ''

        logger.info(f"Video downloaded to: {video_path}")

        # Check if video has SEI data
        logger.info("Checking if video has SEI data...")
        has_sei = check_video_has_sei(video_path)

        if not has_sei:
            logger.warning("Video does not contain SEI data")
            print(f"this file has no dmps with disengagement tags")
            return False, '', ''

        logger.info("Video contains SEI data. Extracting...")

        # Extract SEI data
        sei_data = extract_sei_from_video(video_path)

        if not sei_data:
            logger.warning("Failed to extract SEI data from video")
            print(f"this file has no dmps with disengagement tags")
            return False, '', ''

        logger.info(f"Extracted {len(sei_data)} SEI frames")

        # Setup CSV output paths
        sei_csv_path, disengagement_csv_path = setup_csv_outputs(output_dir)

        # Save SEI data to CSV
        save_sei_to_csv(sei_data, sei_csv_path)

        # For now, create a placeholder disengagement CSV with DMP metadata
        # If you have specific disengagement events to extract, modify this section
        disengagement_events = [
            {
                "event_id": "sei_extracted",
                "event": f"SEI data extracted from video ({len(sei_data)} frames)",
                "timestamp": None,
            }
        ]

        save_disengagement_to_csv(
            dmp_id=dmp_id,
            org_id=org_id,
            key_id=key_id,
            vin=vin,
            disengagement_events=disengagement_events,
            csv_path=disengagement_csv_path,
        )

        logger.info("=" * 80)
        logger.info("PROCESSING COMPLETE")
        logger.info("=" * 80)
        logger.info(f"SEI data saved to: {sei_csv_path}")
        logger.info(f"Disengagement data saved to: {disengagement_csv_path}")
        logger.info(f"Video saved to: {video_path}")
        logger.info("=" * 80)

        print(f"Successfully processed video")
        print(f"SEI data: {sei_csv_path}")
        print(f"Disengagement data: {disengagement_csv_path}")
        return True, sei_csv_path, video_path

    except Exception as e:
        logger.exception(f"Error processing video: {e}")
        return False, '', ''

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Compute relative speeds from QDTrack, depth, and SEI data."
    )
    parser.add_argument(
        "--video_uri",
        type=str,
        required=True,
        help="S3 URI of the video file.",
    )
    parser.add_argument(
        "--out_dir",
        type=str,
        default=None,
        help="Optional path to the output directory.",
    )
    parser.add_argument("aws_key", type=str, help="AWS Access Key for S3 access.")
    parser.add_argument("aws_secret", type=str, help="AWS Secret Key for S3 access.")

    args = parser.parse_args()

    get_sei_data(
        video_uri=args.video_uri,
        output_dir=args.out_dir,
        aws_key=args.aws_key,
        aws_secret=args.aws_secret,
    )