from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional


@dataclass(frozen=True)
class VideoDataPaths:
    root: Path
    qdtrack_json: Path
    depth_dir: Path
    sei_csv: Path
    video_path: Path
    out_dir: Path


def resolve_video_data(video_data_dir: Path, video_override: Optional[Path] = None) -> VideoDataPaths:
    root = Path(video_data_dir)
    depth_dir = root / "depth_anything_3"
    qdtrack_dir = root / "qdtrack"
    sei_dir = root / "sei_data"
    out_dir = root / "relative_speed_out"

    if not depth_dir.is_dir():
        raise FileNotFoundError(f"Missing depth_anything_3 folder: {depth_dir}")
    if not sei_dir.is_dir():
        raise FileNotFoundError(f"Missing sei_data folder: {sei_dir}")

    qdtrack_jsons: list[Path] = []
    if qdtrack_dir.is_dir():
        qdtrack_jsons = sorted(qdtrack_dir.glob("*.json"))
    if not qdtrack_jsons:
        qdtrack_jsons = sorted(root.rglob("*.json"))
    if not qdtrack_jsons:
        raise FileNotFoundError(f"No .json tracking file found under {root}")
    qdtrack_json = _pick_single_or_latest(qdtrack_jsons)

    sei_csvs = sorted(sei_dir.glob("sei_data_*.csv"))
    if not sei_csvs:
        raise FileNotFoundError(f"No sei_data_*.csv found in {sei_dir}")
    sei_csv = _pick_latest(sei_csvs)

    if video_override is not None:
        video_path = Path(video_override)
    else:
        video_dir = sei_dir / "video"
        videos = sorted(video_dir.glob("*.mp4"))
        if not videos:
            raise FileNotFoundError(f"No .mp4 video found in {video_dir}")
        video_path = _pick_single_or_latest(videos)

    return VideoDataPaths(
        root=root,
        qdtrack_json=qdtrack_json,
        depth_dir=depth_dir,
        sei_csv=sei_csv,
        video_path=video_path,
        out_dir=out_dir,
    )


def _pick_latest(paths: Iterable[Path]) -> Path:
    return max(paths, key=lambda p: p.stat().st_mtime)

def _pick_single_or_latest(paths: Iterable[Path]) -> Path:
    paths = list(paths)
    if len(paths) == 1:
        return paths[0]
    return _pick_latest(paths)
