import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import time
import threading
import connection_cfg
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
from PySide6.QtCore import QSettings
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication
from PySide6.QtCharts import QLogValueAxis, QValueAxis
import calib_controller
import calib_tab
from calib_tab import CalibrationTab
from app import MainWindow
from project import FactoryProject
from test_calibration import Device, Generator


class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.settings_tmp = tempfile.TemporaryDirectory()
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, cls.settings_tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls.settings_tmp.cleanup()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.name = 'sample.txt'
        cfg = {self.name: (np.array([100000, 1000000, 10000000]), ['sys:cal:off'])}
        for module in (calib_controller, calib_tab):
            p = patch.object(module, 'CFG_CALIB_ALL', cfg)
            p.start()
            self.addCleanup(p.stop)
        self.tab = CalibrationTab(device_factory=Device, generator_factory=lambda ip, port: Generator(ip))
        self.addCleanup(self.tab.deleteLater)
        self.prj = SimpleNamespace(root=Path(self.tmp.name), prop_auto=SimpleNamespace(
            calibration_temperature='24', dut_ip='10.0.1.245'))
        self.tab.load_project(self.prj)

    def pump_until(self, predicate):
        deadline = time.monotonic() + 5
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.001)
        self.assertTrue(predicate())

    def test_thread_measure_updates_led_and_plot_and_unlocks_actions(self):
        self.assertFalse(self.tab.rows[self.name]['show'].isEnabled())
        self.tab.start('measure', self.name)
        self.assertTrue(self.tab.busy)
        self.assertFalse(self.tab.ch1.isEnabled())
        self.assertFalse(self.tab.download_all.isEnabled())
        self.assertFalse(self.tab.rows[self.name]['download'].isEnabled())
        self.assertTrue(self.tab.abort.isEnabled())
        self.pump_until(lambda: not self.tab.busy)
        self.assertIn('Completed', self.tab.status.text())
        row = self.tab.rows[self.name]
        self.assertTrue(row['show'].isEnabled())
        self.assertTrue(row['upload'].isEnabled())
        self.assertFalse(self.tab.abort.isEnabled())
        self.assertEqual(self.tab.progress.value(), self.tab.progress.maximum())
        row['show'].setChecked(True)
        self.assertEqual(len(self.tab.chart.series()), 1)
        series = self.tab.chart.series()[0]
        self.assertAlmostEqual(series.at(0).x(), 0.1)
        self.assertAlmostEqual(series.at(0).y(), 0.1)
        self.assertTrue(any(isinstance(a, QLogValueAxis) for a in self.tab.chart.axes()))
        self.tab.scale.setCurrentIndex(1)
        self.assertFalse(any(isinstance(a, QLogValueAxis) for a in self.tab.chart.axes()))
        self.assertEqual(len(self.tab.chart.series()), 1)
        self.assertEqual(self.tab.chart.series()[0].count(), 3)

    def test_abort_waits_for_cleanup_and_preserves_missing_file(self):
        entered, release = threading.Event(), threading.Event()
        class SlowDevice(Device):
            def measure_point_rms(self, f, dwell):
                entered.set()
                release.wait(3)
                return super().measure_point_rms(f, dwell)
        self.tab.device_factory = SlowDevice
        self.tab.start('measure', self.name)
        try:
            self.pump_until(entered.is_set)
            self.tab.abort_measurement()
            self.assertTrue(self.tab.busy)
            self.assertFalse(self.tab.abort.isEnabled())
        finally:
            release.set()
            self.pump_until(lambda: not self.tab.busy)
        self.assertIn('Aborted', self.tab.status.text())
        self.assertFalse((self.prj.root / 'calib' / self.name).exists())
        self.assertFalse(self.tab.rows[self.name]['show'].isEnabled())

    def test_completed_signal_arrives_while_worker_is_still_busy(self):
        received = []
        self.tab.validity_changed.connect(lambda ok: received.append((ok, self.tab.busy)))
        self.tab.start('measure', self.name)
        self.pump_until(lambda: not self.tab.busy)
        self.assertIn((True, True), received)

    def test_worker_failure_shows_error_and_releases_busy_state(self):
        class FailingDevice(Device):
            def measure_point_rms(self, f, dwell):
                raise RuntimeError('Instrument disconnected')
        self.tab.device_factory = FailingDevice
        with patch('calib_tab.QMessageBox.critical') as error:
            self.tab.start('measure', self.name)
            self.pump_until(lambda: not self.tab.busy)
            error.assert_called_once()
        self.assertIn('Instrument disconnected', self.tab.status.text())
        self.assertTrue(self.tab.ch1.isEnabled())
        self.assertFalse(self.tab.abort.isEnabled())

    def test_main_window_blocks_project_changes_and_close_while_busy(self):
        window = MainWindow(device_factory=Device, generator_factory=lambda ip, port: Generator(ip))
        self.addCleanup(window.deleteLater)
        window.project_menu._activate(FactoryProject.new_project(Path(self.tmp.name) / 'factory.prj'))
        entered, release = threading.Event(), threading.Event()
        class SlowDevice(Device):
            def measure_point_rms(self, f, dwell):
                entered.set()
                release.wait(3)
                return 1
        tab = window.calibration_tab
        tab.device_factory = SlowDevice
        tab.start('measure', self.name)
        try:
            self.pump_until(entered.is_set)
            self.assertFalse(window.menuBar().isEnabled())
            self.assertFalse(window.project_tab.isEnabled())
            event = QCloseEvent()
            window.closeEvent(event)
            self.assertFalse(event.isAccepted())
            tab.abort_measurement()
        finally:
            release.set()
            self.pump_until(lambda: not tab.busy)
        self.assertTrue(window.menuBar().isEnabled())
        self.assertTrue(window.project_tab.isEnabled())

    def test_only_operator_and_dwell_are_settings_and_constants_are_used(self):
        self.assertEqual(set(self.tab.fields), {'operator'})
        self.assertEqual(self.tab.settings_box.layout().rowCount(), 2)
        options = self.tab._options()
        self.assertEqual(options['generator_ip'], connection_cfg.GENERATOR_IP)
        self.assertEqual(options['generator_port'], connection_cfg.GENERATOR_PORT)
        self.assertEqual(options['transfer'].username, 'root')
        self.assertTrue(options['transfer'].auto_accept_new_host)
        self.assertEqual(Path(options['transfer'].key_path).name, '245.ppk')

    def test_tab_led_reflects_all_files_present_row_requires_measured_data(self):
        states = []
        self.tab.validity_changed.connect(states.append)
        self.tab._refresh()
        self.assertFalse(states[-1])
        path = self.prj.root / 'calib' / self.name
        path.parent.mkdir()
        path.write_text('freq[Hz];Limit[dB];\n100000;;\n')
        self.tab.backend.reload()
        self.tab._refresh()
        self.assertTrue(states[-1])
        self.assertFalse(self.tab.rows[self.name]['show'].isEnabled())
        path.unlink()
        self.tab._refresh()
        self.assertFalse(states[-1])

    def test_download_all_button_starts_bulk_action(self):
        with patch.object(self.tab, 'start') as start:
            self.tab.download_all.click()
            start.assert_called_once_with('download_all')

    def test_external_hardware_work_blocks_actions(self):
        self.tab.set_external_busy(True)
        self.assertFalse(self.tab.ch1.isEnabled())
        self.assertFalse(self.tab.download_all.isEnabled())
        self.assertFalse(self.tab.rows[self.name]['measure'].isEnabled())
        self.tab.set_external_busy(False)
        self.assertTrue(self.tab.ch1.isEnabled())


if __name__ == '__main__':
    unittest.main()
