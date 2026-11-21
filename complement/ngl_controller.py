"""Coordinate NGL catalogs, station selection, and memory downloads."""

from __future__ import annotations

import logging
import uuid

from collections import deque

from qgis.core import (QgsApplication,QgsTask,QgsFeedback,)

from qgis.PyQt.QtWidgets import (QAbstractItemView,QTableWidgetItem,)

from .qgis_transport import QgisHttpTransport

from .ngl_memory import (NGL_PRODUCT_DESCRIPTION,fetch_ngl_document,fetch_ngl_station_records,)

from .jpl_memory import (fetch_jpl_document,fetch_jpl_station_records,)

from .epos_memory import fetch_epos_document, fetch_epos_station_records

from qgis.PyQt.QtGui import QBrush, QColor

from .core import (CatalogParseError, OperationCancelled, check_cancellation,)

from qgis.PyQt.QtCore import (QObject, Qt, pyqtSignal,)

from .dataframe_task import StationDataFrameTask

from pathlib import Path

LOGGER = logging.getLogger(__name__)


class NglRequestTask(QgsTask):
    """Run a provider request without accessing GUI widgets."""

    def __init__(
        self,
        operation,
        callback,
        station_record=None,
        provider=None,
        data_dir=None,
    ):
        record_provider = (station_record or {}).get("provider")
        provider = str(provider or record_provider or "NGL").strip().upper()

        super().__init__(
            f"{provider} {operation}",
            QgsTask.CanCancel,
        )

        self.operation = operation
        self.callback = callback
        self.station_record = station_record
        self.provider = provider
        self.data_dir = data_dir

        self.feedback = QgsFeedback()
        self.result_data = None
        self.error_message = None
        self.error_kind = None

    def cancel(self):
        """Cancel the task and its active network request."""
        super().cancel()
        self.feedback.cancel()

    def run(self):
        """Execute network and parsing work in the background."""
        try:
            check_cancellation(self.isCanceled)

            if self.provider not in {"NGL", "JPL", "EPOS"}:
                raise ValueError(
                    f"Unsupported provider: {self.provider}"
                )

            transport = QgisHttpTransport(self.feedback)

            if self.operation == "catalog":
                if self.provider == "NGL":
                    self.result_data = fetch_ngl_station_records(
                        transport,
                        self.isCanceled,
                    )

                elif self.provider == "EPOS":
                    # Load the live catalog with the task's cancellation callback.
                    self.result_data = fetch_epos_station_records(
                        transport,
                        self.isCanceled,
                    )


                else:
                    if self.data_dir is None:
                        raise ValueError(
                            "The JPL catalog requires the plugin data directory."
                        )

                    self.result_data = fetch_jpl_station_records(
                        transport,
                        self.data_dir,
                        self.isCanceled,
                    )

            elif self.operation == "document":
                if self.station_record is None:
                    raise ValueError(
                        "A station record is required."
                    )

                record_provider = str(
                    self.station_record.get("provider") or self.provider
                ).strip().upper()

                if record_provider != self.provider:
                    raise ValueError(
                        "The station record does not match the request provider."
                    )

                if self.provider == "NGL":
                    self.result_data = fetch_ngl_document(
                        transport,
                        self.station_record,
                        self.isCanceled,
                    )

                elif self.provider == "EPOS":
                    # Reuse the active task transport and cancellation callback.
                    self.result_data = fetch_epos_document(
                        transport,
                        self.station_record["station_id"],
                        self.isCanceled,
                    )

                else:
                    self.result_data = fetch_jpl_document(
                        transport,
                        self.station_record,
                        self.isCanceled,
                    )

            else:
                raise ValueError(
                    f"Unsupported operation: {self.operation}"
                )

            return not self.isCanceled()

        except OperationCancelled:
            return False

        except CatalogParseError as error:
            self.error_kind = "catalog_format"
            self.error_message = (
                f"{type(error).__name__}: {error}"
            )

            LOGGER.exception(
                "The %s catalog format was not recognized.",
                self.provider,
            )
            return False

        except Exception as error:
            self.error_kind = "request"
            self.error_message = (
                f"{type(error).__name__}: {error}"
            )

            LOGGER.exception(
                "%s request failed.",
                self.provider,
            )
            return False

    def finished(self, result):
        """Deliver results on the main thread."""
        if self.callback is not None:
            self.callback(self, result)


class NglController(QObject):
    """Manage available stations, selected stations, and memory documents.

    Parameters
    ----------
    service_combo : QComboBox
        Existing provider selector.
    available_table : QTableWidget
        Existing cors_av table.
    selected_table : QTableWidget
        Existing cors_se table.
    description_browser : QTextBrowser
        Existing browser used for the requested product description.

    Notes
    -----
    Selection does not imply download success. Only validated downloads
    are added to documents.

    Downloads are queued and processed one at a time.
    """

    dataframes_changed = pyqtSignal()
    dataframe_rejected = pyqtSignal(str)

    def __init__(
        self,
        service_combo,
        available_table,
        selected_table,
        description_browser,
        parent=None,
        available_count_label=None,
        progress_bar=None,
        next_button=None,
    ):
        super().__init__(parent)

        self.service_combo = service_combo
        self.available_table = available_table
        self.selected_table = selected_table
        self.description_browser = description_browser

        # Keep a reference to the existing label owned by the dialog.
        self.available_count_label = available_count_label
        self.progress_bar = progress_bar

        self.stations = {}
        self.documents = {}
        self.errors = {}
        self.metadata_error = None
        self.catalog_error = None

        self._selection_tokens = {}
        self._queue = deque()
        self._catalog_task = None
        self._download_task = None
        self._closed = False

        self.dataframes = {}
        self.dataframe_errors = {}

        self._dataframe_task = None
        self._dataframe_processing_enabled = False

        self._configure_table(self.available_table, available=True)
        self._configure_table(self.selected_table)

        self.available_table.cellClicked.connect(
            self._select_station
        )
        self.selected_table.cellClicked.connect(
            self._remove_station
        )

        self.next_button = next_button
        if self.next_button is not None:
            self.next_button.setEnabled(False)

    def _update_next_button(self):
        """Update navigation readiness and notify document-state changes."""
        has_ready_document = any(
            station_id in self.documents
            and station_id not in self.errors
            for station_id in self._selection_tokens
        )

        if self.next_button is not None:
            self.next_button.setEnabled(
                has_ready_document
            )

        self.dataframes_changed.emit()

    @staticmethod
    def _configure_table(table, available=False):
        """Configure separate available and selected station views."""
        headers = ["Station ID", "Site", "Region", "Country"] if available else ["Station ID", "Site"]
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setColumnHidden(1, available)

        if available:
            table.setColumnHidden(2, False)
            table.setColumnHidden(3, False)

        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setSortingEnabled(False)
        table.setRowCount(0)

    def load_service(self, service_name):
        """Start a provider catalog query after clearing the previous session."""
        if self._closed:
            return

        self.reset_session()
        provider = str(service_name).strip().upper()

        if provider not in {"NGL", "JPL", "EPOS"}:
            return

        task = NglRequestTask(
            operation="catalog",
            callback=self._catalog_finished,
            provider=provider,
            data_dir=(
                Path(__file__).resolve().parent.parent / "data"
                if provider == "JPL" else None
            ),
        )

        self._catalog_task = task
        self._start_progress()
        QgsApplication.taskManager().addTask(task)

    def _start_progress(self):
        """Display activity when the operation size is not known."""
        if self.progress_bar is not None:
            self.progress_bar.setRange(0, 0)

    def _finish_progress(self, success):
        """Restore percentage mode after the current operation finishes."""
        if self.progress_bar is not None:
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(
                100 if success else 0
            )   

    def _catalog_finished(self, task, success):
        """Display the catalog outcome without clearing selected data."""
        if self._closed or task is not self._catalog_task:
            return

        self._catalog_task = None

        if not success:
            self.catalog_error = task.error_message

            if not task.isCanceled():
                message = (
                    "Unrecognized catalog format"
                    if task.error_kind == "catalog_format"
                    else "Query failed"
                )

                self.description_browser.setPlainText(
                    message
                )

            self._finish_progress(False)
            return

        self.stations, self.metadata_error = task.result_data

        if task.provider == "EPOS":
            for station_id in ("REYK00ISL", "HOS000SWE"):
                record = self.stations.get(station_id, {})


        if task.provider == "EPOS":
            named_count = sum(
                bool(str(record.get("site") or "").strip())
                for record in self.stations.values()
            )


        available_station_count = len(self.stations)

        if available_station_count == 0:
            self.description_browser.setPlainText(
                "Empty catalog"
            )

            # The query finished successfully, but returned no stations.
            self._finish_progress(True)
            return

        if self.available_count_label is not None:
            self.available_count_label.setText(
                f"CORS stations available: "
                f"<b>{available_station_count}</b>"
            )

        self.description_browser.setPlainText(
            NGL_PRODUCT_DESCRIPTION
            if task.provider == "NGL"
            else (
                "JPL station time series.\n"
                "The reference frame is IGS14.\n"
                "The reference epoch is January 1, 2026.\n"
                "The reference ellipsoid is GRS80."
            )
        )

        if task.provider == "EPOS":
            self.description_browser.setPlainText(
                "EPOS / UGA-CNRS: daily position time series (IGS20).\n"
            )

        station_ids = sorted(self.stations)

        self.available_table.setUpdatesEnabled(False)

        try:
            self.available_table.setRowCount(
                len(station_ids)
            )

            for row_index, station_id in enumerate(station_ids):
                self._set_station_row(
                    self.available_table,
                    row_index,
                    station_id,
                )
            if task.provider == "EPOS":
                # Show the site names already supplied by the EPOS catalog.
                self.available_table.setColumnHidden(1, False)

        finally:
            self.available_table.setUpdatesEnabled(True)

        self._finish_progress(True)


    def _select_station(self, row_index, column_index):
        """Select a station and enqueue one download attempt."""
        # Archive selection is integrated separately from remote downloads.
        # Route archive members without creating remote download requests.
        if (
            self.service_combo.currentText().strip().casefold()
            == "compressed file"
        ):
            item = self.available_table.item(row_index, 0)
            dialog = self.parent()

            if item is not None and dialog is not None:
                dialog._select_archive_station(
                    item.data(Qt.UserRole)
                )
            return

        item = self.available_table.item(row_index, 0)

        if item is None:
            return

        station_id = item.data(Qt.UserRole)

        if station_id in self._selection_tokens:
            return

        token = uuid.uuid4().hex
        self._selection_tokens[station_id] = token

        self.errors.pop(station_id, None)

        self._queue.append((station_id, token))


        self._render_selected()

        self._update_next_button()

        self._start_next_download()


    
    def _set_station_row(self, table, row_index, station_id):
        """Populate station rows without mixing provider metadata."""
        record = self.stations[station_id]
        provider = str(record.get("provider") or "NGL").strip().upper()
        site_text = str(record.get("site") or "")

        if table is self.selected_table and provider == "NGL":
            reference = getattr(self.parent(), "_ngl_site_index", None)

            if reference is not None:
                attributes = reference.get(str(station_id).strip().upper())
                site_text = str((attributes or {}).get("SITE") or "")

        values = [station_id, site_text]

        if table is self.available_table:
            local = (
                (record.get("local_metadata") or {})
                if provider in {"JPL", "EPOS"}
                else {}
            )
            values.extend([
                local.get("region", ""),
                local.get("country", ""),
            ])

        failed = table is self.selected_table and station_id in self.errors

        for column, value in enumerate(values):
            item = QTableWidgetItem(str(value))
            item.setData(Qt.UserRole, station_id)

            if failed:
                item.setForeground(QBrush(QColor("red")))

            table.setItem(row_index, column, item)


    def _mark_station_failed(self, station_id):
        """Color an existing selected station row without changing others."""
        error_brush = QBrush(QColor("red"))

        for row_index in range(self.selected_table.rowCount()):
            id_item = self.selected_table.item(row_index, 0)

            if (
                id_item is None
                or id_item.data(Qt.UserRole) != station_id
            ):
                continue

            for column_index in range(
                self.selected_table.columnCount()
            ):
                item = self.selected_table.item(
                    row_index,
                    column_index,
                )

                if item is not None:
                    item.setForeground(error_brush)

            return

    def _render_selected(self):
        """Refresh selected stations in alphabetical order."""
        station_ids = sorted(self._selection_tokens)

        self.selected_table.setRowCount(
            len(station_ids)
        )

        for row_index, station_id in enumerate(station_ids):
            self._set_station_row(
                self.selected_table,
                row_index,
                station_id,
            )


    def _remove_station(self, row_index, column_index):
        """Remove a selected station and discard its associated data."""
        # Keep archive removal independent of remote document caches.
        if (
            self.service_combo.currentText().strip().casefold()
            == "compressed file"
        ):
            item = self.selected_table.item(row_index, 0)
            dialog = self.parent()

            if item is not None and dialog is not None:
                dialog._remove_archive_station(
                    item.data(Qt.UserRole)
                )
            return
        
        item = self.selected_table.item(row_index, 0)

        if item is None:
            return

        # Resolve the identifier before using it in any dictionary.
        station_id = item.data(Qt.UserRole)

        if station_id is None:
            return

        # Invalidate the selection so late task results are ignored.
        self._selection_tokens.pop(station_id, None)

        # Remove original data, prepared data, and station-specific errors.
        self.documents.pop(station_id, None)
        self.dataframes.pop(station_id, None)
        self.errors.pop(station_id, None)
        self.dataframe_errors.pop(station_id, None)

        # Remove pending downloads for this station.
        self._queue = deque(
            (queued_id, token)
            for queued_id, token in self._queue
            if queued_id != station_id
        )

        # Request cancellation if this station is currently downloading.
        if (
            self._download_task is not None
            and self._download_task.station_record["station_id"]
            == station_id
        ):
            self._download_task.cancel()

        # Request cancellation if its data frame is being prepared.
        if (
            self._dataframe_task is not None
            and self._dataframe_task.station_id == station_id
        ):
            self._dataframe_task.cancel()

        self._render_selected()
        self._update_next_button()


    def _start_next_download(self):
        """Start the next valid selection without retrying failed stations."""
        if self._closed or self._download_task is not None:
            return

        while self._queue:
            station_id, token = self._queue.popleft()

            if self._selection_tokens.get(station_id) != token:
                continue

            task = NglRequestTask(
                operation="document",
                station_record=dict(self.stations[station_id]),
                callback=lambda completed_task, success,
                current_id=station_id,
                current_token=token: self._document_finished(
                    completed_task,
                    success,
                    current_id,
                    current_token,
                ),
            )

            self._download_task = task
            self._start_progress()

            QgsApplication.taskManager().addTask(task)
            return


    def _document_finished(
        self,
        task,
        success,
        station_id,
        token,
    ):
        """Store valid documents or mark failures, then update readiness."""
        if self._closed or task is not self._download_task:
            return

        self._download_task = None

        selection_is_current = (
            self._selection_tokens.get(station_id) == token
        )

        if selection_is_current:
            if success:
                self.documents[station_id] = task.result_data
                self.errors.pop(station_id, None)

            elif not task.isCanceled():
                self.errors[station_id] = (
                    task.error_message
                    or "Download failed"
                )

                self._mark_station_failed(station_id)

        self._update_next_button()

        self._finish_progress(
            success and not task.isCanceled()
        )

        self._start_next_download()
        self._start_next_dataframe()


    def _cancel_tasks(self):
        """Detach callbacks before cancelling outstanding requests."""
        for task in (
            self._catalog_task,
            self._download_task,
        ):
            if task is not None:
                task.callback = None
                task.cancel()

        self._catalog_task = None
        self._download_task = None

        self._finish_progress(False)

    def close(self):
        """Release callbacks and cancel work before plugin unloading."""
        self._closed = True
        self._reset_dataframe_cache()
        self._cancel_tasks()
        self._queue.clear()

    def get_document(self, station_id):
        """Return a downloaded document or None while unavailable."""
        return self.documents.get(
            station_id.strip().upper()
        )

    def get_selected_station_coordinates(self):
        """Return catalog coordinates for the current station selection."""
        selected_coordinates = {}

        for station_id in self._selection_tokens:
            record = self.stations.get(
                station_id,
                {},
            )

            selected_coordinates[
                station_id
            ] = {
                "LAT": record.get(
                    "latitude"
                ),
                "LONG": record.get(
                    "longitude"
                ),
            }

        return selected_coordinates

    def discard_station_document(self, station_id):
        """Remove an unusable document and its station selection.

        Other selected stations and downloaded documents are preserved.
        """
        self.dataframes.pop(station_id, None)

        self.documents.pop(station_id, None)
        self.errors.pop(station_id, None)
        self._selection_tokens.pop(station_id, None)

        # Remove pending entries for the discarded selection.
        self._queue = deque(
            (queued_id, token)
            for queued_id, token in self._queue
            if queued_id != station_id
        )

        if (
            self._download_task is not None
            and self._download_task.station_record["station_id"]
            == station_id
        ):
            self._download_task.cancel()

        self._render_selected()
        self._update_next_button()

    def clear_station_selection(self):
        """Clear selected stations while preserving the available catalog.

        Active document requests are detached and cancelled so that late
        responses cannot repopulate the cleared selection.
        """
        self._reset_dataframe_cache()

        if self._download_task is not None:
            self._download_task.callback = None
            self._download_task.cancel()
            self._download_task = None

        self._queue.clear()
        self._selection_tokens.clear()

        self.documents.clear()
        self.errors.clear()

        self.selected_table.setRowCount(0)

        self._update_next_button()
        self._finish_progress(False)

    def start_dataframe_processing(self):
        """Prepare remaining documents after the first active dataset."""
        self._dataframe_processing_enabled = True
        self._start_next_dataframe()

    def _start_next_dataframe(self):
        """Start one unprepared document without duplicating cached data."""
        if (
            self._closed
            or not self._dataframe_processing_enabled
            or self._dataframe_task is not None
        ):
            return

        for station_id, document in self.documents.items():
            if (
                station_id in self.dataframes
                or station_id not in self._selection_tokens
            ):
                continue

            task = StationDataFrameTask(
                station_id=station_id,
                selection_token=self._selection_tokens[station_id],
                source_lines=document.get("lines", []),
                callback=self._dataframe_finished,
            )

            self._dataframe_task = task
            self.dataframes_changed.emit()

            QgsApplication.taskManager().addTask(task)
            return

        self.dataframes_changed.emit()

    def _dataframe_finished(self, task, success):
        """Store current results or discard an unusable station."""
        if self._closed or task is not self._dataframe_task:
            return

        self._dataframe_task = None

        station_id = task.station_id

        selection_is_current = (
            self._selection_tokens.get(station_id)
            == task.selection_token
            and station_id in self.documents
        )

        if selection_is_current:
            if success:
                self.dataframes[station_id] = task.result_data

            elif not task.isCanceled():
                self.dataframe_errors[station_id] = (
                    task.error_message
                    or "Data frame preparation failed"
                )

                self.discard_station_document(station_id)
                self.dataframe_rejected.emit(station_id)

        self.dataframes_changed.emit()
        self._start_next_dataframe()

    def dataframe_processing_pending(self):
        """Return whether downloads or data frame preparation remain."""
        return (
            self._download_task is not None
            or bool(self._queue)
            or self._dataframe_task is not None
            or any(
                station_id not in self.dataframes
                for station_id in self.documents
                if station_id in self._selection_tokens
            )
        )

    def _reset_dataframe_cache(self):
        """Cancel preparation and remove all cached station data frames."""
        if self._dataframe_task is not None:
            self._dataframe_task.callback = None
            self._dataframe_task.cancel()
            self._dataframe_task = None

        self._dataframe_processing_enabled = False

        self.dataframes.clear()
        self.dataframe_errors.clear()

    def reset_session(self):
        """Cancel pending work and discard the current service session.

        The controller and its signal connections remain available
        for subsequent queries.
        """
        self._reset_dataframe_cache()
        self._cancel_tasks()

        self.stations.clear()
        self.documents.clear()
        self.errors.clear()
        self.dataframe_errors.clear()

        self._selection_tokens.clear()
        self._queue.clear()

        self.catalog_error = None
        self.metadata_error = None

        self.available_table.setRowCount(0)
        self.selected_table.setRowCount(0)

        if self.available_count_label is not None:
            self.available_count_label.setText(
                "CORS Station avaible:"
            )

        self.description_browser.clear()

        self._update_next_button()
        self._finish_progress(False)