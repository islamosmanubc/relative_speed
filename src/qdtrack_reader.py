import json
from pathlib import Path
from typing import Any, Iterable, Optional

from .config import LabelType
from .rs_types import BBox, Detection, FrameDetections


def load_qdtrack(
    json_path: Path,
    label_whitelist: Optional[Iterable[LabelType]] = None,
) -> list[FrameDetections]:
    with json_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    frames = _extract_frames(data)
    parsed = []
    for idx, frame in enumerate(frames):
        frame_id = _get_frame_id(frame, idx)
        instances = _get_instances(frame)
        detections: list[Detection] = []
        for inst in instances:
            det = _parse_detection(inst, frame_id)
            if det is None:
                continue
            if label_whitelist is not None and det.label not in label_whitelist:
                continue
            detections.append(det)
        parsed.append(FrameDetections(frame_id=frame_id, detections=detections))

    parsed.sort(key=lambda item: item.frame_id)
    return parsed


def _extract_frames(data: Any) -> list[Any]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("frames", "results", "detections", "tracks"):
            if key in data and isinstance(data[key], list):
                return data[key]
        if all(isinstance(v, list) for v in data.values()):
            frames = []
            for k, v in data.items():
                try:
                    frame_id = int(k)
                except (TypeError, ValueError):
                    frame_id = k
                frames.append({"frame_id": frame_id, "instances": v})
            return frames
    raise ValueError("Unsupported QDTrack JSON structure.")


def _get_frame_id(frame: Any, default_id: int) -> int:
    if isinstance(frame, dict):
        for key in ("frame_id", "frame_index", "index", "id"):
            if key in frame:
                try:
                    return int(frame[key])
                except (TypeError, ValueError):
                    return default_id
        name = frame.get("name")
        if isinstance(name, str):
            stem = name.rsplit(".", 1)[0]
            if stem.isdigit():
                return int(stem)
    return default_id


def _get_instances(frame: Any) -> list[Any]:
    if isinstance(frame, list):
        return frame
    if isinstance(frame, dict):
        for key in ("instances", "objects", "detections", "tracks", "bbox_results", "labels"):
            if key in frame and isinstance(frame[key], list):
                return frame[key]
    return []


def _parse_detection(instance: Any, frame_id: int) -> Optional[Detection]:
    if not isinstance(instance, dict):
        return None

    track_id = _get_track_id(instance)
    if track_id is None:
        return None

    bbox = _get_bbox(instance)
    if bbox is None:
        return None

    score = _get_score(instance)
    label = _get_label(instance)
    return Detection(
        frame_id=frame_id,
        track_id=track_id,
        bbox=bbox,
        score=score,
        label=label,
    )


def _get_track_id(instance: dict[str, Any]) -> Optional[str]:
    for key in ("track_id", "track", "tracking_id", "id"):
        if key in instance:
            value = instance[key]
            if value is None:
                return None
            return str(value)
    return None


def _get_score(instance: dict[str, Any]) -> Optional[float]:
    for key in ("score", "confidence"):
        if key in instance:
            try:
                return float(instance[key])
            except (TypeError, ValueError):
                return None
    return None


def _get_label(instance: dict[str, Any]) -> Optional[LabelType]:
    for key in ("label", "category_id", "class", "cls", "name", "category"):
        if key in instance:
            return instance[key]
    return None


def _get_bbox(instance: dict[str, Any]) -> Optional[BBox]:
    bbox_raw = None
    bbox_key = None
    for key in ("bbox", "bbox_xyxy", "box", "tlbr", "tlwh", "box2d"):
        if key in instance:
            bbox_raw = instance[key]
            bbox_key = key
            break

    if bbox_raw is None:
        return None

    if isinstance(bbox_raw, dict):
        return _bbox_from_dict(bbox_raw)

    if isinstance(bbox_raw, (list, tuple)) and len(bbox_raw) >= 4:
        x1, y1, x2, y2 = bbox_raw[:4]
        try:
            x1, y1, x2, y2 = float(x1), float(y1), float(x2), float(y2)
        except (TypeError, ValueError):
            return None
        if bbox_key == "tlwh" or x2 <= x1 or y2 <= y1:
            x2 = x1 + max(0.0, float(bbox_raw[2]))
            y2 = y1 + max(0.0, float(bbox_raw[3]))
        return BBox(x1=x1, y1=y1, x2=x2, y2=y2)

    return None


def _bbox_from_dict(bbox_raw: dict[str, Any]) -> Optional[BBox]:
    keys_xyxy = ("x1", "y1", "x2", "y2")
    if all(k in bbox_raw for k in keys_xyxy):
        try:
            return BBox(
                x1=float(bbox_raw["x1"]),
                y1=float(bbox_raw["y1"]),
                x2=float(bbox_raw["x2"]),
                y2=float(bbox_raw["y2"]),
            )
        except (TypeError, ValueError):
            return None

    keys_xywh = ("x", "y", "w", "h")
    if all(k in bbox_raw for k in keys_xywh):
        try:
            x1 = float(bbox_raw["x"])
            y1 = float(bbox_raw["y"])
            w = float(bbox_raw["w"])
            h = float(bbox_raw["h"])
            return BBox(x1=x1, y1=y1, x2=x1 + w, y2=y1 + h)
        except (TypeError, ValueError):
            return None

    return None
