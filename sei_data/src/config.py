"""Centralized configuration for disengagement SEI analyzer."""

import os
from pathlib import Path
from typing import Final

# Project root directory (parent of src/)
PROJECT_ROOT = Path(__file__).parent.parent

# Output directories
OUTPUTS_DIR: Final[Path] = PROJECT_ROOT / "outputs"
VIDEOS_DIR: Final[Path] = OUTPUTS_DIR / "videos"

# Viewer directories
VIEWER_DIR: Final[Path] = PROJECT_ROOT / "viewer"
VIEWER_STATUS_FILE: Final[Path] = VIEWER_DIR / "video_status.json"

# DynamoDB table names
VEHICLE_TABLE: Final[str] = "TeslaVehicle-up4zzmiar5bkto74uqba2bjmqy-staging"
KEY_TABLE: Final[str] = "Key-up4zzmiar5bkto74uqba2bjmqy-staging"

# Vehicle filtering requirements
MIN_VERSION: Final[tuple[int, int, int, int]] = (2025, 44, 25, 1)
REQUIRED_DRIVER_ASSIST: Final[str] = "TeslaAP4"

# S3 download retry configuration
S3_MAX_RETRIES: Final[int] = 3
S3_INITIAL_RETRY_DELAY: Final[int] = 1  # seconds
S3_MAX_RETRY_DELAY: Final[int] = 10  # seconds

# Video processing defaults
DEFAULT_BATCH_SIZE: Final[int] = 50
DEFAULT_START_INDEX: Final[int] = 0

# Adaptive batch sizing configuration
ADAPTIVE_BATCH_ENABLED: Final[bool] = os.getenv("ADAPTIVE_BATCH_ENABLED", "true").lower() == "true"

# Viewer server configuration
VIEWER_PORT: Final[int] = int(os.getenv("VIEWER_PORT", "8000"))
VIEWER_CACHE_TTL: Final[int] = 300  # seconds (5 minutes)

# Database configuration (loaded from environment)
DB_CONFIG = {
    "host": os.getenv(
        "DB_HOST",
        "matt3r-aurora-catalog-cluster.cluster-ro-cbbarg1ot9rc.us-west-2.rds.amazonaws.com",
    ),
    "port": os.getenv("DB_PORT", "5432"),
    "database": os.getenv("DB_NAME", "postgres"),
    "user": os.getenv("DB_USER", "postgres"),
}

# Database connection pool configuration
DB_POOL_MIN_CONN: Final[int] = int(os.getenv("DB_POOL_MIN_CONN", "1"))
DB_POOL_MAX_CONN: Final[int] = int(os.getenv("DB_POOL_MAX_CONN", "10"))

# Database query batching configuration
DB_QUERY_BATCH_SIZE: Final[int] = int(os.getenv("DB_QUERY_BATCH_SIZE", "50"))

# Vehicle lookup configuration
VEHICLE_LOOKUP_MAX_WORKERS: Final[int] = int(os.getenv("VEHICLE_LOOKUP_MAX_WORKERS", "50"))
VEHICLE_LOOKUP_BOTO3_POOL_HEADROOM: Final[int] = 10
VEHICLE_LOOKUP_PROGRESS_INTERVAL: Final[int] = 50

# Adaptive batch sizing thresholds
ADAPTIVE_BATCH_MIN: Final[int] = 3
ADAPTIVE_BATCH_MAX: Final[int] = 10
ADAPTIVE_BATCH_MEMORY_THRESHOLD_LOW: Final[int] = 8  # GB
ADAPTIVE_BATCH_MEMORY_THRESHOLD_MEDIUM: Final[int] = 16  # GB

# Progress logging intervals
ANALYZER_PROGRESS_INTERVAL: Final[int] = 100

# Viewer server configuration
VIEWER_VIDEO_CHUNK_SIZE: Final[int] = 1024 * 1024  # 1MB

# Tesla Holiday Update release date (Unix timestamp UTC)
# December 8, 2025 00:00:00 UTC - when SEI feature became available
DEFAULT_MIN_START_TIME: Final[int] = 1765152000
