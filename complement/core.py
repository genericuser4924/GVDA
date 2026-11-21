"""Provide portable HTTP and GNSS catalog utilities.

This module uses only the Python standard library.

Provider functions receive an HTTP transport object so that the same
catalog logic can run in Spyder or within a QGIS plugin.

Notes
-----
HTTP responses are buffered in memory. Large archive downloads should
use a separate streaming implementation.
"""

from __future__ import annotations

import time
import re

from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urljoin, urlsplit
from urllib.request import Request, urlopen


CancellationCallback = Callable[[], bool]
StationCatalog = Dict[str, List[str]]


NGL_CATALOG_URL = (
    "https://geodesy.unr.edu/"
    "NGLStationPages/GlobalStationList"
)

NGL_IGS20_BASE_URL = (
    "https://geodesy.unr.edu/"
    "gps_timeseries/IGS20/tenv3/IGS20/"
)

JPL_SERIES_DIRECTORY_URL = (
    "https://sideshow.jpl.nasa.gov/"
    "pub/JPL_GPS_Timeseries/"
    "repro2018a/post/point/"
)

STATION_PATH_PATTERN = re.compile(
    r"/stations/([A-Za-z0-9_]{4})\.sta$"
)

JPL_FILENAME_PATTERN = re.compile(
    r"([A-Za-z0-9_]{4})\.series"
)

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class OperationCancelled(Exception):
    """Indicate that the current operation was cancelled."""


class CatalogError(RuntimeError):
    """Indicate that a station catalog could not be interpreted."""


class CatalogParseError(CatalogError):
    """Indicate that a catalog response has an unrecognized structure."""


class InvalidDownloadError(RuntimeError):
    """Indicate that a downloaded response is not a usable data payload."""

class NglCatalogStructureParser(HTMLParser):
    """Inspect basic catalog identity and table contents."""

    def __init__(self):
        super().__init__(convert_charrefs=True)

        self.table_count = 0
        self.text_parts = []
        self.cell_values = []

        self._inside_cell = False
        self._cell_parts = []

    def handle_starttag(self, tag, attrs):
        """Track tables and collect table-cell text."""
        tag = tag.lower()

        if tag == "table":
            self.table_count += 1

        elif tag in {"td", "th"}:
            self._inside_cell = True
            self._cell_parts = []

    def handle_data(self, data):
        """Collect document text and the current cell contents."""
        self.text_parts.append(data)

        if self._inside_cell:
            self._cell_parts.append(data)

    def handle_endtag(self, tag):
        """Store a completed table cell."""
        if tag.lower() in {"td", "th"} and self._inside_cell:
            self.cell_values.append(
                "".join(self._cell_parts).strip()
            )

            self._inside_cell = False
            self._cell_parts = []


class InvalidDownloadError(RuntimeError):
    """Indicate that a downloaded response is not a usable data payload."""


# ---------------------------------------------------------------------------
# Cancellation helpers
# ---------------------------------------------------------------------------

def check_cancellation(
    is_cancelled: Optional[CancellationCallback] = None,
) -> None:
    """Raise OperationCancelled when cancellation is requested."""
    if is_cancelled is not None and is_cancelled():
        raise OperationCancelled(
            "The operation was cancelled."
        )


def wait_with_cancellation(
    seconds: float,
    is_cancelled: Optional[CancellationCallback] = None,
) -> None:
    """Wait while periodically checking for cancellation."""
    deadline = time.monotonic() + max(0.0, seconds)

    while True:
        check_cancellation(is_cancelled)
        remaining = deadline - time.monotonic()

        if remaining <= 0:
            return

        time.sleep(min(0.1, remaining))


# ---------------------------------------------------------------------------
# Standard-library HTTP transport
# ---------------------------------------------------------------------------

class StandardHttpTransport:
    """Retrieve HTTP resources without third-party dependencies.

    Parameters
    ----------
    timeout : float, default 60.0
        Timeout passed to the underlying network connection.
    max_retries : int, default 2
        Number of retries after the initial request.
    chunk_size : int, default 262144
        Number of bytes read during each response iteration.

    Notes
    -----
    Cancellation is checked between response reads. A blocking network
    call may still wait until its configured timeout.

    The timeout is not a maximum duration for the complete download.
    """

    RETRYABLE_STATUS_CODES = frozenset({
        429,
        500,
        502,
        503,
        504,
    })

    def __init__(
        self,
        timeout: float = 60.0,
        max_retries: int = 2,
        chunk_size: int = 256 * 1024,
    ) -> None:
        if timeout <= 0:
            raise ValueError(
                "The timeout must be greater than zero."
            )

        if max_retries < 0:
            raise ValueError(
                "The retry count cannot be negative."
            )

        if chunk_size <= 0:
            raise ValueError(
                "The chunk size must be greater than zero."
            )

        self.timeout = timeout
        self.max_retries = max_retries
        self.chunk_size = chunk_size

    def get_bytes(
        self,
        url: str,
        is_cancelled: Optional[CancellationCallback] = None,
    ) -> bytes:
        """Return the complete response body for an HTTP GET request.

        Parameters
        ----------
        url : str
            Absolute HTTP or HTTPS resource URL.
        is_cancelled : callable, optional
            Function returning True when cancellation is requested.

        Returns
        -------
        bytes
            Complete response body.

        Raises
        ------
        OperationCancelled
            If cancellation is requested.
        HTTPError
            If an HTTP error cannot be retried.
        URLError
            If network failures persist after all attempts.
        """
        if urlsplit(url).scheme not in {"http", "https"}:
            raise ValueError(
                "Only HTTP and HTTPS URLs are supported."
            )

        for attempt in range(self.max_retries + 1):
            check_cancellation(is_cancelled)

            request = Request(
                url,
                headers={
                    "User-Agent": "GVDA-GNSS/0.1",
                    "Accept-Encoding": "identity",
                },
            )

            try:
                with urlopen(
                    request,
                    timeout=self.timeout,
                ) as response:
                    chunks = []

                    while True:
                        check_cancellation(is_cancelled)

                        chunk = response.read(
                            self.chunk_size
                        )

                        if not chunk:
                            break

                        chunks.append(chunk)

                    check_cancellation(is_cancelled)
                    return b"".join(chunks)

            except HTTPError as error:
                should_retry = (
                    error.code in self.RETRYABLE_STATUS_CODES
                    and attempt < self.max_retries
                )

                # Release the response associated with the HTTP error.
                error.close()

                if not should_retry:
                    raise

            except (URLError, TimeoutError):
                if attempt >= self.max_retries:
                    raise

            retry_delay = min(2 ** attempt, 8)

            wait_with_cancellation(
                retry_delay,
                is_cancelled,
            )

        raise RuntimeError(
            "The HTTP retry loop ended unexpectedly."
        )


# ---------------------------------------------------------------------------
# HTML link extraction
# ---------------------------------------------------------------------------

class HtmlLinkParser(HTMLParser):
    """Collect href attributes from HTML anchor elements."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: List[str] = []

    def handle_starttag(
        self,
        tag,
        attrs,
    ) -> None:
        """Collect a link when an anchor element is encountered."""
        if tag.lower() != "a":
            return

        href = dict(attrs).get("href")

        if href:
            self.links.append(href)


def extract_http_links(
    content: bytes,
    page_url: str,
) -> List[str]:
    """Return unique absolute HTTP links from an HTML response.

    Parameters
    ----------
    content : bytes
        Raw HTML document.
    page_url : str
        Base URL used to resolve relative links.

    Returns
    -------
    list of str
        Sorted HTTP and HTTPS links.
    """
    parser = HtmlLinkParser()

    parser.feed(
        content.decode(
            "utf-8",
            errors="replace",
        )
    )
    parser.close()

    absolute_links = {
        urljoin(page_url, href)
        for href in parser.links
    }

    return sorted(
        link
        for link in absolute_links
        if urlsplit(link).scheme in {"http", "https"}
    )


# ---------------------------------------------------------------------------
# Provider catalogs
# ---------------------------------------------------------------------------

def fetch_ngl_catalog(transport, is_cancelled=None):
    """Retrieve station links and reject unrecognized catalog responses."""
    content = transport.get_bytes(
        NGL_CATALOG_URL,
        is_cancelled,
    )

    if not content.strip():
        raise CatalogParseError(
            "The catalog response is empty."
        )

    station_ids = set()

    links = extract_http_links(
        content,
        NGL_CATALOG_URL,
    )

    for link in links:
        check_cancellation(is_cancelled)

        match = re.search(
            r"/stations/([A-Za-z0-9_]{4})\.sta$",
            urlsplit(link).path,
        )

        if match is not None:
            station_ids.add(
                match.group(1).upper()
            )

    if not station_ids:
        structure = NglCatalogStructureParser()

        structure.feed(
            content.decode("utf-8", errors="replace")
        )
        structure.close()

        document_text = " ".join(
            structure.text_parts
        ).casefold()

        catalog_identity_found = (
            "station list" in document_text
            or "list of all gps stations" in document_text
        )

        has_nonempty_cells = any(
            structure.cell_values
        )

        # Accept an empty result only when a recognizable catalog
        # contains a table with no populated cells.
        if (
            catalog_identity_found
            and structure.table_count > 0
            and not has_nonempty_cells
        ):
            return {}

        raise CatalogParseError(
            "The catalog structure could not be recognized."
        )

    return {
        station_id: [
            f"{NGL_IGS20_BASE_URL}{station_id}.tenv3"
        ]
        for station_id in sorted(station_ids)
    }


def fetch_jpl_catalog(
    transport,
    is_cancelled: Optional[CancellationCallback] = None,
) -> StationCatalog:
    """List station series published in the selected JPL directory."""
    content = transport.get_bytes(
        JPL_SERIES_DIRECTORY_URL,
        is_cancelled,
    )

    catalog: StationCatalog = {}

    for link in extract_http_links(
        content,
        JPL_SERIES_DIRECTORY_URL,
    ):
        check_cancellation(is_cancelled)

        filename = Path(
            unquote(urlsplit(link).path)
        ).name

        match = JPL_FILENAME_PATTERN.fullmatch(filename)

        if match:
            station_id = match.group(1).upper()
            catalog.setdefault(station_id, []).append(link)

    if not catalog:
        raise CatalogError(
            "No station series files were found in the JPL directory."
        )

    return catalog


# ---------------------------------------------------------------------------
# Basic payload validation
# ---------------------------------------------------------------------------

def validate_payload(payload: bytes) -> None:
    """Reject empty responses and common HTML error documents.

    Notes
    -----
    This check does not validate the scientific content of a time series.
    Provider-specific validation must be applied after decoding.
    """
    if not payload:
        raise InvalidDownloadError(
            "The server returned an empty response."
        )

    prefix = payload[:512].lstrip().lower()

    if (
        prefix.startswith(b"<!doctype html")
        or prefix.startswith(b"<html")
    ):
        raise InvalidDownloadError(
            "The server returned HTML instead of a data file."
        )