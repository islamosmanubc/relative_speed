"""Shared logging configuration for disengagement SEI analyzer."""

import logging
import sys

import colorlog


def setup_logging(
    log_file: str | None = None,
    log_level: int = logging.INFO,
    console_level: int = logging.INFO,
) -> logging.Logger:
    """Set up logging with file and console handlers.

    Args:
        log_file: Optional path to log file (if None, only console logging)
        log_level: Logging level for file handler
        console_level: Logging level for console handler

    Returns:
        Configured root logger
    """
    # Suppress noisy third-party library warnings
    logging.getLogger("urllib3.connectionpool").setLevel(logging.ERROR)
    logging.getLogger("botocore.credentials").setLevel(logging.WARNING)
    logging.getLogger("botocore.utils").setLevel(logging.WARNING)

    root_logger = logging.getLogger()
    root_logger.handlers = []  # Clear any existing handlers
    root_logger.setLevel(logging.DEBUG)  # Set to lowest level, handlers filter

    # File handler (plain text, no colors)
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(log_level)
        file_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
        file_handler.setFormatter(file_formatter)
        root_logger.addHandler(file_handler)

    # Console handler (colored)
    console_handler = colorlog.StreamHandler(sys.stdout)
    console_handler.setLevel(console_level)
    console_formatter = colorlog.ColoredFormatter(
        "%(log_color)s%(asctime)s - %(levelname)s - %(message)s%(reset)s",
        datefmt=None,
        reset=True,
        log_colors={
            "DEBUG": "cyan",
            "INFO": "green",
            "WARNING": "yellow",
            "ERROR": "red",
            "CRITICAL": "red,bg_white",
        },
    )
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)

    return root_logger
