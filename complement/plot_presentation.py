from qgis.PyQt.QtCore import (
    QObject,
    QEvent,
    QPointF,
    QRectF,
    QTimer,
    Qt,
)
from qgis.PyQt.QtGui import QFont, QBrush, QColor, QPen
from qgis.PyQt.QtWidgets import (QGraphicsItem,QGraphicsSimpleTextItem,QGraphicsTextItem,)


PLOT_FONT_FAMILY = "Sans Serif"
PLOT_FONT_PIXELS = 12


def uniform_plot_fonts(scene, pixels=PLOT_FONT_PIXELS):
    """Apply the same screen-readable font to every text item."""
    font = QFont(PLOT_FONT_FAMILY)
    font.setPixelSize(pixels)
    font.setBold(False)

    for item in scene.items():
        if isinstance(
            item,
            (QGraphicsSimpleTextItem, QGraphicsTextItem),
        ):
            item.setFont(font)

            item.setFlag(
                QGraphicsItem.ItemIgnoresTransformations,
                True,
            )

            if isinstance(item, QGraphicsSimpleTextItem):
                # Fill glyphs without drawing an extra outline.
                item.setPen(QPen(Qt.NoPen))
                item.setBrush(QBrush(QColor("black")))


def position_north_label(view, item, center, radius, gap=8.0):
    """Safely center north label, discarding deleted C++ references."""
    try:
        # Check if C++ underlying pointer is still valid
        item.setRotation(0.0)
    except RuntimeError:
        return

    item.setTransformOriginPoint(QPointF(0.0, 0.0))
    anchor = QPointF(center.x(), center.y() - radius)
    item.setPos(anchor)

    transform = view.viewportTransform()
    inverse, invertible = transform.inverted()
    if not invertible:
        return

    anchor_px = transform.map(anchor)
    label_px = item.deviceTransform(transform).mapRect(item.boundingRect())
    offset_px = QPointF(
        anchor_px.x() - label_px.center().x(),
        anchor_px.y() - gap - label_px.bottom(),
    )
    offset_scene = inverse.map(offset_px) - inverse.map(QPointF(0.0, 0.0))
    item.moveBy(offset_scene.x(), offset_scene.y())


def position_screen_label(view, item, anchor, alignment="left", gap=6.0):
    """Align fixed-size text against a scene anchor after fitting the view."""
    try:
        item.setRotation(0.0)
        item.setPos(anchor)

        transform = view.viewportTransform()
        inverse, invertible = transform.inverted()

        if not invertible:
            return

        bounds = item.deviceTransform(transform).mapRect(item.boundingRect())
        anchor_px = transform.map(anchor)
        reference_x = {"left": bounds.left(), "center": bounds.center().x(), "right": bounds.right()}[alignment]

        delta_px = QPointF(anchor_px.x() - reference_x, anchor_px.y() + gap - bounds.top())
        delta_scene = inverse.map(delta_px) - inverse.map(QPointF(0.0, 0.0))
        item.moveBy(delta_scene.x(), delta_scene.y())

    except RuntimeError:
        return
    

class PlotAutoFit(QObject):
    """Fit the QQPlot and align its fixed-size screen labels."""

    def __init__(self, view):
        super().__init__(view)

        self.view = view
        self._bounds = None
        self._labels = []
        self._busy = False

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.fit)

        self.view.viewport().installEventFilter(self)

    def refresh(self, bounds, labels):
        """Publish a completed plot without rebuilding it on resize."""
        self._timer.stop()

        self._bounds = QRectF(bounds)
        self._labels = list(labels)

        scene = self.view.scene()

        if scene is None:
            self._bounds = None
            self._labels = []
            return

        uniform_plot_fonts(scene)

        self.view.setAlignment(Qt.AlignCenter)

        self.view.setHorizontalScrollBarPolicy(
            Qt.ScrollBarAlwaysOff
        )

        self.view.setVerticalScrollBarPolicy(
            Qt.ScrollBarAlwaysOff
        )

        scene.setSceneRect(self._bounds)
        self.view.setSceneRect(self._bounds)

        self.fit()
        self._timer.start(0)

    def eventFilter(self, watched, event):
        # Trigger resize auto-fit for all non-circular graphics view plots
        if watched is self.view.viewport() and getattr(self.view, "_active_plot", None) != "circle":
            if event.type() in (QEvent.Resize, QEvent.Show):
                if not self._busy:
                    self._timer.start(0)

        return super().eventFilter(watched, event)

    def fit(self):
        # Skip auto-fit if view is currently displaying the unit circle
        if getattr(self.view, "_active_plot", None) == "circle":
            return
        if self._busy or self._bounds is None:
            return

        viewport = self.view.viewport()
        if viewport.width() <= 2 or viewport.height() <= 2:
            return

        self._busy = True
        try:
            self.view.resetTransform()
            self.view.fitInView(self._bounds, Qt.KeepAspectRatio)
            self.view.centerOn(self._bounds.center())

            transform = self.view.viewportTransform()
            inverse, invertible = transform.inverted()
            if not invertible:
                return

            origin = inverse.map(QPointF(0.0, 0.0))

            valid_labels = []
            for item, anchor, horizontal, vertical, dx, dy in self._labels:
                try:
                    item.setPos(anchor)
                    rect = item.deviceTransform(transform).mapRect(item.boundingRect())
                except RuntimeError:
                    continue

                anchor_px = transform.map(anchor)
                ref_x = {"left": rect.left(), "center": rect.center().x(), "right": rect.right()}[horizontal]
                ref_y = {"top": rect.top(), "center": rect.center().y(), "bottom": rect.bottom()}[vertical]

                offset_px = QPointF(anchor_px.x() + dx - ref_x, anchor_px.y() + dy - ref_y)
                offset_scene = inverse.map(offset_px) - origin
                item.moveBy(offset_scene.x(), offset_scene.y())
                valid_labels.append((item, anchor, horizontal, vertical, dx, dy))

            self._labels = valid_labels
        finally:
            self._busy = False


class HistogramAutoFit(PlotAutoFit):
    """Fit cached histogram geometry and maintain screen-space label spacing."""

    def __init__(self, view):
        super().__init__(view)
        self._plot_rect = None
        self._tick_groups = []
        self._margins = (90.0, 55.0, 50.0, 80.0)

    def clear(self):
        self._timer.stop()
        self._bounds = None
        self._labels = []
        self._plot_rect = None
        self._tick_groups = []

    def refresh(self, plot_rect, labels, tick_groups, margins):
        self._plot_rect = QRectF(plot_rect)
        self._tick_groups = [list(group) for group in tick_groups]
        self._margins = tuple(margins)
        super().refresh(plot_rect, labels)

    def eventFilter(self, watched, event):
        if getattr(self.view, "_active_plot", None) != "hist":
            return False
        return super().eventFilter(watched, event)

    def fit(self):
        if getattr(self.view, "_active_plot", None) != "hist":
            return

        if self._plot_rect is None or self._busy:
            return

        viewport = self.view.viewport()
        if viewport.width() <= 2 or viewport.height() <= 2:
            return

        rect = self._plot_rect
        if rect.width() <= 0 or rect.height() <= 0:
            return

        # Reserve label margins in screen pixels rather than scene units.
        left, top, right, bottom = self._margins
        scale_x = max(1.0, viewport.width() - left - right - 4.0) / rect.width()
        scale_y = max(1.0, viewport.height() - top - bottom - 4.0) / rect.height()
        scale = min(scale_x, scale_y)
        self._bounds = rect.adjusted(-left / scale, -top / scale, right / scale, bottom / scale)

        scene = self.view.scene()
        if scene is None:
            return

        scene.setSceneRect(self._bounds)
        self.view.setSceneRect(self._bounds)
        super().fit()

        # Hide overlapping tick labels without removing observations or guides.
        transform = self.view.viewportTransform()

        for group in self._tick_groups:
            count = len(group)
            priority = list(dict.fromkeys([0, count - 1, count // 2] + list(range(count)))) if count else []
            accepted = []

            for index in priority:
                item = group[index]

                try:
                    bounds = item.deviceTransform(transform).mapRect(item.boundingRect()).adjusted(-4.0, -3.0, 4.0, 3.0)
                    visible = not any(bounds.intersects(other) for other in accepted)
                    item.setVisible(visible)

                    if visible:
                        accepted.append(bounds)

                except RuntimeError:
                    continue