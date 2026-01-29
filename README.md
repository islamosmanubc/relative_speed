# Relative Speed Estimator

Estimate relative object speeds from QDTrack detections + DepthAnything depth maps,
aligned with ego-speed telemetry (SEI CSV). The main entry point is `cli.py`.

## Requirements

- Python 3.10+
- Python dependencies are captured in `requirements.txt`

Install (pip):

```bash
python -m pip install -r requirements.txt
```

## Expected data layout

Point `--video_data` at a folder like this:

```
video_data/
  depth_anything_3/
    0.npy
    1.npy
    2.npy
    ...
  qdtrack/
    <some_tracking>.json
  sei_data/
    sei_data_YYYYMMDD_*.csv
    video/
      <video>.mp4
```

Notes:
- The QDTrack JSON can be a list of frames or a dict with a list under keys like
  `frames`, `results`, `detections`, or `tracks`. Each frame should contain an
  `instances`/`objects` list with per-object `track_id` and `bbox`.
- Depth maps are `.npy` files. The filename stem should match the frame id
  (e.g., `123.npy` for frame 123). String frame ids also work.
- The SEI CSV is auto-selected as the latest `sei_data_*.csv` in `sei_data/`.
- The video is auto-selected from `sei_data/video/*.mp4` (latest if multiple).

## Usage

From the repo root (recommended):

```bash
python -m relative_speed.cli --video_data H:/path/to/video_data
```

Direct script run (also supported):

```bash
python relative_speed/cli.py --video_data H:/path/to/video_data
```

Common options:

```
--video_data <path>           Root folder described above
--video <path>                Optional override for the video file
--qdtrack_fps <float>         QDTrack/Depth FPS (default from config)
--sei_fps <float>             SEI FPS (default from config)
--frame_id_offset <int>       Frame offset between QDTrack and SEI/Depth
--speed_column <name>         SEI CSV column name (default: vehicle_speed_mps)
--label_whitelist <csv>       Keep only these labels (ids or names)
--max_depth_m <float>         Ignore objects deeper than this
```

## SEI extraction (get_sei.py)

`get_sei.py` provides a helper function that downloads a Tesla dashcam video from S3,
checks for SEI metadata, and writes CSV outputs.

Example (run from repo root):

```bash
python -c "from get_sei import get_sei_data; ok, sei_csv, video_path = get_sei_data('s3://bucket/path/video.mp4', output_dir='sei_data', dmp_id=123, org_id='org', key_id='key', vin='VIN'); print(ok, sei_csv, video_path)"
```

Behavior:
- Creates the `output_dir` (it must not already exist).
- Downloads the video into `output_dir/video/`.
- Writes `sei_data_YYYYMMDD_HHMMSS.csv` and `disengagement_data_YYYYMMDD_HHMMSS.csv`.
- Writes a log file `check_single_video_YYYYMMDD_HHMMSS.log` in `output_dir/`.

Note: `sei_data/src/s3_downloader.py` requires AWS credentials (`aws_key`, `aws_secret`).
`get_sei.py` currently does not pass them, so update it (or read from environment) before use.

## Outputs

Outputs are written to `<video_data>/relative_speed_out/`:

- `object_speeds.csv` (per-frame, per-object measurements)
- `track_summary.csv` (per-track aggregates)
- `relative_speed.mp4` (overlay video)

## Troubleshooting

- If `cv2` import fails: `pip install opencv-python`
- If progress bar is missing: `pip install tqdm` (optional)
- If `ImportError` mentions `types`: ensure there is no local `types.py` shadowing
  the Python stdlib in your working directory.
