from collections import defaultdict
from pathlib import Path
from typing import Iterable

import cv2

from .progress import progress_iter
from .rs_types import FrameObjectRecord


def write_overlay_video(
    video_path: Path,
    out_path: Path,
    frame_records: list[FrameObjectRecord],
    aligned_frame_ids: Iterable[int],
    output_fps: float,
) -> None:
    frame_map = defaultdict(list)
    for rec in frame_records:
        frame_map[rec.aligned_frame_id].append(rec)

    target_frames = sorted({int(fid) for fid in aligned_frame_ids})
    if not target_frames:
        raise ValueError("No frames available for video overlay.")

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")

    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(out_path), fourcc, float(output_fps), (width, height))

    frame_idx = 0
    for target in progress_iter(target_frames, total=len(target_frames), desc="Writing overlay"):
        while frame_idx < target:
            ok, _ = cap.read()
            if not ok:
                cap.release()
                writer.release()
                return
            frame_idx += 1

        ok, frame = cap.read()
        if not ok:
            break
        frame_idx += 1
        for rec in frame_map.get(target, []):
            _draw_record(frame, rec)
        writer.write(frame)

    cap.release()
    writer.release()


def _draw_record(frame, rec: FrameObjectRecord) -> None:
    color = _color_for_label(rec.label)
    height, width = frame.shape[:2]
    x1 = int(round(rec.bbox_x1))
    y1 = int(round(rec.bbox_y1))
    x2 = int(round(rec.bbox_x2))
    y2 = int(round(rec.bbox_y2))
    x1 = max(0, min(width - 1, x1))
    y1 = max(0, min(height - 1, y1))
    x2 = max(0, min(width - 1, x2))
    y2 = max(0, min(height - 1, y2))
    if x2 <= x1 or y2 <= y1:
        return
    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

    speed = rec.rel_speed_mps
    if speed is None:
        speed_str = "rel=n/a"
    else:
        speed_str = f"rel={speed:.1f} m/s"
    label = f"{rec.label} {speed_str}"
    _draw_label(frame, label, x1, y1, color)


def _draw_label(frame, text: str, x: int, y: int, color: tuple[int, int, int]) -> None:
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.8
    thickness = 2
    (tw, th), _ = cv2.getTextSize(text, font, font_scale, thickness)
    pad = 4
    y1 = max(0, y - th - 2 * pad)
    x1 = max(0, x)
    cv2.rectangle(frame, (x1, y1), (x1 + tw + 2 * pad, y1 + th + 2 * pad), color, -1)
    cv2.putText(frame, text, (x1 + pad, y1 + th + pad), font, font_scale, (0, 0, 0), thickness)


def _color_for_label(label: str) -> tuple[int, int, int]:
    palette = {
        "parked": (0, 165, 255),
        "opposite_direction": (0, 0, 255),
        "same_direction": (0, 255, 0),
        "stopped_ego_direction": (255, 255, 0),
    }
    return palette.get(label, (255, 255, 255))
