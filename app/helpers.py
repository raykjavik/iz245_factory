"""Reusable tab widget with LED indicators beside each tab caption."""
from PySide6.QtWidgets import QLabel, QTabBar, QTabWidget

LED_OK = """QLabel { border-radius: 9px; background: #27c93f;
                      border: 1px solid #1d7f2b; }"""
LED_NOK = """QLabel { border-radius: 9px; background: #ff4d4f;
                       border: 1px solid #b22222; }"""


def set_led_ok(led, is_ok):
    led.setStyleSheet(LED_OK if is_ok else LED_NOK)
    led.setToolTip("Ready" if is_ok else "Incomplete or not verified")
    led.setAccessibleName("Status: ready" if is_ok else "Status: incomplete")


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
