if __package__ in (None, ""):
    import sys
    from pathlib import Path as _Path

    sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))
    __package__ = "relative_speed"

import argparse
from pathlib import Path

import cv2

from src.config import ClassificationConfig, DepthConfig, IOConfig, SpeedConfig
from src.pipeline import RelativeSpeedPipeline
from src.qdtrack_reader import load_qdtrack
from src.video_data import resolve_video_data
from src.video_overlay import write_overlay_video


def build_parser() -> argparse.ArgumentParser:
    class_defaults = ClassificationConfig()
    depth_defaults = DepthConfig()
    speed_defaults = SpeedConfig()
    ap = argparse.ArgumentParser(description="Estimate relative object speeds from QDTrack + DepthAnything.")
    ap.add_argument("--video_data", required=True, help="Path to video_data folder with qdtrack/depth/sei_data")
    ap.add_argument("--video", default="", help="Optional video file path override")
    ap.add_argument("--qdtrack_fps", type=float, default=speed_defaults.qdtrack_fps, help="QDTrack/Depth frame rate")
    ap.add_argument("--sei_fps", type=float, default=speed_defaults.sei_fps, help="SEI frame rate")
    ap.add_argument("--frame_id_offset", type=int, default=speed_defaults.frame_id_offset, help="Frame offset between QDTrack and depth/SEI")
    ap.add_argument("--speed_column", default="vehicle_speed_mps", help="SEI CSV speed column")
    ap.add_argument("--label_whitelist", default="", help="Comma-separated label IDs/names to keep (optional)")
    ap.add_argument("--stop_speed_mps", type=float, default=class_defaults.stop_speed_mps, help="Threshold for stopped/parked")
    ap.add_argument("--opposite_speed_mps", type=float, default=class_defaults.opposite_speed_mps, help="Threshold for opposite direction")
    ap.add_argument("--lane_center_thresh", type=float, default=class_defaults.lane_center_thresh, help="Normalized center distance for in-lane")
    ap.add_argument("--opposite_left_max", type=float, default=class_defaults.opposite_left_max, help="Max normalized center x for opposite-direction candidates")
    ap.add_argument("--rel_same_ratio", type=float, default=class_defaults.rel_same_ratio, help="Same-direction ratio of ego speed for negative rel speed")
    ap.add_argument("--rel_opposite_ratio", type=float, default=class_defaults.rel_opposite_ratio, help="Opposite-direction ratio of ego speed for negative rel speed")
    ap.add_argument("--smooth_window", type=int, default=speed_defaults.rel_speed_smooth_window, help="Median smoothing window for relative speed")
    ap.add_argument("--min_track_length", type=int, default=speed_defaults.min_track_length, help="Minimum frames for track summary")
    ap.add_argument("--max_depth_m", type=float, default=depth_defaults.max_depth_m, help="Ignore objects deeper than this (meters)")
    return ap


def _get_video_size(video_path: Path) -> tuple[int | None, int | None]:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return None, None
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    if width <= 0 or height <= 0:
        return None, None
    return width, height


def main() -> None:
    ap = build_parser()
    args = ap.parse_args()

    labels = []
    for raw in args.label_whitelist.split(","):
        val = raw.strip()
        if not val:
            continue
        if val.isdigit():
            labels.append(int(val))
        else:
            labels.append(val)
    label_whitelist = labels if labels else None

    speed_cfg = SpeedConfig(
        qdtrack_fps=args.qdtrack_fps,
        sei_fps=args.sei_fps,
        frame_id_offset=args.frame_id_offset,
        rel_speed_smooth_window=args.smooth_window,
        min_track_length=args.min_track_length,
    )
    class_cfg = ClassificationConfig(
        stop_speed_mps=args.stop_speed_mps,
        opposite_speed_mps=args.opposite_speed_mps,
        lane_center_thresh=args.lane_center_thresh,
        opposite_left_max=args.opposite_left_max,
        rel_same_ratio=args.rel_same_ratio,
        rel_opposite_ratio=args.rel_opposite_ratio,
    )
    io_cfg = IOConfig(
        speed_column=args.speed_column,
        label_whitelist=label_whitelist,
    )

    video_override = Path(args.video) if args.video else None
    paths = resolve_video_data(Path(args.video_data), video_override)

    video_width, video_height = _get_video_size(paths.video_path)
    if video_width and video_height:
        depth_cfg = DepthConfig(
            source_width=video_width,
            source_height=video_height,
            max_depth_m=args.max_depth_m,
        )
    else:
        depth_cfg = DepthConfig(max_depth_m=args.max_depth_m)

    depth_files = list(paths.depth_dir.glob("*.npy"))
    print("Resolved paths:")
    print(f"  qdtrack_json: {paths.qdtrack_json}")
    print(f"  depth_dir: {paths.depth_dir} (npy={len(depth_files)})")
    print(f"  sei_csv: {paths.sei_csv}")
    print(f"  video_path: {paths.video_path}")
    if video_width and video_height:
        print(f"  video_size: {video_width}x{video_height}")
    print(f"  out_dir: {paths.out_dir}")

    frames_debug = load_qdtrack(paths.qdtrack_json, io_cfg.label_whitelist)
    det_count = sum(len(frame.detections) for frame in frames_debug)
    print(f"QDTrack frames: {len(frames_debug)}  detections: {det_count}")

    pipeline = RelativeSpeedPipeline(speed_cfg, depth_cfg, class_cfg, io_cfg)
    result = pipeline.run(
        qdtrack_json=paths.qdtrack_json,
        depth_dir=paths.depth_dir,
        sei_csv=paths.sei_csv,
        out_dir=paths.out_dir,
    )

    frames = frames_debug
    ratio = speed_cfg.sei_fps / speed_cfg.qdtrack_fps
    aligned_frame_ids = [
        int(round(frame.frame_id * ratio)) + speed_cfg.frame_id_offset
        for frame in frames
    ]

    out_video = paths.out_dir / "relative_speed.mp4"
    write_overlay_video(
        paths.video_path,
        out_video,
        result.frame_records,
        aligned_frame_ids,
        output_fps=speed_cfg.qdtrack_fps,
    )

    print(f"Done. Wrote: {paths.out_dir / 'object_speeds.csv'}")
    print(f"Done. Wrote: {paths.out_dir / 'track_summary.csv'}")
    print(f"Done. Wrote: {out_video}")
    print(f"Tracks: {len(result.track_summaries)}  Frames: {len(result.frame_records)}")


if __name__ == "__main__":
    main()
