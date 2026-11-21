"""Provide independent JPL station documents compatible with the shared reader."""

from __future__ import annotations

import hashlib
import math
import csv
from pathlib import Path
import re
from html.parser import HTMLParser
from datetime import datetime

from .core import (check_cancellation,fetch_jpl_catalog,validate_payload,)


JPL_COLUMNS = (
    "Decimal_YR",
    "East(m)",
    "North(m)",
    "Vert(m)",
    "E_sig(m)",
    "N_sig(m)",
    "V_sig(m)",
    "E_N_cor",
    "E_V_cor",
    "N_V_cor",
    "Seconds_past_J2000",
    "YEAR",
    "MM",
    "DD",
    "HR",
    "MN",
    "SS",
)

JPL_POSITIONS_URL = "https://sideshow.jpl.nasa.gov/post/tables/table2.html"


class _JPLPositionTextParser(HTMLParser):
    """Extract table text while preserving record boundaries."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)

    def handle_starttag(self, tag, attrs):
        if tag in {"br", "tr", "pre", "p", "div"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"td", "th"}:
            self.parts.append(" ")
        elif tag in {"tr", "pre", "p", "div"}:
            self.parts.append("\n")

def fetch_jpl_positions(transport, is_cancelled=None):
    """Read official reference positions without propagating them in time."""
    check_cancellation(is_cancelled)
    payload = transport.get_bytes(JPL_POSITIONS_URL, is_cancelled)
    check_cancellation(is_cancelled)

    parser = _JPLPositionTextParser()
    parser.feed(payload.decode("utf-8-sig"))
    parser.close()
    text = "".join(parser.parts)

    if not re.search(r"Latitude and longitude in degrees", text, re.I):
        raise ValueError("The JPL position coordinate units are not recognized.")

    position_metadata = {
        "coordinate_source": "JPL_online",
        "position_source_url": JPL_POSITIONS_URL,
    }

    for key, label in (
        ("position_reference_frame", "frame"),
        ("position_reference_epoch", "epoch"),
        ("position_reference_ellipsoid", "ellipsoid"),
    ):
        match = re.search(
            rf"The reference {label} is\s+([^\r\n.]+)",
            text,
            re.I,
        )
        position_metadata[key] = match.group(1).strip() if match else ""

    height_match = re.search(
        r"Height estimates and errors in\s+(mm|cm|m)\s*\.",
        text,
        re.I,
    )
    height_scale = (
        {"mm": 0.001, "cm": 0.01, "m": 1.0}[height_match.group(1).lower()]
        if height_match else None
    )

    records = {}

    for line in text.splitlines():
        check_cancellation(is_cancelled)
        fields = line.split()

        if len(fields) < 5 or fields[1] != "POS":
            continue

        station_id = fields[0].strip().upper()

        try:
            latitude = float(fields[2])
            longitude = float(fields[3])
        except (ValueError, OverflowError):
            continue

        if not (
            math.isfinite(latitude)
            and math.isfinite(longitude)
            and -90 <= latitude <= 90
            and -360 <= longitude <= 360
        ):
            continue

        longitude = (
            longitude - 360 if longitude > 180
            else longitude + 360 if longitude < -180
            else longitude
        )

        height_m = None

        if height_scale is not None:
            try:
                height = float(fields[4]) * height_scale
                height_m = height if math.isfinite(height) else None
            except (ValueError, OverflowError):
                pass

        record = {
            **position_metadata,
            "station_id": station_id,
            "latitude": latitude,
            "longitude": longitude,
            "height_m": height_m,
        }

        if station_id in records:
            if records[station_id] != record:
                # Do not choose between conflicting reference positions.
                records[station_id] = None
        else:
            records[station_id] = record

    check_cancellation(is_cancelled)
    records = {key: value for key, value in records.items() if value is not None}

    if not records:
        raise ValueError("The JPL table contains no usable reference positions.")

    return records


def fetch_jpl_document(transport, station_record, is_cancelled=None):
    """Download a headerless JPL series and provide its documented header."""
    if station_record.get("provider") != "JPL":
        raise ValueError("A JPL station record is required.")

    station_id = str(station_record["station_id"]).strip().upper()
    url = station_record["url"]

    payload = transport.get_bytes(url, is_cancelled)
    check_cancellation(is_cancelled)
    validate_payload(payload)

    source_lines = payload.decode("utf-8-sig").splitlines(keepends=True)

    # Require at least one numeric record with the documented column count.
    usable_record_found = False

    for line in source_lines:
        check_cancellation(is_cancelled)
        fields = line.split()

        if len(fields) != len(JPL_COLUMNS):
            continue

        try:
            usable_record_found = all(math.isfinite(float(value)) for value in fields)
        except (ValueError, OverflowError):
            continue

        if usable_record_found:
            break

    if not usable_record_found:
        raise ValueError("The response contains no usable 17-column JPL records.")

    # Keep every original line so the shared reader can count rejected rows.
    prepared_columns = (*JPL_COLUMNS, "_JPL_MJD")
    lines = [" ".join(prepared_columns) + "\n"]

    for line_number, line in enumerate(source_lines, 1):
        check_cancellation(is_cancelled)
        fields = line.split()

        if len(fields) != len(JPL_COLUMNS):
            # Preserve one rejected-row entry without accepting malformed input.
            lines.append("_JPL_REJECTED_ROW\n")
            continue

        try:
            mjd = _jpl_calendar_to_mjd(fields)
        except (ValueError, OverflowError) as error:
            raise ValueError(
                f"Invalid JPL calendar at source line {line_number}: {error}"
            ) from error

        lines.append(
            line.rstrip("\r\n") + f" {mjd!r}\n"
        )

    check_cancellation(is_cancelled)

    return {
        "station_id": station_id,
        "site": station_record.get("site", ""),
        "provider": "JPL",
        "source_name": f"{station_id}.series",
        "source_url": url,
        "format": "jpl_series",
        "header_generated": True,
        "lines": lines,
        "original_lines": tuple(source_lines),
        "derived_epoch_column": "_JPL_MJD",
        "derived_epoch_format": "JJJJJ.JJJJJ",
        "time_scale": "unspecified",
        "byte_count": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "metadata": dict(station_record),
    }

def load_jpl_local_metadata(data_dir, is_cancelled=None):
    """Read optional JPL metadata silently without requiring descriptive fields."""
    check_cancellation(is_cancelled)
    records = {}

    try:
        matches = [
            path for path in Path(data_dir).iterdir()
            if path.is_file() and path.name.casefold() == "jpl.csv"
        ]

        if len(matches) != 1:
            return {}

        with matches[0].open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            required = {
                "CODE", "DOMES", "STATION_DESCRIPTION",
                "CITY", "REGION", "COUNTRY", "LAT", "LONG", "HEIGHT",
            }

            if not required.issubset(reader.fieldnames or []):
                return {}

            for row in reader:
                check_cancellation(is_cancelled)
                station_id = (row.get("CODE") or "").strip().upper()

                if not station_id:
                    continue

                attributes = {
                    name.lower(): (row.get(name) or "").strip()
                    for name in (
                        "DOMES", "STATION_DESCRIPTION",
                        "CITY", "REGION", "COUNTRY", "HEIGHT",
                    )
                }

                attributes["station_id"] = station_id
                attributes["site"] = "/".join(
                    attributes[name]
                    for name in ("city", "region", "country")
                    if attributes[name]
                )

                latitude = longitude = None

                try:
                    lat = float((row.get("LAT") or "").strip())
                    lon = float((row.get("LONG") or "").strip())

                    if math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -360 <= lon <= 360:
                        latitude = lat
                        longitude = lon - 360 if lon > 180 else lon + 360 if lon < -180 else lon

                except (ValueError, OverflowError):
                    pass

                attributes["latitude"] = latitude
                attributes["longitude"] = longitude

                if station_id in records:
                    if records[station_id] != attributes:
                        # Do not choose between conflicting duplicate records.
                        records[station_id] = None
                else:
                    records[station_id] = attributes

    except (OSError, UnicodeError, csv.Error):
        return {}

    check_cancellation(is_cancelled)
    return {key: value for key, value in records.items() if value is not None}

def fetch_jpl_station_records(transport, data_dir, is_cancelled=None):
    """Combine the JPL catalog with official positions and local metadata."""
    check_cancellation(is_cancelled)
    catalog = fetch_jpl_catalog(transport, is_cancelled)

    if not catalog:
        return {}, None

    local_metadata = load_jpl_local_metadata(data_dir, is_cancelled)

    positions = {}
    metadata_error = None

    try:
        positions = fetch_jpl_positions(transport, is_cancelled)
    except Exception as error:
        # Cancellation must not become a metadata fallback.
        check_cancellation(is_cancelled)
        metadata_error = f"{type(error).__name__}: {error}"

    records = {}

    for station_id, urls in catalog.items():
        check_cancellation(is_cancelled)
        local = local_metadata.get(station_id, {})
        official = positions.get(station_id)

        record = {
            "station_id": station_id,
            "provider": "JPL",
            "url": urls[0],
            "site": local.get("site", ""),
            "domes": local.get("domes", ""),
            "station_description": local.get("station_description", ""),
            "latitude": None,
            "longitude": None,
            "height_m": None,
            "coordinate_source": "",
            "position_source_url": "",
            "position_reference_frame": "",
            "position_reference_epoch": "",
            "position_reference_ellipsoid": "",
            "local_metadata": dict(local),
        }

        if official is not None:
            record.update(official)

        elif (
            local.get("latitude") is not None
            and local.get("longitude") is not None
        ):
            record.update({
                "latitude": local["latitude"],
                "longitude": local["longitude"],
                "height_m": local.get("height_m"),
                "coordinate_source": "JPL_csv",
            })

        records[station_id] = record

    check_cancellation(is_cancelled)
    return records, metadata_error

def _jpl_calendar_to_mjd(fields):
    """Express the supplied calendar fields as MJD without a time-scale shift."""
    year, month, day, hour, minute = (
        int(value) for value in fields[11:16]
    )
    seconds = float(fields[16])

    if not math.isfinite(seconds) or not 0 <= seconds < 60:
        raise ValueError(
            "JPL calendar seconds must be finite and within [0, 60)."
        )

    stamp = datetime(year, month, day, hour, minute)
    elapsed = (stamp - datetime(2000, 1, 1)).total_seconds() + seconds

    return 51544.0 + elapsed / 86400.0