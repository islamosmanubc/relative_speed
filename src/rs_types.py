from dataclasses import dataclass
from typing import Optional, Union


LabelType = Union[int, str]


@dataclass
class BBox:
    x1: float
    y1: float
    x2: float
    y2: float

    def clamp(self, width: int, height: int) -> "BBox":
        x1 = max(0.0, min(float(width - 1), self.x1))
        y1 = max(0.0, min(float(height - 1), self.y1))
        x2 = max(0.0, min(float(width), self.x2))
        y2 = max(0.0, min(float(height), self.y2))
        return BBox(x1=x1, y1=y1, x2=x2, y2=y2)

    def center(self) -> tuple[float, float]:
        return ((self.x1 + self.x2) * 0.5, (self.y1 + self.y2) * 0.5)

    def width(self) -> float:
        return max(0.0, self.x2 - self.x1)

    def height(self) -> float:
        return max(0.0, self.y2 - self.y1)


@dataclass
class Detection:
    frame_id: int
    track_id: str
    bbox: BBox
    score: Optional[float] = None
    label: Optional[LabelType] = None


@dataclass
class FrameDetections:
    frame_id: int
    detections: list[Detection]


@dataclass
class FrameObjectRecord:
    frame_id: int
    aligned_frame_id: int
    t_sec: float
    track_id: str
    bbox_x1: float
    bbox_y1: float
    bbox_x2: float
    bbox_y2: float
    depth_m: Optional[float]
    center_x_norm: Optional[float]
    ego_speed_mps: Optional[float]
    rel_speed_raw_mps: Optional[float]
    rel_speed_mps: Optional[float] = None
    rel_acc_mps2: Optional[float] = None
    obj_speed_mps: Optional[float] = None
    label: str = "unknown"


@dataclass
class TrackSummary:
    track_id: str
    label: str
    n_frames: int
    start_frame: int
    end_frame: int
    median_depth_m: Optional[float]
    median_rel_speed_mps: Optional[float]
    median_obj_speed_mps: Optional[float]
    median_center_x_norm: Optional[float]
