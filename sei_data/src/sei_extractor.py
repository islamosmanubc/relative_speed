"""SEI metadata extraction from Tesla dashcam videos."""

# Set protobuf implementation to pure Python to work with older protoc-generated files
# This MUST be set before importing any protobuf modules
import os

os.environ["PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION"] = "python"

import json
import logging
import struct
from collections.abc import Generator
from pathlib import Path
from typing import Any, Optional, Tuple

from google.protobuf.json_format import MessageToDict
from google.protobuf.message import DecodeError

logger = logging.getLogger(__name__)

# Lazy import to avoid issues if protobuf file is missing
_dashcam_pb2_module = None


def _ensure_dashcam_pb2():
    """Ensure dashcam_pb2 is imported. Returns True if available."""
    global _dashcam_pb2_module
    if _dashcam_pb2_module is not None:
        return True

    try:
        from . import dashcam_pb2  # noqa: PLC0415

        _dashcam_pb2_module = dashcam_pb2
        return True
    except ImportError:
        logger.warning("dashcam_pb2.py not found. Run: protoc --python_out=. src/dashcam.proto")
        return False


def _get_dashcam_pb2():
    """Get dashcam_pb2 module, ensuring it's imported first."""
    _ensure_dashcam_pb2()
    return _dashcam_pb2_module


def find_mdat(fp) -> Tuple[int, int]:
    """Return (offset, size) for the first mdat atom in MP4 file.

    Args:
        fp: File pointer (opened in binary mode)

    Returns:
        Tuple of (offset, size) for mdat atom
    """
    fp.seek(0)
    while True:
        header = fp.read(8)
        if len(header) < 8:
            raise RuntimeError("mdat atom not found")
        size32, atom_type = struct.unpack(">I4s", header)
        if size32 == 1:
            large = fp.read(8)
            if len(large) != 8:
                raise RuntimeError("truncated extended atom size")
            atom_size = struct.unpack(">Q", large)[0]
            header_size = 16
        else:
            atom_size = size32 if size32 else 0
            header_size = 8
        if atom_type == b"mdat":
            payload_size = atom_size - header_size if atom_size else 0
            return fp.tell(), payload_size
        if atom_size < header_size:
            raise RuntimeError("invalid MP4 atom size")
        fp.seek(atom_size - header_size, 1)


def iter_nals(fp, offset: int, size: int) -> Generator[bytes, None, None]:
    """Yield SEI user NAL units from the MP4 mdat atom.

    Args:
        fp: File pointer (opened in binary mode)
        offset: Offset to start reading from
        size: Size of data to read (0 for all)

    Yields:
        SEI NAL unit bytes
    """
    NAL_ID_SEI = 6
    NAL_SEI_ID_USER_DATA_UNREGISTERED = 5

    fp.seek(offset)
    consumed = 0
    while size == 0 or consumed < size:
        header = fp.read(4)
        if len(header) < 4:
            break
        nal_size = struct.unpack(">I", header)[0]
        if nal_size < 2:
            fp.seek(nal_size, 1)
            consumed += 4 + nal_size
            continue

        first_two = fp.read(2)
        if len(first_two) != 2:
            break

        if (first_two[0] & 0x1F) != NAL_ID_SEI or first_two[1] != NAL_SEI_ID_USER_DATA_UNREGISTERED:
            fp.seek(nal_size - 2, 1)
            consumed += 4 + nal_size
            continue

        rest = fp.read(nal_size - 2)
        if len(rest) != nal_size - 2:
            break
        payload = first_two + rest
        consumed += 4 + nal_size
        yield payload


def extract_proto_payload(nal: bytes) -> Optional[bytes]:
    """Extract protobuf payload from SEI NAL unit.

    Args:
        nal: NAL unit bytes

    Returns:
        Protobuf payload bytes or None if not found
    """
    if not isinstance(nal, bytes) or len(nal) < 2:
        return None
    for i in range(3, len(nal) - 1):
        byte = nal[i]
        if byte == 0x42:
            continue
        if byte == 0x69:
            if i > 2:
                return strip_emulation_prevention_bytes(nal[i + 1 : -1])
            break
        break
    return None


def strip_emulation_prevention_bytes(data: bytes) -> bytes:
    """Remove emulation prevention bytes (0x03 following 0x00 0x00).

    Args:
        data: Raw bytes with potential emulation prevention bytes

    Returns:
        Bytes with emulation prevention bytes removed
    """
    stripped = bytearray()
    zero_count = 0
    for byte in data:
        if zero_count >= 2 and byte == 0x03:
            zero_count = 0
            continue
        stripped.append(byte)
        zero_count = 0 if byte != 0 else zero_count + 1
    return bytes(stripped)


def iter_sei_messages(fp, offset: int, size: int) -> Generator[Any, None, None]:
    """Yield parsed SeiMetadata messages from the MP4 file.

    Args:
        fp: File pointer (opened in binary mode)
        offset: Offset to start reading from
        size: Size of data to read (0 for all)

    Yields:
        SeiMetadata protobuf messages
    """
    dashcam_pb2 = _get_dashcam_pb2()
    if dashcam_pb2 is None:
        logger.error("dashcam_pb2 not available. Cannot extract SEI messages.")
        return

    for nal in iter_nals(fp, offset, size):
        payload = extract_proto_payload(nal)
        if not payload:
            continue
        meta = dashcam_pb2.SeiMetadata()
        try:
            meta.ParseFromString(payload)
        except DecodeError:
            continue
        yield meta


def extract_sei_from_video(video_path: Path) -> list[dict[str, Any]]:
    """Extract SEI metadata from a Tesla dashcam video file.

    Args:
        video_path: Path to the MP4 video file

    Returns:
        List of SEI metadata dictionaries (one per frame with SEI data)
    """

    try:
        sei_data = []
        with open(video_path, "rb") as fp:
            offset, size = find_mdat(fp)
            for meta in iter_sei_messages(fp, offset, size):
                meta_dict = MessageToDict(meta, preserving_proto_field_name=True)
                sei_data.append(meta_dict)

        logger.info(f"Extracted {len(sei_data)} SEI metadata frames from {video_path}")
        return sei_data

    except Exception as e:
        logger.error(f"Error extracting SEI from {video_path}: {e}")
        return []


def save_sei_data(sei_data: list[dict[str, Any]], output_path: Path) -> None:
    """Save SEI metadata to JSON file.

    Args:
        sei_data: List of SEI metadata dictionaries
        output_path: Path to save JSON file
    """

    with open(output_path, "w") as f:
        json.dump(sei_data, f, indent=2, default=str)

    logger.info(f"Saved {len(sei_data)} SEI frames to {output_path}")


def load_sei_data(sei_path: Path) -> list[dict[str, Any]]:
    """Load SEI metadata from JSON file.

    Args:
        sei_path: Path to JSON file

    Returns:
        List of SEI metadata dictionaries
    """

    try:
        with open(sei_path) as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading SEI data from {sei_path}: {e}")
        return []


def check_video_has_sei(video_path: Path) -> bool:
    """Efficiently check if video file contains SEI data without full extraction.

    Args:
        video_path: Path to the MP4 video file

    Returns:
        True if video contains SEI data, False otherwise
    """

    try:
        has_sei = False
        with open(video_path, "rb") as fp:
            offset, size = find_mdat(fp)
            for _ in iter_sei_messages(fp, offset, size):
                has_sei = True
                break
        return has_sei

    except Exception as e:
        logger.error(f"Error checking SEI in {video_path}: {e}")
        return False


def extract_and_save_sei_from_video(video_path: Path, output_dir: Path, dmp_id: int) -> Optional[Path]:
    """Extract SEI metadata from a local video file and save it.

    Args:
        video_path: Path to local video file
        output_dir: Base output directory for SEI data
        dmp_id: DMP ID for organizing output

    Returns:
        Path to saved SEI data file, or None if extraction failed
    """
    logger.info(f"Extracting SEI from {video_path} for DMP {dmp_id}...")
    sei_data = extract_sei_from_video(video_path)

    if not sei_data:
        logger.warning(f"No SEI data extracted from {video_path}")
        return None

    sei_output_dir = output_dir / "sei_data" / str(dmp_id)
    sei_output_path = sei_output_dir / f"{video_path.stem}_sei.json"
    save_sei_data(sei_data, sei_output_path)

    return sei_output_path
