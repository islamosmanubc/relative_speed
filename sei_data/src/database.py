"""Database connection and query functions for disengagement DMP analysis."""

import contextlib
import getpass
import logging
import os
from typing import Any, Iterator, Optional

import psycopg2
from psycopg2 import pool
from dotenv import load_dotenv

from .config import (
    DB_CONFIG,
    DB_POOL_MAX_CONN,
    DB_POOL_MIN_CONN,
    DB_QUERY_BATCH_SIZE,
    DEFAULT_MIN_START_TIME,
)

load_dotenv()

logger = logging.getLogger(__name__)

# Connection pool (lazy initialization)
_connection_pool: Optional[pool.SimpleConnectionPool] = None

# SQL query fragments
_DISENGAGEMENT_EVENT_CHECK = """
    SELECT 1
    FROM jsonb_each(data_links->'coreml') AS event_entry
    WHERE jsonb_typeof(event_entry.value->'event') IN ('string', 'array')
        AND (
            -- Check if event is a string containing "dis" or "disengagement"
            (jsonb_typeof(event_entry.value->'event') = 'string'
             AND (
                 LOWER(event_entry.value->>'event') LIKE '%%dis%%'
                 OR LOWER(event_entry.value->>'event') LIKE '%%disengagement%%'
             ))
            OR
            -- Check if event is an array containing "dis" or "disengagement"
            (jsonb_typeof(event_entry.value->'event') = 'array'
             AND EXISTS (
                 SELECT 1
                 FROM jsonb_array_elements_text(event_entry.value->'event') AS tag
                 WHERE LOWER(tag) LIKE '%%dis%%'
                    OR LOWER(tag) LIKE '%%disengagement%%'
             ))
        )
"""


def get_db_connection():
    """Create a database connection (for non-pooled use)."""
    password = os.getenv("DB_PASSWORD")

    if not password:
        password = getpass.getpass("Please enter database password: ")

    try:
        return psycopg2.connect(password=password, sslmode="require", **DB_CONFIG)
    except Exception as e:
        logger.error(f"Error connecting to database: {e}")
        raise


def get_connection_pool() -> pool.SimpleConnectionPool:
    """Get or create database connection pool.

    Returns:
        Connection pool instance
    """
    global _connection_pool
    if _connection_pool is None:
        password = os.getenv("DB_PASSWORD")
        if not password:
            password = getpass.getpass("Please enter database password: ")

        try:
            _connection_pool = pool.SimpleConnectionPool(
                minconn=DB_POOL_MIN_CONN,
                maxconn=DB_POOL_MAX_CONN,
                password=password,
                sslmode="require",
                **DB_CONFIG,
            )
            logger.info(f"Created database connection pool (min={DB_POOL_MIN_CONN}, max={DB_POOL_MAX_CONN})")
        except Exception as e:
            logger.error(f"Error creating connection pool: {e}")
            raise
    return _connection_pool


def close_connection_pool():
    """Close the database connection pool."""
    global _connection_pool
    if _connection_pool is not None:
        _connection_pool.closeall()
        _connection_pool = None
        logger.info("Closed database connection pool")


@contextlib.contextmanager
def db_connection() -> Iterator[psycopg2.extensions.connection]:
    """Context manager for database connections.

    Yields:
        Database connection that is automatically closed on exit
    """
    conn = get_db_connection()
    try:
        yield conn
    finally:
        conn.close()


def _execute_query(query: str, params: Optional[tuple] = None) -> list[dict[str, Any]]:
    """Execute a database query and return results as list of dictionaries.

    Args:
        query: SQL query to execute
        params: Optional query parameters

    Returns:
        List of dictionaries representing query results
    """
    connection_pool = get_connection_pool()
    conn = connection_pool.getconn()
    try:
        cursor = conn.cursor()
        try:
            cursor.execute(query, params)
            rows = cursor.fetchall()
            column_names = [desc[0] for desc in cursor.description]
            return [dict(zip(column_names, row)) for row in rows]
        finally:
            cursor.close()
    finally:
        connection_pool.putconn(conn)


def _build_vehicle_where_clause(vehicle_triplets: list[tuple[str, str, str]]) -> tuple[str, list[Any]]:
    """Build WHERE clause for vehicle matching.

    Args:
        vehicle_triplets: List of (org_id, key_id, vin) tuples to filter by

    Returns:
        Tuple of (SQL WHERE clause, parameter list)
    """
    vehicle_conditions = []
    params = []

    for org_id, key_id, vin in vehicle_triplets:
        if not vin:
            logger.warning(f"Vehicle with org_id={org_id}, key_id={key_id} has no VIN - skipping")
            continue
        vehicle_conditions.append("(org_id = %s AND key_id = %s AND vin = %s)")
        params.extend([org_id, key_id, vin])

    vehicle_clause = " OR ".join(vehicle_conditions) if vehicle_conditions else "FALSE"
    return vehicle_clause, params


def _build_disengagement_query(
    vehicle_clause: str, params: list[Any], min_start_time: int, limit: Optional[int] = None
) -> tuple[str, tuple]:
    """Build SQL query for DMPs with disengagement events.

    Args:
        vehicle_clause: SQL WHERE clause for vehicle matching
        params: Query parameters for vehicle matching
        min_start_time: Minimum start_time timestamp
        limit: Optional limit on number of records

    Returns:
        Tuple of (SQL query string, complete parameter tuple)
    """
    query_params = params + [min_start_time]
    limit_clause = f"LIMIT {limit}" if limit else ""

    query = f"""
    SELECT
        id, org_id, key_id, vin, start_time, end_time,
        data_links, data_source_status, dmp_status,
        created_at, updated_at, failure_reason,
        bundle_id, in_bundle_seq
    FROM public.dmp
    WHERE ({vehicle_clause})
        AND dmp_status = 'SUCCESS'
        AND start_time >= %s
        AND jsonb_typeof(data_links->'coreml') = 'object'
        AND data_links->'coreml' IS NOT NULL
        AND EXISTS ({_DISENGAGEMENT_EVENT_CHECK})
    ORDER BY created_at DESC
    {limit_clause};
    """

    return query, tuple(query_params)


def get_dmps_with_disengagement(
    vehicle_triplets: list[tuple[str, str, str]],
    limit: Optional[int] = None,
    min_start_time: Optional[int] = None,
) -> list[dict[str, Any]]:
    """Get DMPs with disengagement tags from specified vehicles.

    Args:
        vehicle_triplets: List of (org_id, key_id, vin) tuples to filter by
        limit: Optional limit on number of records (applied to total results)
        min_start_time: Optional Unix timestamp (UTC) - only return DMPs with start_time >= this value.
            Defaults to 1765152000 (December 8, 2025 00:00:00 UTC).

    Returns:
        List of DMP records with disengagement events
    """
    if not vehicle_triplets:
        return []

    if min_start_time is None:
        min_start_time = DEFAULT_MIN_START_TIME

    # Filter out invalid triplets first
    valid_triplets = [
        (org_id, key_id, vin) for org_id, key_id, vin in vehicle_triplets if vin  # Skip vehicles without VIN
    ]

    if not valid_triplets:
        logger.warning("No valid vehicle triplets after filtering")
        return []

    logger.info(
        f"Querying DMPs with disengagement tags for {len(valid_triplets)} vehicle(s) "
        f"(start_time >= {min_start_time})..."
    )

    all_results = []
    batch_size = DB_QUERY_BATCH_SIZE

    if len(valid_triplets) <= batch_size:
        vehicle_clause, vehicle_params = _build_vehicle_where_clause(valid_triplets)
        query, params = _build_disengagement_query(vehicle_clause, vehicle_params, min_start_time, limit)
        results = _execute_query(query, params)
        all_results.extend(results)
    else:
        total_batches = (len(valid_triplets) + batch_size - 1) // batch_size
        logger.info(f"Splitting query into {total_batches} batch(es) of up to {batch_size} vehicles each")

        remaining_limit = limit
        for i in range(0, len(valid_triplets), batch_size):
            batch = valid_triplets[i : i + batch_size]
            batch_num = (i // batch_size) + 1

            vehicle_clause, vehicle_params = _build_vehicle_where_clause(batch)
            batch_limit = remaining_limit if remaining_limit is not None else None
            query, params = _build_disengagement_query(vehicle_clause, vehicle_params, min_start_time, batch_limit)

            logger.debug(f"Processing batch {batch_num}/{total_batches} ({len(batch)} vehicles)...")
            batch_results = _execute_query(query, params)
            all_results.extend(batch_results)

            if remaining_limit is not None:
                remaining_limit -= len(batch_results)
                if remaining_limit <= 0:
                    break

    logger.info(f"Found {len(all_results)} DMPs with disengagement tags")
    return all_results


def extract_all_coreml_events(data_links: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract all coreml events from DMP data_links.

    Args:
        data_links: DMP data_links JSONB field

    Returns:
        List of all event dictionaries with event_id, event, timestamp
    """
    events = []
    coreml_data = data_links.get("coreml", {})

    if not isinstance(coreml_data, dict):
        return events

    for event_id, event_data in coreml_data.items():
        if not isinstance(event_data, dict):
            continue

        event_field = event_data.get("event")
        if not event_field:
            continue

        # Extract event(s) - can be string or list
        event_tags = []
        if isinstance(event_field, str):
            event_tags = [event_field]
        elif isinstance(event_field, list):
            event_tags = [str(tag) for tag in event_field]

        if event_tags:
            events.append(
                {
                    "event_id": event_id,
                    "event": event_tags if len(event_tags) > 1 else event_tags[0],
                    "timestamp": event_data.get("timestamp"),
                }
            )

    return events


def _is_disengagement_event(event_field: Any) -> bool:
    """Check if an event field contains disengagement tags.

    Args:
        event_field: Event field (string or list)

    Returns:
        True if event contains "dis" or "disengagement", False otherwise
    """
    if isinstance(event_field, str):
        event_lower = event_field.lower()
        return "dis" in event_lower or "disengagement" in event_lower
    if isinstance(event_field, list):
        return any("dis" in str(tag).lower() or "disengagement" in str(tag).lower() for tag in event_field)
    return False


def extract_disengagement_events(data_links: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract disengagement events from DMP data_links.

    Args:
        data_links: DMP data_links JSONB field

    Returns:
        List of disengagement event dictionaries with event_id, event, timestamp
    """
    disengagement_events = []
    coreml_data = data_links.get("coreml", {})

    if not isinstance(coreml_data, dict):
        return disengagement_events

    for event_id, event_data in coreml_data.items():
        if not isinstance(event_data, dict):
            continue

        event_field = event_data.get("event")
        if not event_field:
            continue

        # Check if this is a disengagement event before processing
        if not _is_disengagement_event(event_field):
            continue

        # Extract event(s) - can be string or list
        event_tags = []
        if isinstance(event_field, str):
            event_tags = [event_field]
        elif isinstance(event_field, list):
            event_tags = [str(tag) for tag in event_field]

        if event_tags:
            disengagement_events.append(
                {
                    "event_id": event_id,
                    "event": event_tags if len(event_tags) > 1 else event_tags[0],
                    "timestamp": event_data.get("timestamp"),
                }
            )

    return disengagement_events
