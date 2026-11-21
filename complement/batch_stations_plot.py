from datetime import datetime

import numpy as np
import matplotlib.dates as mdates

from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QVBoxLayout,
    QSizePolicy,
    QScrollArea,
    QFrame,
)


def circular_intervals(mean, deviation):
    """Split a circular interval at the 0/360-degree boundary."""
    mean = float(mean) % 360.0
    deviation = float(deviation)

    if deviation >= 180.0:
        return ((0.0, 360.0),)

    low = mean - deviation
    high = mean + deviation

    if low < 0.0:
        return (
            (0.0, high),
            (low + 360.0, 360.0),
        )

    if high > 360.0:
        return (
            (low, 360.0),
            (0.0, high - 360.0),
        )

    return ((low, high),)


class BatchStationsPlot:
    """Maintain one canvas and two independent vertical scales."""

    def __init__(self, parent):
        parent.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Expanding,
        )
        parent.setMinimumHeight(180)

        layout = parent.layout()

        if layout is None:
            layout = QVBoxLayout(parent)

        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.figure = Figure(
            figsize=(7, 3),
            dpi=100,
            constrained_layout=True,
        )
        self.epochs = self.figure.add_subplot(111)
        self.angles = self.epochs.twinx()

        # Reserve horizontal space for each station and both axes.
        self.station_width = 60
        self.axes_width = 220

        self.scroll = QScrollArea(parent)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarAsNeeded
        )
        self.scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarAlwaysOff
        )
        self.scroll.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Expanding,
        )
        self.scroll.setMinimumSize(0, 0)

        self.canvas = FigureCanvasQTAgg(self.figure)
        self.canvas.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Expanding,
        )
        self.canvas.setMinimumSize(0, 0)

        self.scroll.setWidget(self.canvas)
        layout.addWidget(self.scroll)

        self._drawn_station_indices = set()
        self._pending_follow_x = None
        self.canvas.mpl_connect("draw_event", self._follow_drawn_station)

        self.draw((), ("#666666", "#222222", "#888888"))

    def _follow_drawn_station(self, event):
        """Reveal the newest rightmost station after layout."""
        x = self._pending_follow_x
        self._pending_follow_x = None

        if x is None or event.canvas is not self.canvas:
            return

        bar = self.scroll.horizontalScrollBar()
        if bar.maximum() <= bar.minimum():
            return

        figure_width = self.figure.bbox.width
        if figure_width <= 0:
            return

        # Convert Matplotlib display pixels to Qt widget coordinates.
        display_x = self.epochs.transData.transform((x, 0.0))[0]
        canvas_x = round(display_x * self.canvas.width() / figure_width)

        viewport_width = self.scroll.viewport().width()
        margin = 24
        target = canvas_x + margin - viewport_width

        if target > bar.value():
            bar.setValue(min(target, bar.maximum()))


    def draw(self, rows, colors):
        """Draw accepted batch values without calculating statistics."""
        epoch_color, mean_color, deviation_color = colors

        drawn_station_indices = {
            (index, row[0])
            for index, row in enumerate(rows)
            if row[1] is not None
        }
        newly_drawn = drawn_station_indices - self._drawn_station_indices
        self._drawn_station_indices = drawn_station_indices

        self._pending_follow_x = (
            max(index for index, _ in newly_drawn)
            if newly_drawn
            else None
        )

        # Grow only the scroll content, never the outer container.
        minimum_width = (
            int((len(rows) + 0.2) * self.station_width)
            + self.axes_width
            if rows
            else 0
        )

        self.canvas.setMinimumWidth(minimum_width)

        self.epochs.clear()
        self.angles.clear()

        visible = bool(rows)
        self.epochs.set_visible(visible)
        self.angles.set_visible(visible)

        if not visible:
            self.canvas.draw_idle()
            return

        # Keep angular symbols above the independent epoch axis.
        self.epochs.set_zorder(0)
        self.angles.set_zorder(1)
        self.angles.patch.set_visible(False)

        self.epochs.set_ylabel("Epoch", fontsize=9)
        self.angles.set_ylabel("Azimuth (°)", fontsize=9)
        self.epochs.set_xlabel("Station", fontsize=9)

        # Restore axis sides after clearing both axes.
        self.epochs.yaxis.set_label_position("left")
        self.epochs.yaxis.tick_left()

        self.angles.yaxis.set_label_position("right")
        self.angles.yaxis.tick_right()

        self.epochs.yaxis.labelpad = 8
        self.angles.yaxis.labelpad = 8

        self.angles.set_ylim(0.0, 360.0)
        self.angles.set_yticks((0, 90, 180, 270, 360))
        self.angles.set_yticklabels(
            ("0°", "90°", "180°", "270°", "360°")
        )
        self.angles.grid(
            axis="y",
            color="#dddddd",
            linewidth=0.6,
        )

        for axis in (self.epochs, self.angles):
            axis.tick_params(labelsize=8)

        positions = np.arange(len(rows))
        identifiers = [row[0] for row in rows]

        self.epochs.set_xlim(-0.6, len(rows) - 0.4)
        self.epochs.set_xticks(positions)

        # Rotate all station labels when at least one identifier is long.
        rotate_labels = any(len(str(identifier)) > 10 for identifier in identifiers)

        self.epochs.set_xticklabels(
            identifiers,
            rotation=45 if rotate_labels else 0,
            ha="right" if rotate_labels else "center",
            rotation_mode="anchor",
        )

        # Reserve vertical space for rotated labels and the plotting area.
        minimum_height = 280 if rotate_labels else 180
        self.scroll.parentWidget().setMinimumHeight(minimum_height)

        # Convert internal JD without assuming a UTC time scale.
        date_origin = mdates.date2num(
            datetime(2000, 1, 1, 12)
        )
        date_bounds = []

        for x, row in zip(positions, rows):
            station, first_jd, last_jd, mean, deviation = row

            if first_jd is None:
                self.angles.text(
                    x,
                    180.0,
                    "Pending",
                    rotation=90,
                    ha="center",
                    va="center",
                    fontsize=7,
                    color="#888888",
                )
                continue

            first = date_origin + first_jd - 2451545.0
            last = date_origin + last_jd - 2451545.0
            date_bounds.extend((first, last))

            self.epochs.vlines(
                x,
                first,
                last,
                colors=epoch_color,
                linewidth=1.0,
                zorder=100,
            )
            self.epochs.hlines(
                (first, last),
                x - 0.07,
                x + 0.07,
                colors=epoch_color,
                linewidth=1.0,
                zorder=100,
            )

            mean = mean % 360.0

            for low, high in circular_intervals(
                mean,
                deviation,
            ):
                rectangle = Rectangle(
                    (x - 0.20, low),
                    0.40,
                    high - low,
                    fill=False,
                    edgecolor=deviation_color,
                    linewidth=1.2,
                    zorder=101,
                )
                self.angles.add_patch(rectangle)

            self.angles.hlines(
                mean,
                x - 0.28,
                x + 0.28,
                colors=mean_color,
                linewidth=2.4,
                zorder=102,
            )

        if date_bounds:
            # Use the complete time extent of accepted batch results.
            low = min(date_bounds)
            high = max(date_bounds)
            middle = low + (high - low) / 2.0

            margin = max(
                (high - low) * 0.05,
                1.0 / 24.0,
            )

            ticks = np.unique(
                np.array(
                    (low, middle, high),
                    dtype=float,
                )
            )

            self.epochs.set_yticks(ticks)

            # Include time when the complete span is shorter than two days.
            date_format = (
                "%Y-%m-%d"
                if high - low >= 2.0
                else "%Y-%m-%d\n%H:%M"
            )

            self.epochs.yaxis.set_major_formatter(
                mdates.DateFormatter(date_format)
            )

            self.epochs.set_ylim(
                low - margin,
                high + margin,
            )

        else:
            self.epochs.set_yticks([])

        handles = (
            Line2D(
                [], [],
                color=epoch_color,
                linewidth=1.0,
                label="Epoch range",
            ),
            Rectangle(
                (0, 0), 1, 1,
                fill=False,
                edgecolor=deviation_color,
                linewidth=1.2,
                label="Mean ± circular SD",
            ),
            Line2D(
                [], [],
                color=mean_color,
                linewidth=2.4,
                label="Mean azimuth",
            ),
        )

        self.angles.legend(
            handles=handles,
            loc="upper center",
            bbox_to_anchor=(0.5, 1.22),
            ncol=3,
            frameon=False,
            fontsize=7,
        )

        self.canvas.draw_idle()