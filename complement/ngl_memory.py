"""Provide NGL metadata retrieval and independent in-memory documents."""

from __future__ import annotations

import hashlib

from .core import (
    check_cancellation,
    fetch_ngl_catalog,
    validate_payload,
)


NGL_METADATA_URL = (
    "https://geodesy.unr.edu/"
    "NGLStationPages/DataHoldings.txt"
)

NGL_PRODUCT_DESCRIPTION = (
    "Daily GNSS position time series in ASCII (.tenv3) format, based on 24-hour final solutions in the IGS20 reference frame."
)


def fetch_ngl_metadata(transport, is_cancelled=None):
    """Read NGL station coordinates, dates, and original site names."""
    payload = transport.get_bytes(
        NGL_METADATA_URL,
        is_cancelled,
    )

    metadata = {}

    for line in payload.decode("utf-8-sig").splitlines():
        check_cancellation(is_cancelled)

        # The optional site name may contain whitespace.
        fields = line.split(maxsplit=11)

        if len(fields) < 11 or fields[0] == "Sta":
            continue

        try:
            station_id = fields[0].upper()

            metadata[station_id] = {
                "station_id": station_id,
                "site": fields[11].strip() if len(fields) > 11 else "",
                "latitude": float(fields[1]),
                "longitude": float(fields[2]),
                "height_m": float(fields[3]),
                "start_date": fields[7],
                "end_date": fields[8],
                "modified_date": fields[9],
                "solution_count": int(fields[10]),
            }

        except (ValueError, IndexError):
            continue

    return metadata


def fetch_ngl_station_records(transport, is_cancelled=None):
    """Combine the global station catalog with optional metadata.

    Metadata failure does not prevent the station catalog from loading.

    Returns
    -------
    tuple
        Station records and an optional metadata error description.
    """
    catalog = fetch_ngl_catalog(
        transport,
        is_cancelled,
    )

    # Skip metadata retrieval when the catalog contains no stations.
    if not catalog:
        return {}, None
    
    metadata_error = None

    try:
        metadata = fetch_ngl_metadata(
            transport,
            is_cancelled,
        )
    except Exception as error:
        # Do not convert a cancellation request into a metadata warning.
        check_cancellation(is_cancelled)
        metadata = {}
        metadata_error = f"{type(error).__name__}: {error}"

    records = {}

    for station_id, urls in catalog.items():
        record = dict(metadata.get(station_id, {}))

        record.update({
            "station_id": station_id,
            "site": record.get("site", ""),
            "url": urls[0],
            "provider": "NGL",
        })

        records[station_id] = record

    return records, metadata_error


def fetch_ngl_document(
    transport,
    station_record,
    is_cancelled=None,
):
    """Download one station without saving or merging its contents.

    Returns
    -------
    dict
        Independent document containing original text lines and metadata.

    Notes
    -----
    Row-length validation remains the responsibility of the existing
    reader. This function only checks the response and required header.
    """
    station_id = station_record["station_id"]
    url = station_record["url"]

    payload = transport.get_bytes(url, is_cancelled)
    check_cancellation(is_cancelled)

    validate_payload(payload)

    lines = payload.decode("utf-8-sig").splitlines(
        keepends=True
    )

    if not lines:
        raise ValueError("The downloaded document is empty.")

    header = lines[0].split()

    required_columns = {
        "site",
        "__MJD",
        "__east(m)",
        "_north(m)",
        "____up(m)",
    }

    if not required_columns.issubset(header):
        raise ValueError(
            "The response does not contain the expected tenv3 header."
        )

    if not any(line.strip() for line in lines[1:]):
        raise ValueError(
            "The downloaded document has no data records."
        )

    check_cancellation(is_cancelled)

    return {
        "station_id": station_id,
        "site": station_record.get("site", ""),
        "provider": "NGL",
        "source_name": f"{station_id}.tenv3",
        "source_url": url,
        "format": "tenv3",
        "solution": "final",
        "reference_frame": "IGS20",
        "lines": lines,
        "byte_count": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "metadata": dict(station_record),
    }