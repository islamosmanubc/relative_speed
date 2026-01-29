"""Filter vehicles by TeslaAP4 and firmware version requirements."""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Optional

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from .config import (
    KEY_TABLE,
    MIN_VERSION,
    REQUIRED_DRIVER_ASSIST,
    VEHICLE_TABLE,
    VEHICLE_LOOKUP_MAX_WORKERS,
    VEHICLE_LOOKUP_BOTO3_POOL_HEADROOM,
    VEHICLE_LOOKUP_PROGRESS_INTERVAL,
    S3_MAX_RETRIES,
)

logger = logging.getLogger(__name__)

# Module-level DynamoDB resources (reused across calls)
_dynamodb_resource = None
_vehicle_table = None
_key_table = None

_BOTO3_CONFIG = Config(
    max_pool_connections=VEHICLE_LOOKUP_MAX_WORKERS + VEHICLE_LOOKUP_BOTO3_POOL_HEADROOM,
    retries={"max_attempts": S3_MAX_RETRIES, "mode": "standard"},
)


def get_vehicle_table():
    """Get or create DynamoDB vehicle table resource (reused across calls).

    Returns:
        DynamoDB Table resource for TeslaVehicle table
    """
    global _vehicle_table
    if _vehicle_table is None:
        global _dynamodb_resource
        if _dynamodb_resource is None:
            _dynamodb_resource = boto3.resource("dynamodb", config=_BOTO3_CONFIG)
        _vehicle_table = _dynamodb_resource.Table(VEHICLE_TABLE)
    return _vehicle_table


def get_key_table():
    """Get or create DynamoDB key table resource (reused across calls).

    Returns:
        DynamoDB Table resource for Key table
    """
    global _key_table
    if _key_table is None:
        global _dynamodb_resource
        if _dynamodb_resource is None:
            _dynamodb_resource = boto3.resource("dynamodb", config=_BOTO3_CONFIG)
        _key_table = _dynamodb_resource.Table(KEY_TABLE)
    return _key_table


def parse_version(version_str: str) -> tuple[int, int, int, int]:
    """Parse car version string into tuple for comparison.

    Args:
        version_str: Version string like "2025.44.25.1" or "2025.38.9.5 a7c052f420c9"

    Returns:
        Tuple of (year, major, minor, patch) or (0, 0, 0, 0) if invalid
    """
    if not version_str:
        return (0, 0, 0, 0)

    try:
        # Extract version part (before space if present)
        version_part = version_str.split()[0]
        parts = version_part.split(".")
        if len(parts) >= 4:
            return (int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3]))
        if len(parts) == 3:
            return (int(parts[0]), int(parts[1]), int(parts[2]), 0)
        if len(parts) == 2:
            return (int(parts[0]), int(parts[1]), 0, 0)
        return (0, 0, 0, 0)
    except (ValueError, IndexError):
        return (0, 0, 0, 0)


def version_meets_requirement(version_str: str) -> bool:
    """Check if car version meets minimum requirement (2025.44.25.1 or newer).

    Args:
        version_str: Version string from TeslaVehicle table

    Returns:
        True if version >= 2025.44.25.1, False otherwise
    """
    version_tuple = parse_version(version_str)
    return version_tuple >= MIN_VERSION


def get_vehicle_info(vehicle_id: str) -> Optional[dict[str, Any]]:
    """Get vehicle information from TeslaVehicle table.

    Args:
        vehicle_id: Tesla vehicle ID

    Returns:
        Vehicle item from DynamoDB or None if not found
    """
    try:
        vehicle_table = get_vehicle_table()
        response = vehicle_table.get_item(Key={"id": vehicle_id})
        if "Item" in response:
            return response["Item"]
    except ClientError as e:
        logger.debug(f"Error querying TeslaVehicle table for vehicle_id={vehicle_id}: {e}")
    return None


def _extract_vehicle_attributes(vehicle_item: dict[str, Any]) -> Optional[dict[str, str]]:
    """Extract vehicle attributes from DynamoDB item.

    Args:
        vehicle_item: Vehicle item from DynamoDB

    Returns:
        Dictionary with vin, car_version, driver_assist or None if missing required fields
    """
    snapshot = vehicle_item.get("snapshot", {})
    vehicle_config = snapshot.get("vehicle_config", {})
    vehicle_state = snapshot.get("vehicle_state", {})
    car_version = vehicle_state.get("car_version", "")
    driver_assist = vehicle_config.get("driver_assist", "")
    vin = vehicle_item.get("VIN", "")

    return {
        "vin": vin,
        "car_version": car_version,
        "driver_assist": driver_assist,
    }


def _matches_criteria(vehicle_attrs: dict[str, str]) -> bool:
    """Check if vehicle attributes match filtering criteria.

    Args:
        vehicle_attrs: Dictionary with driver_assist and car_version

    Returns:
        True if vehicle matches TeslaAP4 and firmware >= 2025.44.25.1
    """
    driver_assist = vehicle_attrs.get("driver_assist", "")
    car_version = vehicle_attrs.get("car_version", "")

    if driver_assist != REQUIRED_DRIVER_ASSIST:
        return False

    return version_meets_requirement(car_version)


def filter_vehicles() -> list[dict[str, str]]:
    """Find all vehicles matching TeslaAP4 and firmware >= 2025.44.25.1.

    Returns:
        List of dictionaries with keys: org_id, key_id, vehicle_id, car_version, driver_assist
    """
    key_table = get_key_table()

    logger.info("Scanning Key table to find all keys...")
    matching_vehicles = []
    scan_kwargs = {}
    total_keys_scanned = 0
    keys_with_vehicles = 0
    vehicle_lookups = []

    while True:
        try:
            response = key_table.scan(**scan_kwargs)
            items = response.get("Items", [])
            total_keys_scanned += len(items)

            for key_item in items:
                key_id = key_item.get("id")
                org_id = key_item.get("org_id")
                tesla_vehicle_id = key_item.get("tesla_vehicle_id")

                if not key_id or not org_id:
                    continue

                if not tesla_vehicle_id:
                    continue

                keys_with_vehicles += 1
                vehicle_lookups.append((key_item, tesla_vehicle_id))

            last_evaluated_key = response.get("LastEvaluatedKey")
            if not last_evaluated_key:
                break

            scan_kwargs["ExclusiveStartKey"] = last_evaluated_key
            logger.info(f"Scanned {total_keys_scanned} keys, found {keys_with_vehicles} with vehicles so far...")

        except ClientError as e:
            logger.error(f"Error scanning Key table: {e}")
            break

    logger.info(f"Processing {len(vehicle_lookups)} vehicle lookups in parallel...")
    with ThreadPoolExecutor(max_workers=VEHICLE_LOOKUP_MAX_WORKERS) as executor:
        future_to_key = {
            executor.submit(get_vehicle_info, tesla_vehicle_id): (key_item, tesla_vehicle_id)
            for key_item, tesla_vehicle_id in vehicle_lookups
        }

        processed_count = 0
        for future in as_completed(future_to_key):
            key_item, tesla_vehicle_id = future_to_key[future]
            processed_count += 1

            try:
                vehicle_item = future.result()
            except Exception as e:
                logger.debug(f"Error fetching vehicle {tesla_vehicle_id}: {e}")
                continue

            if not vehicle_item:
                continue

            vehicle_attrs = _extract_vehicle_attributes(vehicle_item)
            if not vehicle_attrs:
                continue

            if not _matches_criteria(vehicle_attrs):
                continue

            key_id = key_item.get("id")
            org_id = key_item.get("org_id")
            matching_vehicles.append(
                {
                    "org_id": org_id,
                    "key_id": key_id,
                    "vehicle_id": tesla_vehicle_id,
                    "vin": vehicle_attrs["vin"],
                    "car_version": vehicle_attrs["car_version"],
                    "driver_assist": vehicle_attrs["driver_assist"],
                }
            )

            if processed_count % VEHICLE_LOOKUP_PROGRESS_INTERVAL == 0 or processed_count == len(vehicle_lookups):
                logger.info(
                    f"Processed {processed_count}/{len(vehicle_lookups)} vehicles, "
                    f"found {len(matching_vehicles)} matching criteria so far..."
                )

    logger.info(
        f"Completed scan: {total_keys_scanned} total keys, {keys_with_vehicles} with vehicles, "
        f"{len(matching_vehicles)} matching TeslaAP4 + firmware >= 2025.44.25.1"
    )

    return matching_vehicles
