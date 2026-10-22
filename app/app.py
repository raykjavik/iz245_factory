"""Run with: python app.py"""
import sys
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMainWindow
from helpers import LedTabWidget
from prj_tab import ProjectTab
from calib_tab import CalibrationTab, VerificationTab
from menu import ProjectMenu
from controller import Controller


class MainWindow(QMainWindow):
    def __init__(self, device_factory=None, generator_factory=None):
        super().__init__()
        self.resize(1440, 850)
        self.tabs = LedTabWidget()
        self.setCentralWidget(self.tabs)
        self.project_tab = ProjectTab()
        self.calibration_tab = CalibrationTab(device_factory=device_factory,
                                              generator_factory=generator_factory)
        self.verification_tab = VerificationTab()
        for page, title in ((self.project_tab, "Project details"),
                            (self.calibration_tab, "Calibrations"),
                            (self.verification_tab, "Verification")):
            self.tabs.add_led_tab(page, title)
            page.validity_changed.connect(lambda ok, page=page: self.tabs.set_tab_ok(page, ok))
        self.project_menu = ProjectMenu(self, self.project_tab,
                                        [self.calibration_tab, self.verification_tab])
        self.controller = Controller(lambda: self.project_menu.project, self,
                                     device_factory=device_factory)
        self.project_tab.connect_requested.connect(self.controller.connect_device)
        self.controller.auto_properties_updated.connect(self.project_tab.refresh_auto_properties)
        self.controller.auto_properties_updated.connect(self.project_menu.mark_dirty)
        self.controller.connection_failed.connect(self.project_tab.connection_failed)
        self.controller.message.connect(self.statusBar().showMessage)
        self.calibration_tab.message.connect(self.statusBar().showMessage)
        self.controller.busy_changed.connect(self.calibration_tab.set_external_busy)
        self.controller.busy_changed.connect(self._update_busy)
        self.calibration_tab.busy_changed.connect(self._update_busy)
        self.statusBar().showMessage("Create or open a project to begin.")

    def _update_busy(self, *_):
        busy = self.controller.busy or self.calibration_tab.busy
        self.menuBar().setEnabled(not busy)
        self.project_tab.setEnabled(not busy)

    def closeEvent(self, event):
        if self.controller.busy or self.calibration_tab.busy:
            self.statusBar().showMessage("Hardware work is running; abort or wait for completion before closing.")
            event.ignore()
            return
        if self.project_menu.confirm_discard():
            event.accept()
        else:
            event.ignore()


def main():
    app = QApplication(sys.argv)
    app.styleHints().setColorScheme(Qt.ColorScheme.Light)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
