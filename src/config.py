from dataclasses import dataclass
from typing import Iterable, Optional, Union


LabelType = Union[int, str]


@dataclass
class DepthConfig:
    margin_frac: float = 0.1
    min_pixels: int = 25
    min_valid_ratio: float = 0.2
    invalid_depth_threshold: float = 0.01
    max_depth_m: Optional[float] = 35.0
    source_width: Optional[int] = None
    source_height: Optional[int] = None


@dataclass
class SpeedConfig:
    qdtrack_fps: float = 12.0
    sei_fps: float = 36.0
    frame_id_offset: int = 0
    rel_speed_smooth_window: int = 5
    min_track_length: int = 5


@dataclass
class ClassificationConfig:
    stop_speed_mps: float = 0.2
    opposite_speed_mps: float = 2.0
    lane_center_thresh: float = 0.2
    ego_moving_mps: float = 1.0
    opposite_left_max: float = 0.5
    rel_same_ratio: float = 0.2
    rel_opposite_ratio: float = 0.3
    unknown_label: str = "unknown"


@dataclass
class IOConfig:
    speed_column: str = "vehicle_speed_mps"
    label_whitelist: Optional[Iterable[LabelType]] = None
