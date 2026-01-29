from pathlib import Path
from typing import Optional

import numpy as np

from .config import DepthConfig
from .rs_types import BBox


class DepthReader:
    def __init__(self, depth_dir: Path):
        self.depth_dir = Path(depth_dir)
        self._id_to_path: dict[object, Path] = {}
        self._index_depth_files()

    def _index_depth_files(self) -> None:
        for path in self.depth_dir.glob("*.npy"):
            stem = path.stem
            if stem.isdigit():
                idx = int(stem)
                self._id_to_path[idx] = path
            self._id_to_path[stem] = path

    def get(self, frame_id: object) -> Optional[np.ndarray]:
        if frame_id in self._id_to_path:
            return np.load(self._id_to_path[frame_id])

        if isinstance(frame_id, str) and frame_id.isdigit():
            numeric_id = int(frame_id)
            if numeric_id in self._id_to_path:
                return np.load(self._id_to_path[numeric_id])

        if isinstance(frame_id, int):
            str_id = str(frame_id)
            if str_id in self._id_to_path:
                return np.load(self._id_to_path[str_id])

        return None


class DepthEstimator:
    def __init__(self, config: DepthConfig):
        self.config = config

    def estimate(self, depth_map: np.ndarray, bbox: BBox) -> Optional[float]:
        if depth_map is None or depth_map.size == 0:
            return None
        height, width = depth_map.shape[:2]
        scaled = self._scale_bbox(bbox, width, height)
        clamped = scaled.clamp(width, height)

        x1, y1, x2, y2 = clamped.x1, clamped.y1, clamped.x2, clamped.y2
        if self.config.margin_frac > 0.0:
            dx = (x2 - x1) * self.config.margin_frac
            dy = (y2 - y1) * self.config.margin_frac
            x1 += dx
            x2 -= dx
            y1 += dy
            y2 -= dy

        x1_i = int(max(0.0, min(float(width - 1), x1)))
        x2_i = int(max(0.0, min(float(width), x2)))
        y1_i = int(max(0.0, min(float(height - 1), y1)))
        y2_i = int(max(0.0, min(float(height), y2)))

        if x2_i <= x1_i or y2_i <= y1_i:
            return None

        patch = depth_map[y1_i:y2_i, x1_i:x2_i]
        if patch.ndim > 2:
            patch = patch[..., 0]
        if patch.size < self.config.min_pixels:
            return None

        valid_mask = np.isfinite(patch) & (patch > self.config.invalid_depth_threshold)
        valid = patch[valid_mask]
        if valid.size == 0:
            return None

        if valid.size < patch.size * self.config.min_valid_ratio:
            return None

        depth_m = float(np.median(valid))
        max_depth = self.config.max_depth_m
        if max_depth is not None and depth_m > max_depth:
            return None
        return depth_m

    def _scale_bbox(self, bbox: BBox, depth_width: int, depth_height: int) -> BBox:
        src_w = self.config.source_width
        src_h = self.config.source_height
        if not src_w or not src_h or src_w <= 0 or src_h <= 0:
            return bbox
        if src_w == depth_width and src_h == depth_height:
            return bbox
        scale_x = depth_width / float(src_w)
        scale_y = depth_height / float(src_h)
        return BBox(
            x1=bbox.x1 * scale_x,
            y1=bbox.y1 * scale_y,
            x2=bbox.x2 * scale_x,
            y2=bbox.y2 * scale_y,
        )
