# -*- coding: utf-8 -*-

import os
from html import escape

from qgis.PyQt import uic
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QDialog,
    QListWidgetItem,
    QVBoxLayout,
)


class PositionDialog(QDialog):
    """Collect a position association without publishing map layers."""

    def __init__(
        self,
        parent,
        station_name,
        frame,
        column_names,
        catalog_rows,
        resolve_column,
        normalize_position,
    ):
        super().__init__(parent)

        self.setWindowTitle(f"Position association — {station_name}")

        self._frame = frame
        self._resolve_column = resolve_column
        self._normalize_position = normalize_position
        self._draft = None

        ui_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "dialog_position.ui",
        )
        self.panel = uic.loadUi(ui_path)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(self.panel)

        panel = self.panel
        panel.lb_adv.setWordWrap(True)

        for selector in (panel.lat, panel.longi):
            selector.clear()
            selector.addItem("")
            selector.addItems([str(name) for name in column_names])
            selector.setCurrentIndex(0)
            selector.setEnabled(True)

        panel.listWidget.clear()

        for row in catalog_rows:
            if not row:
                continue

            item = QListWidgetItem(" ".join(row))
            item.setData(Qt.UserRole, tuple(row))
            panel.listWidget.addItem(item)

        panel.listWidget.clearSelection()
        panel.listWidget.setCurrentRow(-1)

        panel.bt_accept.setEnabled(False)
        panel.bt_cancel.setEnabled(True)

        panel.lat.currentTextChanged.connect(self._evaluate)
        panel.longi.currentTextChanged.connect(self._evaluate)
        panel.tabWidget.currentChanged.connect(self._evaluate)
        panel.listWidget.itemSelectionChanged.connect(self._evaluate)
        panel.lineEdit.textChanged.connect(self._filter_catalog)

        panel.bt_accept.clicked.connect(self._accept_position)
        panel.bt_cancel.clicked.connect(self.reject)

        self._evaluate()

    @property
    def association(self):
        """Return the validated draft accepted by the user."""
        return self._draft

    def _message(self, text, valid=False):
        """Show English feedback for the active position mode."""
        color = "#297500" if valid else "#FF0000"
        self.panel.lb_adv.setText(
            f"<font color='{color}'>{escape(text)}</font>"
        )
        self.panel.bt_accept.setEnabled(valid)

    def _filter_catalog(self, text):
        """Filter reference stations without relying on visible row numbers."""
        needle = text.casefold()

        for index in range(self.panel.listWidget.count()):
            item = self.panel.listWidget.item(index)
            item.setHidden(needle not in item.text().casefold())

        self._evaluate()

    def _evaluate(self, *args):
        """Validate only the currently displayed tab."""
        self._draft = None
        self.panel.bt_accept.setEnabled(False)

        if self.panel.tabWidget.currentIndex() == 0:
            self._evaluate_columns()
        else:
            self._evaluate_reference()

    def _evaluate_columns(self):
        """Validate coordinate columns while retaining original row indices."""
        latitude = self.panel.lat.currentText()
        longitude = self.panel.longi.currentText()

        if not latitude or not longitude:
            self._message(
                "Select the latitude and longitude columns."
            )
            return

        if latitude == longitude:
            self._message(
                "Latitude and longitude must use different columns."
            )
            return

        try:
            lat_index = self._resolve_column(self._frame, latitude)
            lon_index = self._resolve_column(self._frame, longitude)

            latitudes = self._frame.iloc[:, lat_index].tolist()
            longitudes = self._frame.iloc[:, lon_index].tolist()

            valid_rows = tuple(
                index
                for index, (lat, lon) in enumerate(
                    zip(latitudes, longitudes)
                )
                if self._normalize_position(lat, lon) is not None
            )
        except (ValueError, TypeError, IndexError, OverflowError) as error:
            self._message(str(error))
            return

        if not valid_rows:
            self._message(
                "No valid WGS84 positions were found "
                "in the selected columns."
            )
            return

        skipped = len(self._frame) - len(valid_rows)

        self._draft = {
            "mode": "observations",
            "mapping": (latitude, longitude),
            "position": None,
            "valid_rows": valid_rows,
            "skipped_count": skipped,
            "reference": None,
        }

        self._message(
            f"{len(valid_rows)} valid positions; "
            f"{skipped} rows will be excluded. "
            "Click Accept to associate these columns with this station.",
            valid=True,
        )

    def _evaluate_reference(self):
        """Validate the selected catalog reference position."""
        items = self.panel.listWidget.selectedItems()

        if len(items) != 1 or items[0].isHidden():
            self._message(
                "Select a reference station from the list."
            )
            return

        row = items[0].data(Qt.UserRole)

        if row is None or len(row) < 9:
            self._message(
                "The selected catalog entry is incomplete."
            )
            return

        position = self._normalize_position(row[6], row[7])

        if position is None:
            self._message(
                "The selected reference station "
                "does not have a valid WGS84 position."
            )
            return

        self._draft = {
            "mode": "reference",
            "mapping": None,
            "position": position,
            "valid_rows": (),
            "skipped_count": 0,
            "reference": tuple(row),
        }

        self._message(
            "Valid reference position. Click Accept "
            "to associate it with this station.",
            valid=True,
        )

    def _accept_position(self):
        """Recheck the active draft before accepting the dialog."""
        self._evaluate()

        if self._draft is not None:
            self.accept()