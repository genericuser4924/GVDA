"""Prepare aligned time series and fit their native Qt presentation."""

import math
from statistics import median

from qgis.PyQt.QtCore import QRectF
from .plot_presentation import PlotAutoFit


def prepare_time_series(epochs, azimuths, distances):
    """Align existing N-1 observations with epochs 1 through N-1."""
    epochs = tuple(float(value) for value in epochs)
    azimuths = tuple(float(value) for value in azimuths)
    distances = tuple(float(value) for value in distances)

    if not azimuths:
        raise ValueError("No distance/azimuth observations are available.")
    if len(azimuths) != len(distances) or len(epochs) != len(azimuths) + 1:
        raise ValueError("Epoch, azimuth, and distance series are not row-aligned.")
    if not all(math.isfinite(value) for values in (epochs, azimuths, distances) for value in values):
        raise ValueError("Time series require finite numeric values.")
    intervals = tuple(second - first for first, second in zip(epochs, epochs[1:]))
    if any(value <= 0 for value in intervals):
        raise ValueError("Epochs must be strictly increasing.")
    if any(value < 0 or value > 360 for value in azimuths):
        raise ValueError("Azimuths must lie between 0 and 360 degrees.")
    if any(value < 0 for value in distances):
        raise ValueError("Distances cannot be negative.")

    times = epochs[1:]
    gap_limit = 1.5 * median(intervals)
    distance_breaks = tuple(index == 0 or times[index] - times[index - 1] > gap_limit for index in range(len(times)))
    azimuth_breaks = tuple(distance_breaks[index] or abs(azimuths[index] - azimuths[index - 1]) > 180 for index in range(len(times)))
    maximum = max(distances)

    return {
        "times": times,
        "azimuths": azimuths,
        "distances": distances,
        "start": epochs[0],
        "end": epochs[-1],
        "distance_scale_max": maximum if maximum > 0 else 1.0,
        "distance_breaks": distance_breaks,
        "azimuth_breaks": azimuth_breaks,
    }


class TimeSeriesAutoFit(PlotAutoFit):
    """Fit cached geometry with screen-space margins and collision-free date labels."""

    def __init__(self, view):
        super().__init__(view)
        self._plot_rect = None
        self._date_labels = []

    def clear(self):
        self._timer.stop()
        self._bounds = None
        self._labels = []
        self._date_labels = []
        self._plot_rect = None

    def refresh(self, plot_rect, labels, date_labels):
        self._plot_rect = QRectF(plot_rect)
        self._date_labels = list(date_labels)
        super().refresh(plot_rect, labels)

    def eventFilter(self, watched, event):
        if getattr(self.view, "_active_plot", None) != "azimuth_distance_time_series":
            return False
        return super().eventFilter(watched, event)

    def fit(self):
        if getattr(self.view, "_active_plot", None) != "azimuth_distance_time_series":
            return
        if self._plot_rect is None or self._busy:
            return

        viewport = self.view.viewport()
        left, top, right, bottom = 110.0, 55.0, 140.0, 125.0
        scale = min(
            max(40.0, viewport.width() - left - right - 4.0) / self._plot_rect.width(),
            max(40.0, viewport.height() - top - bottom - 4.0) / self._plot_rect.height(),
        )
        self._bounds = self._plot_rect.adjusted(
            -left / scale,
            -top / scale,
            right / scale,
            bottom / scale,
        )

        # Publish the complete bounds, including axis and legend margins.
        scene = self.view.scene()
        if scene is None:
            return

        scene.setSceneRect(self._bounds)
        self.view.setSceneRect(self._bounds)

        super().fit()

        transform = self.view.viewportTransform()
        accepted = []
        count = len(self._date_labels)
        priority = list(dict.fromkeys([0, count - 1, count // 2] + list(range(count)))) if count else []

        for index in priority:
            item = self._date_labels[index]
            try:
                bounds = item.deviceTransform(transform).mapRect(item.boundingRect()).adjusted(-6, 0, 6, 0)
                visible = not any(bounds.intersects(other) for other in accepted)
                item.setVisible(visible)
                if visible:
                    accepted.append(bounds)
            except RuntimeError:
                continue
