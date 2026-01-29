import csv
import math
from pathlib import Path
from typing import Optional


class EgoSpeedSeries:
    def __init__(self, speeds: list[float]):
        self._speeds = self._fill_missing(speeds)

    @classmethod
    def from_csv(cls, csv_path: Path, speed_column: str) -> "EgoSpeedSeries":
        speeds: list[float] = []
        with csv_path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None or speed_column not in reader.fieldnames:
                raise ValueError(f"Missing speed column '{speed_column}' in {csv_path}")
            for row in reader:
                raw = row.get(speed_column, "")
                try:
                    speeds.append(float(raw))
                except (TypeError, ValueError):
                    speeds.append(float("nan"))
        return cls(speeds)

    def speed_at(self, frame_id: int) -> Optional[float]:
        if not self._speeds:
            return None
        if frame_id < 0:
            return None
        if frame_id >= len(self._speeds):
            return self._speeds[-1]
        return self._speeds[frame_id]

    @staticmethod
    def _fill_missing(values: list[float]) -> list[float]:
        if not values:
            return []
        out: list[float] = []
        last_valid: Optional[float] = None
        for v in values:
            if isinstance(v, float) and not math.isnan(v):
                last_valid = v
                out.append(v)
            else:
                out.append(last_valid if last_valid is not None else float("nan"))

        try:
            first_valid = next(v for v in out if not math.isnan(v))
            return [first_valid if math.isnan(v) else v for v in out]
        except StopIteration:
            return [0.0 for _ in out]
