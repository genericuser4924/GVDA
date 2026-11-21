"""Render native Qt circle plots without statistical calculations."""

from qgis.PyQt import sip

from qgis.PyQt.QtCore import (
    QObject,
    QEvent,
    QPointF,
    QRectF,
    QTimer,
    Qt,
)

from qgis.PyQt.QtGui import (
    QBrush,
    QColor,
    QPainterPath,
    QPen,
)

from math import cos, sin

from qgis.PyQt.QtWidgets import (QGraphicsPathItem,QGraphicsLineItem,QGraphicsPathItem,)
from .plot_presentation import (uniform_plot_fonts,position_north_label,)
from .plot_presentation import uniform_plot_fonts, position_north_label, position_screen_label


class CircleSceneRenderer(QObject):
    """Manage batched geometry, overlays, and view-only resizing.

    The scene and view are owned by the dialog. This object does not
    calculate statistics or modify the observation arrays.
    """

    def __init__(self, view, scene):
        super().__init__(view)

        self._screen_labels = []

        self.view = view
        self.scene = scene

        self.mean_item = None
        self.deviation_item = None

        self._paths = {}
        self._items = {}
        self._base_rect = None

        self._fit_rect = None
        self._fitting = False

        self.view.setAlignment(Qt.AlignCenter)

        if self.view.scene() is not self.scene:
            self.view.setScene(self.scene)

        # Automatic fitting does not require scene scrollbars.
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self._fit_timer = QTimer(self)
        self._fit_timer.setSingleShot(True)

        self._fit_timer.timeout.connect(self.fit_to_view)

        self.view.viewport().installEventFilter(self)
        self._north_label = None


    def eventFilter(self, watched, event):
        """Fit the plot only after viewport size or visibility changes."""
        if watched is self.view.viewport():
            if event.type() in (
                QEvent.Resize,
                QEvent.Show,
            ):
                if not self._fitting:
                    self._fit_timer.start(0)

        return super().eventFilter(watched,event,)
    
    def set_north_label(self, item, center, radius):
        self._north_label = (item,QPointF(center),float(radius),)

    def begin(self, point_color, line_color):
        """Start a new plot and create only three observation items."""
        self.mean_item = None
        self.deviation_item = None

        self._items = {}
        self._paths = {}

        self._fit_timer.stop()
        self._fit_rect = None

        self._screen_labels = []
        self.scene.clear()
        self._north_label = None

        for name in (
            "unit_points",
            "distance_lines",
            "density_points",
        ):
            path = QPainterPath()

            # Overlapping closed subpaths must not create empty holes.
            path.setFillRule(
                Qt.WindingFill
            )

            item = QGraphicsPathItem()

            color = (
                line_color
                if name == "distance_lines"
                else point_color
            )

            pen = QPen(color)
            pen.setWidth(2)
            pen.setCapStyle(Qt.FlatCap)

            item.setPen(pen)

            if name == "distance_lines":
                item.setBrush(
                    QBrush(Qt.NoBrush)
                )

                item.setZValue(0)

            else:
                item.setBrush(
                    QBrush(point_color)
                )

                item.setZValue(1)

            self.scene.addItem(item)

            self._paths[name] = path
            self._items[name] = item

    def geometry(self):
        """Use a compact square scene independent of viewport proportions."""
        if self._base_rect is None:
            viewport = self.view.viewport()

            side = min(viewport.width(),viewport.height(),)

            if side <= 60:
                side = 640

            self._base_rect = QRectF(0.0,0.0,float(side),float(side),)

        rect = QRectF(self._base_rect)

        center = QPointF(rect.center())

        radius = (rect.width() / 2.0) - 30.0

        self.scene.setSceneRect(rect)

        self.view.setSceneRect(rect)

        return rect, center, radius

    def add_point(self, layer, x, y, diameter):
        """Append an ellipse without creating another scene item."""
        self._paths[layer].addEllipse(
            x,
            y,
            diameter,
            diameter,
        )

    def add_line(self, x1, y1, x2, y2):
        """Append an independent segment to the line layer."""
        path = self._paths[
            "distance_lines"
        ]

        path.moveTo(
            x1,
            y1,
        )

        path.lineTo(
            x2,
            y2,
        )

    def finish(self):
        """Publish geometry and cache the actual drawing bounds once."""
        for name, path in self._paths.items():
            self._items[name].setPath(
                path
            )

        uniform_plot_fonts(self.scene)

        bounds = self.scene.itemsBoundingRect()

        if bounds.isEmpty():
            self._fit_rect = None
            return

        # Include labels and pen edges without retaining unused viewport space.
        margin = 12.0

        self._fit_rect = bounds.adjusted(
            -margin,
            -margin,
            margin,
            margin,
        )

        self.scene.setSceneRect(
            self._fit_rect
        )

        self.view.setSceneRect(
            self._fit_rect
        )

        self.fit_to_view()

        # Repeat after pending layout changes have been processed.
        self._fit_timer.start(0)

    def fit_to_view(self):
        """Scale the existing plot without changing widget geometry."""
        if getattr(
            self.view,
            "_active_plot",
            None,
        ) == "qq":
            return
        
        if self._fitting:
            return

        if self._fit_rect is None:
            return

        viewport = self.view.viewport()

        if (
            viewport.width() <= 2
            or viewport.height() <= 2
        ):
            return

        rect = QRectF(
            self._fit_rect
        )

        if rect.isEmpty():
            return

        self._fitting = True

        try:
            self.view.resetTransform()

            self.view.fitInView(rect,Qt.KeepAspectRatio,)

            self.view.centerOn(rect.center())

            if self._north_label is not None:
                item, center, radius = self._north_label

                position_north_label(self.view,item,center,radius,)

            for item, anchor, alignment, gap in self._screen_labels:
                position_screen_label(self.view, item, anchor, alignment, gap)

        finally:
            self._fitting = False

    def update_overlays(
        self,
        show_mean,
        show_deviation,
        mean_color,
        deviation_color,
        deviation_opacity,
    ):
        """Update overlay visibility and style without recalculation."""
        if (
            self.mean_item is not None
            and not sip.isdeleted(self.mean_item)
        ):
            pen = QPen(mean_color)
            pen.setWidth(2)
            pen.setCapStyle(Qt.FlatCap)

            self.mean_item.setPen(pen)

            self.mean_item.setVisible(
                show_mean
            )

        if (
            self.deviation_item is not None
            and not sip.isdeleted(self.deviation_item)
        ):
            color = QColor(
                deviation_color
            )

            self.deviation_item.setPen(
                QPen(color)
            )

            color.setAlphaF(
                max(
                    0.0,
                    min(
                        1.0,
                        deviation_opacity,
                    ),
                )
            )

            self.deviation_item.setBrush(
                QBrush(color)
            )

            self.deviation_item.setVisible(
                show_deviation
            )

        self.scene.update()

    def clear(self):
        """Remove plot data and restore the empty rendering state."""
        self._fit_timer.stop()

        self.mean_item = None
        self.deviation_item = None

        self._items = {}
        self._paths = {}
        self._base_rect = None
        self._fit_rect = None

        self._screen_labels = []
        self.scene.clear()
        self.scene.setSceneRect(QRectF())

        self.view.setSceneRect(QRectF())
        self.view.resetTransform()
        self.view.viewport().update()
        self._north_label = None

    def add_rings(
        self,
        center,
        outer_radius,
        count,
        color,
    ):
        """Draw all reference rings as one unfilled scene item."""
        count = int(count)

        if count < 1:
            raise ValueError(
                "The ring count must be at least one"
            )

        path = QPainterPath()

        step = outer_radius / count

        for index in range(1, count + 1):
            ring_radius = step * index

            path.addEllipse(
                center.x() - ring_radius,
                center.y() - ring_radius,
                ring_radius * 2,
                ring_radius * 2,
            )

        item = QGraphicsPathItem(path)

        item.setPen(
            QPen(color)
        )

        # Rings must not fill or obscure the observation layers.
        item.setBrush(
            QBrush(Qt.NoBrush)
        )

        item.setZValue(1)

        self.scene.addItem(item)

        return item

    def add_density_axes(
        self,
        center,
        radius,
        color,
    ):
        """Draw both density reference axes as one scene item."""
        path = QPainterPath()

        # Horizontal axis.
        path.moveTo(
            center.x() - radius,
            center.y(),
        )

        path.lineTo(
            center.x() + radius,
            center.y(),
        )

        # Vertical axis: start a separate subpath.
        path.moveTo(
            center.x(),
            center.y() - radius,
        )

        path.lineTo(
            center.x(),
            center.y() + radius,
        )

        pen = QPen(color)
        pen.setWidth(2)
        pen.setCapStyle(Qt.FlatCap)

        item = QGraphicsPathItem(path)

        item.setPen(pen)
        item.setBrush(QBrush(Qt.NoBrush))

        # Preserve the original default stacking level.
        item.setZValue(0)

        self.scene.addItem(item)

        return item

    def set_mean_vector(
        self,
        center,
        length,
        angle_radians,
        color,
        visible,
    ):
        """Create or update the independent mean-azimuth vector.

        Azimuth is measured clockwise from north. Scene Y coordinates
        increase downward, so the north component is subtracted.
        """
        if (
            self.mean_item is None
            or sip.isdeleted(self.mean_item)
        ):
            self.mean_item = QGraphicsLineItem()

            self.mean_item.setZValue(2)

            self.scene.addItem(
                self.mean_item
            )

        east = sin(angle_radians) * length
        north = cos(angle_radians) * length

        self.mean_item.setLine(
            center.x(),
            center.y(),
            center.x() + east,
            center.y() - north,
        )

        pen = QPen(color)
        pen.setWidth(2)
        pen.setCapStyle(Qt.FlatCap)

        self.mean_item.setPen(pen)

        self.mean_item.setVisible(
            visible
        )

        return self.mean_item

    def set_screen_label(self, item, anchor, alignment="left", gap=6.0):
        """Register text that must retain screen alignment after resizing."""
        anchor = QPointF(anchor)
        factor = {"left": 0.0, "center": 0.5, "right": 1.0}[alignment]
        item.setPos(anchor.x() - item.boundingRect().width() * factor, anchor.y() + gap)
        self._screen_labels.append((item, anchor, alignment, float(gap)))