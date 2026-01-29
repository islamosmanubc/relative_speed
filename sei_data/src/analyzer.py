"""Main analyzer for disengagement events with SEI metadata extraction."""

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from .config import ANALYZER_PROGRESS_INTERVAL
from .database import get_dmps_with_disengagement, extract_disengagement_events, extract_all_coreml_events
from .models import AnalysisMetadata, AnalysisSummary, CoreMLEvent, DMPResult
from .utils import format_datetime_for_display, generate_timestamp
from .vehicle_filter import filter_vehicles
from .sei_extractor import extract_and_save_sei_from_video

logger = logging.getLogger(__name__)


class DisengagementAnalyzer:
    """Analyzer for disengagement events with SEI metadata."""

    def __init__(self, output_dir: Path):
        """Initialize analyzer.

        Args:
            output_dir: Directory to save analysis results
        """
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.results: list[DMPResult] = []
        self.start_time = None
        self.end_time = None

    def analyze(self) -> dict[str, Any]:
        """Run complete analysis pipeline.

        Returns:
            Analysis results dictionary
        """
        self.start_time = time.time()
        start_datetime = datetime.now()
        logger.info(f"Starting disengagement analysis at {format_datetime_for_display(start_datetime)}")

        logger.info("Step 1: Filtering vehicles by TeslaAP4 and firmware >= 2025.44.25.1...")
        matching_vehicles = filter_vehicles()
        logger.info(f"Found {len(matching_vehicles)} vehicles matching criteria")

        if not matching_vehicles:
            logger.warning("No vehicles found matching criteria. Analysis cannot continue.")
            return {
                "summary": {
                    "matching_vehicles": 0,
                    "dmps_found": 0,
                    "dmps_processed": 0,
                },
                "analysis_timestamp": datetime.now().isoformat(),
            }

        logger.info("Step 2: Finding DMPs with disengagement tags...")
        vehicle_triplets = [(v["org_id"], v["key_id"], v.get("vin", "")) for v in matching_vehicles]
        dmps = get_dmps_with_disengagement(vehicle_triplets)
        logger.info(f"Found {len(dmps)} DMPs with disengagement tags")

        if not dmps:
            logger.warning("No DMPs found with disengagement tags.")
            return {
                "summary": {
                    "matching_vehicles": len(matching_vehicles),
                    "dmps_found": 0,
                    "dmps_processed": 0,
                },
                "vehicles": matching_vehicles,
                "analysis_timestamp": datetime.now().isoformat(),
            }

        logger.info("Step 3: Processing DMPs and extracting disengagement events...")
        processed_count = 0
        total_dmps = len(dmps)

        for idx, dmp in enumerate(dmps, 1):
            if idx % ANALYZER_PROGRESS_INTERVAL == 0 or idx == total_dmps:
                logger.info(f"Processing DMP {idx}/{total_dmps}...")

            dmp_result = self._process_dmp(dmp)
            if dmp_result:
                self.results.append(dmp_result)
                processed_count += 1

        self.end_time = time.time()
        total_duration = self.end_time - self.start_time

        self._matching_vehicles = matching_vehicles
        self._matching_vehicles_count = len(matching_vehicles)
        self._dmps_found_count = len(dmps)
        self._analysis_metadata = {
            "analysis_timestamp": datetime.now().isoformat(),
            "analysis_duration_seconds": round(total_duration, 2),
            "analysis_start_time": start_datetime.isoformat(),
            "analysis_end_time": datetime.now().isoformat(),
        }

        summary = self._build_summary(processed_count)

        logger.info(f"Analysis completed in {total_duration:.1f} seconds ({total_duration/60:.1f} minutes)")
        logger.info(f"Processed {processed_count} DMPs with disengagement events")

        return summary

    def save_results(self, filename: Optional[str] = None) -> Path:
        """Save analysis results to JSON file.

        Args:
            filename: Optional filename (default: disengagement_analysis_YYYYMMDD_HHMMSS.json)

        Returns:
            Path to saved file
        """
        if filename is None:
            timestamp = generate_timestamp()
            filename = f"disengagement_analysis_{timestamp}.json"

        output_path = self.output_dir / filename
        output_path.parent.mkdir(parents=True, exist_ok=True)

        summary_data = self._build_summary(len(self.results))
        summary_dict = {
            "summary": summary_data["summary"],
            "vehicles": summary_data["vehicles"],
            "dmps": [result.to_dict() for result in self.results],
            "analysis_metadata": summary_data["analysis_metadata"],
        }

        with open(output_path, "w") as f:
            json.dump(summary_dict, f, indent=2, default=str)

        logger.info(f"Results saved to: {output_path}")
        return output_path

    def extract_sei_from_local_video(self, video_path: Path, dmp_id: int) -> Optional[Path]:
        """Extract SEI metadata from a local video file and save it.

        Args:
            video_path: Path to local video file
            dmp_id: DMP ID for organizing output

        Returns:
            Path to saved SEI data file, or None if extraction failed
        """
        sei_output_path = extract_and_save_sei_from_video(video_path, self.output_dir, dmp_id)

        if sei_output_path:
            for result in self.results:
                if result.dmp_id == dmp_id:
                    result.sei_extracted = True
                    result.sei_data_path = str(sei_output_path)
                    break

        return sei_output_path

    def _build_summary(self, processed_count: Optional[int] = None) -> dict[str, Any]:
        """Build summary dictionary for analysis results.

        Args:
            processed_count: Number of processed DMPs (defaults to len(self.results))

        Returns:
            Complete summary dictionary with summary, vehicles, dmps, and metadata
        """
        if processed_count is None:
            processed_count = len(self.results)

        summary = AnalysisSummary(
            matching_vehicles=getattr(self, "_matching_vehicles_count", 0),
            dmps_found=getattr(self, "_dmps_found_count", len(self.results)),
            dmps_processed=processed_count,
            total_disengagement_events=sum(len(r.disengagement_events) for r in self.results),
        )

        metadata_dict = getattr(self, "_analysis_metadata", {})
        metadata = AnalysisMetadata(
            analysis_timestamp=metadata_dict.get("analysis_timestamp", ""),
            analysis_duration_seconds=metadata_dict.get("analysis_duration_seconds", 0.0),
            analysis_start_time=metadata_dict.get("analysis_start_time", ""),
            analysis_end_time=metadata_dict.get("analysis_end_time", ""),
        )

        return {
            "summary": summary.to_dict(),
            "vehicles": getattr(self, "_matching_vehicles", []),
            "dmps": [result.to_dict() for result in self.results],
            "analysis_metadata": metadata.to_dict(),
        }

    def _process_dmp(self, dmp: dict[str, Any]) -> Optional[DMPResult]:
        """Process a single DMP and extract events.

        Args:
            dmp: DMP record from database

        Returns:
            DMPResult instance or None if processing failed
        """
        dmp_id = dmp["id"]
        org_id = dmp["org_id"]
        key_id = dmp["key_id"]
        data_links = dmp.get("data_links", {})

        all_events_data = extract_all_coreml_events(data_links)
        disengagement_events_data = extract_disengagement_events(data_links)

        all_events = [
            CoreMLEvent(
                event_id=e["event_id"],
                event=e["event"],
                timestamp=e.get("timestamp"),
            )
            for e in all_events_data
        ]
        disengagement_events = [
            CoreMLEvent(
                event_id=e["event_id"],
                event=e["event"],
                timestamp=e.get("timestamp"),
            )
            for e in disengagement_events_data
        ]

        return DMPResult(
            dmp_id=dmp_id,
            org_id=org_id,
            key_id=key_id,
            vin=dmp.get("vin"),
            start_time=dmp.get("start_time"),
            end_time=dmp.get("end_time"),
            disengagement_events=disengagement_events,
            all_coreml_events=all_events,
            video_uris=data_links.get("video", {}),
            sei_extracted=False,
            sei_data_path=None,
        )
