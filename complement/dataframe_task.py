"""Prepare station data frames without accessing GUI objects."""

from __future__ import annotations

import pandas as pd

from qgis.core import QgsTask


class StationDataFrameTask(QgsTask):
    """Convert a snapshot of one station document into a data frame."""

    def __init__(
        self,
        station_id,
        selection_token,
        source_lines,
        callback,
    ):
        super().__init__(
            f"Prepare station data: {station_id}",
            QgsTask.CanCancel,
        )

        self.station_id = station_id
        self.selection_token = selection_token

        # Copy the sequence before background execution.
        # Strings themselves are immutable.
        self.source_lines = tuple(source_lines)

        self.callback = callback
        self.result_data = None
        self.error_message = None

    def run(self):
        """Prepare one data frame without changing shared application data."""
        try:
            if self.isCanceled():
                return False

            if not self.source_lines:
                raise ValueError(
                    "The station document is empty."
                )

            column_names = self.source_lines[0].split()

            if not column_names:
                raise ValueError(
                    "The station header is empty."
                )

            expected_column_count = len(column_names)
            valid_rows = []
            rejected_row_count = 0

            for line in self.source_lines[1:]:
                if self.isCanceled():
                    return False

                fields = line.split()

                if len(fields) == expected_column_count:
                    valid_rows.append(fields)
                else:
                    rejected_row_count += 1

            if not valid_rows:
                raise ValueError(
                    "The station contains no valid data rows."
                )

            prepared_dataframe = pd.DataFrame(
                valid_rows,
                columns=[column_names],
            )

            if self.isCanceled():
                return False

            self.result_data = {
                "dataframe": prepared_dataframe,
                "column_names": column_names,
                "rejected_row_count": rejected_row_count,
            }

            return True

        except Exception as error:
            self.error_message = (
                f"{type(error).__name__}: {error}"
            )
            return False

    def finished(self, success):
        """Deliver the result through the main-thread callback."""
        if self.callback is not None:
            self.callback(self, success)