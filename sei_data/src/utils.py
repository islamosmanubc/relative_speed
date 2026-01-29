"""Utility functions for disengagement SEI analyzer."""

from datetime import datetime

# Timestamp format constants
TIMESTAMP_FORMAT = "%Y%m%d_%H%M%S"
TIMESTAMP_FORMAT_DISPLAY = "%Y-%m-%d %H:%M:%S"


def generate_timestamp() -> str:
    """Generate timestamp string in standard format.

    Returns:
        Timestamp string in format YYYYMMDD_HHMMSS
    """
    return datetime.now().strftime(TIMESTAMP_FORMAT)


def format_datetime_for_display(dt: datetime) -> str:
    """Format datetime for display purposes.

    Args:
        dt: Datetime object to format

    Returns:
        Formatted datetime string
    """
    return dt.strftime(TIMESTAMP_FORMAT_DISPLAY)
