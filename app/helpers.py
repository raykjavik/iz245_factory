"""Reusable tab widget with LED indicators beside each tab caption."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QTabBar, QTabWidget, QWidget, QToolButton, QVBoxLayout
from chart_style import PASS_COLOR

LED_OK = """QLabel { border-radius: 9px; background: COLOR;
                      border: 1px solid #1d7f2b; }""".replace('COLOR', PASS_COLOR)
LED_NOK = """QLabel { border-radius: 9px; background: #ff4d4f;
                       border: 1px solid #b22222; }"""


def set_led_ok(led, is_ok):
    led.setStyleSheet(LED_OK if is_ok else LED_NOK)
    led.setToolTip("Ready" if is_ok else "Incomplete or not verified")
    led.setAccessibleName("Status: ready" if is_ok else "Status: incomplete")


class CollapsibleSection(QWidget):
    """A heading button and a body; add controls to content_layout."""
    def __init__(self, title, parent=None, expanded=False):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.toggle_button = QToolButton()
        self.toggle_button.setText(title)
        self.toggle_button.setCheckable(True)
        self.toggle_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle_button.setAccessibleName(title)
        self.body = QWidget()
        self.content_layout = QVBoxLayout(self.body)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.toggle_button)
        layout.addWidget(self.body)
        self.toggle_button.toggled.connect(self._set_visible)
        self.toggle_button.setChecked(expanded)
        self._set_visible(expanded)

    def set_expanded(self, expanded):
        self.toggle_button.setChecked(expanded)

    def _set_visible(self, expanded):
        self.body.setVisible(expanded)
        self.toggle_button.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)


class LedTabWidget(QTabWidget):
    """Use add_led_tab(), then set_tab_ok(widget, bool) to update status.

    Indicators are keyed by page widget so reordering tabs stays safe.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self._leds = {}

    def add_led_tab(self, widget, label, is_ok=False):
        index = self.addTab(widget, label)
        led = QLabel(self.tabBar())
        led.setFixedSize(18, 18)
        set_led_ok(led, is_ok)
        self.tabBar().setTabButton(index, QTabBar.ButtonPosition.LeftSide, led)
        self._leds[widget] = led
        return index

    def set_tab_ok(self, widget, is_ok):
        set_led_ok(self._leds[widget], is_ok)
