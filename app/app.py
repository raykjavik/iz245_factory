"""Run with: python app.py"""
import sys
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMainWindow
from helpers import LedTabWidget
from prj_tab import ProjectTab
from settings_tab import SettingsTab
from measurement_toolbar import MeasurementToolbar
from calib_tab import CalibrationTab, CalibrationVerificationTab, NoisePreselectorsTab, NoiseDensityTab
from ip3_tab import IP3Tab
from if_spectrum_tab import IFSpectrumTab
from menu import ProjectMenu
from controller import Controller
import project as project_model


class MainWindow(QMainWindow):
    def __init__(self, generator_factory=None, device_factory=None, ip3_generator_factory=None):
        super().__init__()
        self.resize(1440, 850)
        self.tabs = LedTabWidget()
        self.setCentralWidget(self.tabs)
        self.project_tab = ProjectTab()
        self.settings_tab = SettingsTab()
        self.calibration_tab = CalibrationTab(generator_factory=generator_factory,
                                              device_factory=device_factory)
        self.verification_tab = CalibrationVerificationTab(generator_factory=generator_factory,
                                                           device_factory=device_factory)
        self.noise_tab = NoisePreselectorsTab(generator_factory=generator_factory,
                                             device_factory=device_factory)
        self.density_tab = NoiseDensityTab(generator_factory=generator_factory,
                                           device_factory=device_factory)
        self.ip3_tab = IP3Tab(device_factory=device_factory,
                              ip3_generator_factory=ip3_generator_factory)
        self.if_spectrum_tab = IFSpectrumTab(device_factory=device_factory)
        self.workflow_tabs = [self.calibration_tab, self.verification_tab, self.noise_tab,self.density_tab,self.ip3_tab,self.if_spectrum_tab]
        for page, title in ((self.settings_tab, "Settings"),
                            (self.project_tab, "Project details"),
                            (self.calibration_tab, "Calibrations"),
                            (self.verification_tab, "Calibration verification"),
                            (self.noise_tab, "Noise, Preselectors && Internal"),
                            (self.density_tab,"Phase && amplitude noise"),
                            (self.ip3_tab,"IP3 && SFDR"),
                            (self.if_spectrum_tab,"IF filter spectra")):
            self.tabs.add_led_tab(page, title)
            page.validity_changed.connect(lambda ok, page=page: self.tabs.set_tab_ok(page, ok))
        self.project_menu = ProjectMenu(self, self.project_tab,
                                        [self.settings_tab, *self.workflow_tabs])
        self.controller = Controller(lambda: self.project_menu.project, self,
                                     device_factory=device_factory)
        self.run_toolbar = MeasurementToolbar(self.workflow_tabs, self)
        self.addToolBar(self.run_toolbar)
        self.settings_tab.connect_requested.connect(self.controller.connect_device)
        self.settings_tab.changed.connect(self.project_menu.mark_dirty)
        self.settings_tab.changed.connect(self.project_tab._refresh_auto_display)
        self.settings_tab.dut_changed.connect(self.project_tab.invalidate_device)
        self.controller.connection_failed.connect(self.settings_tab.connection_failed)
        self.controller.auto_properties_updated.connect(self.settings_tab.connection_complete)
        self.controller.auto_properties_updated.connect(self.project_tab.refresh_auto_properties)
        self.controller.auto_properties_updated.connect(self.project_menu.mark_dirty)
        self.controller.connection_failed.connect(self.project_tab.connection_failed)
        self.controller.message.connect(self.statusBar().showMessage)
        self.controller.busy_changed.connect(self._update_busy)
        for page in self.workflow_tabs:
            self.settings_tab.changed.connect(page.setup_changed)
            page.changed.connect(self.project_menu.mark_dirty)
            page.changed.connect(self.project_tab._refresh_auto_display)
            page.message.connect(self.statusBar().showMessage)
            page.busy_changed.connect(self._update_busy)
            for destination in self.workflow_tabs:
                if destination is page:
                    continue
                page.measurement_completed.connect(destination._on_completed)
                page.measurement_started.connect(destination._on_measurement_started)
                page.point_measured.connect(destination._on_point_measured)
                page.density_updated.connect(destination._on_density_updated)
                page.ip3_updated.connect(destination._on_ip3_updated)
                page.spectrum_updated.connect(destination._on_spectrum_updated)
                page.run_finished.connect(destination.finish_external_run)
        self.statusBar().showMessage("Create or open a project to begin.")
        self.project_menu.open_default_project(project_model.DEFAULT_PROJECT_PATH)

    def _update_busy(self, *_):
        busy = self.controller.busy or any(page.busy for page in self.workflow_tabs)
        for page in self.workflow_tabs:
            page.set_external_busy(busy and not page.busy)
        self.menuBar().setEnabled(not busy)
        self.project_tab.setEnabled(not busy)
        self.settings_tab.setEnabled(not busy and self.project_menu.project is not None)

    def closeEvent(self, event):
        if self.controller.busy or any(page.busy for page in self.workflow_tabs):
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
