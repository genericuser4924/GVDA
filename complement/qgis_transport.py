"""Provide HTTP access through the QGIS network infrastructure.

This module is intended for execution inside a configured QGIS
environment. Blocking requests must run in a background task rather
than directly in a GUI event handler.
"""

from __future__ import annotations

from typing import Optional

from qgis.core import (
    QgsBlockingNetworkRequest,
    QgsFeedback,
)
from qgis.PyQt.QtCore import QUrl
from qgis.PyQt.QtNetwork import QNetworkRequest

from .core import (
    CancellationCallback,
    OperationCancelled,
    check_cancellation,
)


class QgisHttpTransport:
    """Retrieve HTTP resources using the QGIS network infrastructure.

    Parameters
    ----------
    feedback : QgsFeedback, optional
        Feedback object used to cancel an active network request.

    Notes
    -----
    Each response is buffered in memory.

    This transport does not implement an additional application-level
    retry loop. Network failures are propagated to the calling task.
    """

    def __init__(
        self,
        feedback: Optional[QgsFeedback] = None,
    ) -> None:
        self.feedback = (
            feedback
            if feedback is not None
            else QgsFeedback()
        )

    def get_bytes(
        self,
        url: str,
        is_cancelled: Optional[CancellationCallback] = None,
    ) -> bytes:
        """Retrieve the complete response body for an HTTP GET request.

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
        ValueError
            If the resource URL is invalid or unsupported.
        OperationCancelled
            If cancellation is requested.
        RuntimeError
            If the network request fails.
        """
        self._check_cancellation(is_cancelled)

        resource_url = QUrl(url)

        if (
            not resource_url.isValid()
            or resource_url.scheme() not in {"http", "https"}
            or not resource_url.host()
        ):
            raise ValueError(
                f"Unsupported resource URL: {url}"
            )

        request = QNetworkRequest(resource_url)
        request.setRawHeader(
            b"User-Agent",
            b"GVDA-GNSS/0.1",
        )
        request.setRawHeader(
            b"Accept-Encoding",
            b"identity",
        )

        network_request = QgsBlockingNetworkRequest()

        # The caller runs this blocking operation inside a QgsTask.
        error_code = network_request.get(
            request,
            True,
            self.feedback,
        )

        self._check_cancellation(is_cancelled)

        if error_code != QgsBlockingNetworkRequest.NoError:
            raise RuntimeError(
                network_request.errorMessage()
                or f"QGIS network error: {error_code}"
            )

        return bytes(
            network_request.reply().content()
        )

    def _check_cancellation(
        self,
        is_cancelled: Optional[CancellationCallback],
    ) -> None:
        """Check both task cancellation and network feedback."""
        check_cancellation(is_cancelled)

        if self.feedback.isCanceled():
            raise OperationCancelled(
                "The operation was cancelled."
            )