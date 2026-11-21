"""Probe an EPOS–INGV time-series download without parsing observations."""

from argparse import ArgumentParser
from pathlib import Path
from urllib.parse import urlsplit
import re
import json

if __package__:
    from .core import (
        CatalogParseError,
        StandardHttpTransport,
        check_cancellation,
        validate_payload,
    )
else:
    # Allow the catalog probe to run outside QGIS.
    from core import (
        CatalogParseError,
        StandardHttpTransport,
        check_cancellation,
        validate_payload,
    )


def fetch_epos_payload(transport, request_url, is_cancelled=None):
    """Fetch and validate the raw response using the shared HTTP transport."""
    url = urlsplit(request_url)
    if url.scheme != "https" or not url.hostname:
        raise ValueError("Use the full HTTPS URL of the EPOS download request.")

    payload = transport.get_bytes(request_url, is_cancelled)
    validate_payload(payload)
    return payload


EPOS_TIMESERIES_URL = (
    "https://gnssproducts.epos.ubi.pt/GlassFramework/webresources/"
    "products/timeseries"
)

# The catalog route requires no trailing slash.
EPOS_STATIONS_URL = f"{EPOS_TIMESERIES_URL}/stations"


def fetch_epos_station_records(transport, is_cancelled=None):
    """Return stations advertising daily UGA-CNRS position series."""
    payload = transport.get_bytes(EPOS_STATIONS_URL, is_cancelled)

    try:
        entries = json.loads(payload)
    except (ValueError, UnicodeError) as error:
        raise CatalogParseError("The EPOS station catalog is not valid JSON.") from error

    if not isinstance(entries, list):
        raise CatalogParseError("The EPOS station catalog must contain a list.")

    stations = {}

    for entry in entries:
        check_cancellation(is_cancelled)
        if not isinstance(entry, dict):
            continue

        marker = str(entry.get("marker") or "").strip().upper()
        if not re.fullmatch(r"[A-Z0-9]{9}", marker):
            continue

        products = entry.get("ac_array")
        if not isinstance(products, list):
            continue

        # Both conditions must match the same product, not different centres.
        if not any(
            isinstance(product, dict)
            and product.get("acronym") == "UGA-CNRS"
            and product.get("samplingPeriod") == "daily"
            for product in products
        ):
            continue

        # Inspect station metadata without dumping the product list.
        if marker in {"REYK00ISL", "HOS000SWE"}:
            metadata = {
                key: value
                for key, value in entry.items()
                if key != "ac_array"
            }

        # Preserve the country supplied by the catalog.
        location = entry.get("location")
        country = (
            str(location.get("country") or "").strip()
            if isinstance(location, dict)
            else ""
        )

        # Display the EPOS locality in the existing Region column.
        locality = (
            str(location.get("location") or "").strip()
            if isinstance(location, dict)
            else ""
        )

        stations[marker] = {
            "provider": "EPOS",
            "station_id": marker,
            "site": str(entry.get("name") or "").strip(),
            "local_metadata": {
                "region": locality,
                "country": country,
            },
        }

    if not stations:
        raise CatalogParseError("No daily UGA-CNRS stations were found.")

    # Match the existing controller contract: stations, metadata error.
    return stations, None


def build_epos_timeseries_url(marker):
    """Build the verified UGA-CNRS ENU/PBO request for one station."""
    marker = marker.strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{9}", marker):
        raise ValueError("An EPOS station marker must have nine characters.")

    return f"{EPOS_TIMESERIES_URL}/{marker}/UGA-CNRS/enu/pbo/?file=true"


def prepare_epos_pbo_lines(payload):
    """Return a whitespace-delimited header and rows for GVDA."""
    source = payload.decode("utf-8-sig").splitlines()

    for index, line in enumerate(source):
        fields = line.split()
        if not fields or fields[0] != "*YYYYMMDD":
            continue

        columns = ["YYYYMMDD", *fields[1:]]
        required = {"YYYYMMDD", "dN", "dE", "NLat", "Elong"}
        if not required.issubset(columns):
            raise ValueError("The EPOS PBO header lacks required columns.")

        # Keep original row order and values; let GVDA check row widths.
        rows = tuple(line.strip() for line in source[index + 1:] if line.strip())
        if not rows:
            raise ValueError("The EPOS PBO contains no observation rows.")

        return (" ".join(columns), *rows)

    raise ValueError("The EPOS response has no *YYYYMMDD observation header.")

def fetch_epos_document(transport, marker, is_cancelled=None):
    """Download and prepare one UGA-CNRS station for the GVDA reader."""
    marker = marker.strip().upper()
    url = build_epos_timeseries_url(marker)
    payload = fetch_epos_payload(transport, url, is_cancelled)

    # Return the header and observations in the controller's reader format.
    return {
        "provider": "EPOS",
        "analysis_centre": "UGA-CNRS",
        "station_id": marker,
        "lines": prepare_epos_pbo_lines(payload),
    }


def main():
    """Save the original response and print a short inspection preview."""
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("url", help="Full HTTPS URL copied from the GET request.")
    parser.add_argument("--output", type=Path, default=Path("epos_response.bin"))
    args = parser.parse_args()

    try:
        transport = StandardHttpTransport(timeout=30, max_retries=1)
        payload = fetch_epos_payload(transport, args.url)

        # Keep the original bytes; do not overwrite an earlier probe.
        with args.output.open("xb") as output:
            output.write(payload)
    except (OSError, RuntimeError, ValueError) as error:
        parser.exit(1, f"{type(error).__name__}: {error}\n")

    # repr keeps non-printable bytes visible without assuming a text format.
    print(f"Saved {len(payload)} bytes to {args.output}")
    print(f"First bytes: {payload[:1000]!r}")


if __name__ == "__main__":
    main()