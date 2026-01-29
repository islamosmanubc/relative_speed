import csv
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

from .classifier import SpeedClassifier
from .config import ClassificationConfig, DepthConfig, IOConfig, SpeedConfig
from .depth_reader import DepthEstimator, DepthReader
from .ego_speed import EgoSpeedSeries
from .qdtrack_reader import load_qdtrack
from .progress import progress_iter
from .rs_types import FrameObjectRecord, TrackSummary


@dataclass
class PipelineResult:
    frame_records: list[FrameObjectRecord]
    track_summaries: list[TrackSummary]

    def to_csv(self, out_dir: Path) -> None:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        _write_frame_records(out_dir / "object_speeds.csv", self.frame_records)
        _write_track_summaries(out_dir / "track_summary.csv", self.track_summaries)


class RelativeSpeedPipeline:
    def __init__(
        self,
        speed_config: SpeedConfig,
        depth_config: DepthConfig,
        class_config: ClassificationConfig,
        io_config: IOConfig,
    ):
        self.speed_config = speed_config
        self.depth_config = depth_config
        self.class_config = class_config
        self.io_config = io_config

    def run(
        self,
        qdtrack_json: Path,
        depth_dir: Path,
        sei_csv: Path,
        out_dir: Optional[Path] = None,
    ) -> PipelineResult:
        frames = load_qdtrack(Path(qdtrack_json), self.io_config.label_whitelist)
        ego_speeds = EgoSpeedSeries.from_csv(Path(sei_csv), self.io_config.speed_column)
        depth_reader = DepthReader(Path(depth_dir))
        depth_estimator = DepthEstimator(self.depth_config)
        classifier = SpeedClassifier(self.class_config)

        track_records: dict[str, list[FrameObjectRecord]] = {}
        track_state: dict[str, dict[str, float]] = {}
        ratio = self.speed_config.sei_fps / self.speed_config.qdtrack_fps

        for frame in progress_iter(frames, total=len(frames), desc="Processing frames"):
            aligned_frame_id = int(round(frame.frame_id * ratio)) + self.speed_config.frame_id_offset
            depth_map = depth_reader.get(frame.frame_id)
            if depth_map is None:
                continue

            height, width = depth_map.shape[:2]
            src_width = self.depth_config.source_width or width
            if width <= 0 or src_width <= 0:
                continue

            t_sec = frame.frame_id / self.speed_config.qdtrack_fps
            ego_speed = ego_speeds.speed_at(aligned_frame_id)

            for det in frame.detections:
                depth_m = depth_estimator.estimate(depth_map, det.bbox)
                if depth_m is None:
                    continue

                center_x, _ = det.bbox.center()
                center_x_norm = center_x / float(src_width)
                center_x_norm = max(0.0, min(1.0, center_x_norm))

                rel_speed_raw = None
                state = track_state.get(det.track_id)
                if state is not None:
                    prev_depth = state.get("prev_depth")
                    prev_t = state.get("prev_t")
                    if prev_depth is not None and prev_t is not None:
                        dt = t_sec - prev_t
                        if dt > 0:
                            rel_speed_raw = (depth_m - prev_depth) / dt

                record = FrameObjectRecord(
                    frame_id=frame.frame_id,
                    aligned_frame_id=aligned_frame_id,
                    t_sec=t_sec,
                    track_id=det.track_id,
                    bbox_x1=det.bbox.x1,
                    bbox_y1=det.bbox.y1,
                    bbox_x2=det.bbox.x2,
                    bbox_y2=det.bbox.y2,
                    depth_m=depth_m,
                    center_x_norm=center_x_norm,
                    ego_speed_mps=ego_speed,
                    rel_speed_raw_mps=rel_speed_raw,
                )

                track_records.setdefault(det.track_id, []).append(record)
                track_state[det.track_id] = {"prev_depth": depth_m, "prev_t": t_sec}

        frame_records: list[FrameObjectRecord] = []
        track_summaries: list[TrackSummary] = []

        for track_id, records in track_records.items():
            if len(records) < self.speed_config.min_track_length:
                for rec in records:
                    rec.label = self.class_config.unknown_label
                frame_records.extend(records)
                track_summaries.append(_summarize_track(track_id, records, self.class_config))
                continue

            records.sort(key=lambda rec: rec.t_sec)
            raw_speeds = [rec.rel_speed_raw_mps for rec in records]
            smooth_speeds = _smooth_series(raw_speeds, self.speed_config.rel_speed_smooth_window)

            for idx, rec in enumerate(records):
                rec.rel_speed_mps = smooth_speeds[idx]
                if rec.rel_speed_mps is not None and rec.ego_speed_mps is not None:
                    rec.obj_speed_mps = rec.ego_speed_mps + rec.rel_speed_mps

                if idx > 0:
                    prev = records[idx - 1]
                    if rec.rel_speed_mps is not None and prev.rel_speed_mps is not None:
                        dt = rec.t_sec - prev.t_sec
                        if dt > 0:
                            rec.rel_acc_mps2 = (rec.rel_speed_mps - prev.rel_speed_mps) / dt

            frame_labels = [
                classifier.classify(rec.rel_speed_mps, rec.ego_speed_mps, rec.center_x_norm)
                for rec in records
            ]
            track_label = _majority_label(
                [label for label in frame_labels if label != self.class_config.unknown_label]
            )
            if not track_label:
                track_label = self.class_config.unknown_label
            for rec in records:
                rec.label = track_label

            frame_records.extend(records)
            track_summaries.append(_summarize_track(track_id, records, self.class_config))

        result = PipelineResult(frame_records=frame_records, track_summaries=track_summaries)
        if out_dir is not None:
            result.to_csv(Path(out_dir))
        return result


def _summarize_track(
    track_id: str,
    records: list[FrameObjectRecord],
    class_config: ClassificationConfig,
) -> TrackSummary:
    labels = [rec.label for rec in records if rec.label != class_config.unknown_label]
    label = _majority_label(labels) if labels else class_config.unknown_label
    return TrackSummary(
        track_id=track_id,
        label=label,
        n_frames=len(records),
        start_frame=min(rec.frame_id for rec in records),
        end_frame=max(rec.frame_id for rec in records),
        median_depth_m=_median_or_none([rec.depth_m for rec in records]),
        median_rel_speed_mps=_median_or_none([rec.rel_speed_mps for rec in records]),
        median_obj_speed_mps=_median_or_none([rec.obj_speed_mps for rec in records]),
        median_center_x_norm=_median_or_none([rec.center_x_norm for rec in records]),
    )


def _majority_label(labels: list[str]) -> str:
    if not labels:
        return ""
    return Counter(labels).most_common(1)[0][0]


def _median_or_none(values: list[Optional[float]]) -> Optional[float]:
    valid = [v for v in values if v is not None]
    if not valid:
        return None
    return float(np.median(valid))


def _smooth_series(values: list[Optional[float]], window: int) -> list[Optional[float]]:
    if window <= 1:
        return values
    half = window // 2
    out: list[Optional[float]] = []
    n = len(values)
    for i in range(n):
        a = max(0, i - half)
        b = min(n, i + half + 1)
        chunk = [v for v in values[a:b] if v is not None]
        out.append(float(np.median(chunk)) if chunk else None)
    return out


def _write_frame_records(path: Path, records: list[FrameObjectRecord]) -> None:
    fieldnames = [
        "frame_id",
        "aligned_frame_id",
        "t_sec",
        "track_id",
        "bbox_x1",
        "bbox_y1",
        "bbox_x2",
        "bbox_y2",
        "depth_m",
        "center_x_norm",
        "ego_speed_mps",
        "rel_speed_raw_mps",
        "rel_speed_mps",
        "rel_acc_mps2",
        "obj_speed_mps",
        "label",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for rec in records:
            writer.writerow({
                "frame_id": rec.frame_id,
                "aligned_frame_id": rec.aligned_frame_id,
                "t_sec": rec.t_sec,
                "track_id": rec.track_id,
                "bbox_x1": rec.bbox_x1,
                "bbox_y1": rec.bbox_y1,
                "bbox_x2": rec.bbox_x2,
                "bbox_y2": rec.bbox_y2,
                "depth_m": rec.depth_m,
                "center_x_norm": rec.center_x_norm,
                "ego_speed_mps": rec.ego_speed_mps,
                "rel_speed_raw_mps": rec.rel_speed_raw_mps,
                "rel_speed_mps": rec.rel_speed_mps,
                "rel_acc_mps2": rec.rel_acc_mps2,
                "obj_speed_mps": rec.obj_speed_mps,
                "label": rec.label,
            })


def _write_track_summaries(path: Path, summaries: list[TrackSummary]) -> None:
    fieldnames = [
        "track_id",
        "label",
        "n_frames",
        "start_frame",
        "end_frame",
        "median_depth_m",
        "median_rel_speed_mps",
        "median_obj_speed_mps",
        "median_center_x_norm",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for summary in summaries:
            writer.writerow({
                "track_id": summary.track_id,
                "label": summary.label,
                "n_frames": summary.n_frames,
                "start_frame": summary.start_frame,
                "end_frame": summary.end_frame,
                "median_depth_m": summary.median_depth_m,
                "median_rel_speed_mps": summary.median_rel_speed_mps,
                "median_obj_speed_mps": summary.median_obj_speed_mps,
                "median_center_x_norm": summary.median_center_x_norm,
            })
