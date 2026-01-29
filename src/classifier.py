from __future__ import annotations

from .config import ClassificationConfig


class SpeedClassifier:
    def __init__(self, config: ClassificationConfig):
        self.config = config

    def classify(
        self,
        rel_speed_mps: float | None,
        ego_speed_mps: float | None,
        center_x_norm: float | None,
    ) -> str:
        if rel_speed_mps is None or ego_speed_mps is None or center_x_norm is None:
            return self.config.unknown_label

        left_side = center_x_norm <= self.config.opposite_left_max
        right_side = not left_side
        ego_speed_abs = abs(ego_speed_mps)
        ego_moving = ego_speed_abs >= self.config.ego_moving_mps

        if abs(rel_speed_mps) <= self.config.stop_speed_mps:
            if ego_speed_abs <= self.config.ego_moving_mps:
                return "stopped_ego_direction"
            return "same_direction"

        if not ego_moving:
            if rel_speed_mps < -self.config.stop_speed_mps:
                if right_side:
                    return "parked"
                return "opposite_direction"
            return "same_direction"

        if rel_speed_mps < 0.0:
            ratio = -rel_speed_mps / ego_speed_abs if ego_speed_abs > 0 else 0.0
            if ratio < self.config.rel_same_ratio:
                return "same_direction"
            if ratio < self.config.rel_opposite_ratio:
                return "parked"
            if right_side:
                return "parked"
            return "opposite_direction"

        return "same_direction"
