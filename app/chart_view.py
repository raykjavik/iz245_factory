"""Zoom and pan controls that keep a live-data reset range."""
from PySide6.QtCore import Qt
from PySide6.QtCharts import QChartView


class CalibrationChartView(QChartView):
    def __init__(self, chart, parent=None):
        super().__init__(chart, parent)
        self.setRubberBand(QChartView.RubberBand.RectangleRubberBand)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.setToolTip('Wheel: zoom. Left-drag: zoom area. Right-drag: pan. Home: reset.')
        self._pan_start = None
        self._full_ranges = []
        self.user_navigated = False

    def remember_full_view(self, ranges=None):
        self._full_ranges = ([(a, a.min(), a.max()) for a in self.chart().axes()]
                             if ranges is None else list(ranges))

    def clear_full_view(self):
        self._full_ranges = []
        self.user_navigated = False

    def zoom_by(self, factor):
        if self.chart().series():
            self.chart().zoom(factor)
            self.user_navigated = True

    def reset_view(self):
        self.chart().zoomReset()
        for axis, low, high in self._full_ranges:
            axis.setRange(low, high)
        self.user_navigated = False

    def wheelEvent(self, event):
        delta = event.angleDelta().y() or event.pixelDelta().y()
        if delta and self.chart().series():
            self.zoom_by(1.25 ** max(-8, min(8, delta / 120)))
            event.accept()
        else:
            event.ignore()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            self._pan_start = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._pan_start is not None:
            delta = event.position() - self._pan_start
            self._pan_start = event.position()
            self.chart().scroll(-delta.x(), delta.y())
            self.user_navigated = True
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            self._pan_start = None
            self.unsetCursor()
            event.accept()
        else:
            super().mouseReleaseEvent(event)
            if event.button() == Qt.MouseButton.LeftButton and self.chart().isZoomed():
                self.user_navigated = True

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            self.zoom_by(1.25)
        elif event.key() == Qt.Key.Key_Minus:
            self.zoom_by(1 / 1.25)
        elif event.key() in (Qt.Key.Key_Home, Qt.Key.Key_0):
            self.reset_view()
        else:
            super().keyPressEvent(event)
            return
        event.accept()


def _nice_step(span, target=6):
    import math
    raw = max(span / target, 1e-12)
    magnitude = 10 ** math.floor(math.log10(raw))
    fraction = raw / magnitude
    factor = next(n for n in (1, 2, 2.5, 5, 10) if fraction <= n)
    return factor * magnitude


def update_tick_spacing(axis, low, high):
    """Readable 1/2/2.5/5 steps, including after zooming and panning."""
    from PySide6.QtCharts import QValueAxis
    if isinstance(axis, QValueAxis):
        axis.setTickType(QValueAxis.TickType.TicksDynamic)
        axis.setTickAnchor(0)
        axis.setTickInterval(_nice_step(high - low))
        axis.setMinorTickCount(1)


def nice_axis_range(axis, low, high):
    import math
    from PySide6.QtCharts import QLogValueAxis
    if isinstance(axis, QLogValueAxis):
        axis.setMinorTickCount(8)
        return 10 ** math.floor(math.log10(low)), 10 ** math.ceil(math.log10(high))
    step = _nice_step(high - low)
    update_tick_spacing(axis, low, high)
    return math.floor(low / step) * step, math.ceil(high / step) * step
