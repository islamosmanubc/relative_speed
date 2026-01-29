"""Data models for disengagement analysis results."""

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class CoreMLEvent:
    """Represents a CoreML event from DMP data_links."""

    event_id: str
    event: str | list[str]
    timestamp: Optional[int] = None


@dataclass
class DMPResult:
    """Represents a processed DMP with extracted events and metadata."""

    dmp_id: int
    org_id: str
    key_id: str
    vin: Optional[str] = None
    start_time: Optional[int] = None
    end_time: Optional[int] = None
    disengagement_events: list[CoreMLEvent] = field(default_factory=list)
    all_coreml_events: list[CoreMLEvent] = field(default_factory=list)
    video_uris: dict[str, str] = field(default_factory=dict)
    sei_extracted: bool = False
    sei_data_path: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        """Convert DMPResult to dictionary for JSON serialization.

        Returns:
            Dictionary representation of DMPResult
        """
        return {
            "dmp_id": self.dmp_id,
            "org_id": self.org_id,
            "key_id": self.key_id,
            "vin": self.vin,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "disengagement_events": [
                {
                    "event_id": e.event_id,
                    "event": e.event,
                    "timestamp": e.timestamp,
                }
                for e in self.disengagement_events
            ],
            "all_coreml_events": [
                {
                    "event_id": e.event_id,
                    "event": e.event,
                    "timestamp": e.timestamp,
                }
                for e in self.all_coreml_events
            ],
            "video_uris": self.video_uris,
            "sei_extracted": self.sei_extracted,
            "sei_data_path": self.sei_data_path,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DMPResult":
        """Create DMPResult from dictionary.

        Args:
            data: Dictionary with DMP result data

        Returns:
            DMPResult instance
        """
        return cls(
            dmp_id=data["dmp_id"],
            org_id=data["org_id"],
            key_id=data["key_id"],
            vin=data.get("vin"),
            start_time=data.get("start_time"),
            end_time=data.get("end_time"),
            disengagement_events=[
                CoreMLEvent(
                    event_id=e["event_id"],
                    event=e["event"],
                    timestamp=e.get("timestamp"),
                )
                for e in data.get("disengagement_events", [])
            ],
            all_coreml_events=[
                CoreMLEvent(
                    event_id=e["event_id"],
                    event=e["event"],
                    timestamp=e.get("timestamp"),
                )
                for e in data.get("all_coreml_events", [])
            ],
            video_uris=data.get("video_uris", {}),
            sei_extracted=data.get("sei_extracted", False),
            sei_data_path=data.get("sei_data_path"),
        )


@dataclass
class AnalysisSummary:
    """Summary statistics for analysis results."""

    matching_vehicles: int = 0
    dmps_found: int = 0
    dmps_processed: int = 0
    total_disengagement_events: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert AnalysisSummary to dictionary.

        Returns:
            Dictionary representation of AnalysisSummary
        """
        return {
            "matching_vehicles": self.matching_vehicles,
            "dmps_found": self.dmps_found,
            "dmps_processed": self.dmps_processed,
            "total_disengagement_events": self.total_disengagement_events,
        }


@dataclass
class AnalysisMetadata:
    """Metadata about the analysis run."""

    analysis_timestamp: str
    analysis_duration_seconds: float
    analysis_start_time: str
    analysis_end_time: str

    def to_dict(self) -> dict[str, Any]:
        """Convert AnalysisMetadata to dictionary.

        Returns:
            Dictionary representation of AnalysisMetadata
        """
        return {
            "analysis_timestamp": self.analysis_timestamp,
            "analysis_duration_seconds": self.analysis_duration_seconds,
            "analysis_start_time": self.analysis_start_time,
            "analysis_end_time": self.analysis_end_time,
        }
