"""Calibration controls, threaded hardware work, and frequency plots."""
from pathlib import Path
import threading
import socket
import numpy as np
from PySide6.QtCore import Qt, QThread, Signal, QSettings
from PySide6.QtGui import QColor, QPainter
from PySide6.QtCharts import QChart, QChartView, QLineSeries, QValueAxis, QLogValueAxis
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QCheckBox, QHeaderView, QSplitter, QComboBox,
    QProgressBar, QMessageBox, QGroupBox, QFormLayout, QLineEdit, QDoubleSpinBox)
from helpers import set_led_ok
from calib_controller import CalibrationController, CFG_CALIB_ALL, measured
from ssh_utils import TransferSettings, PuttyTransfer, Aborted
from controller import default_device_factory
import connection_cfg as connections
from iz245.device import SMA1000B


def default_generator_factory(ip, port):
    class ConfiguredGenerator(SMA1000B):
        def open(self, tdoa_setting=False):
            # The supplied SMA1000B.open ignores self.port.
            with self.scpi_lock:
                self.close()
                try:
                    self.main_scpi = socket.create_connection((self.ip, self.port), timeout=10)
                    self.connected = True
                    return True
                except OSError:
                    self.close()
                    return False
    return ConfiguredGenerator(ip, port=port)


class _CalibrationThread(QThread):
    progress = Signal(int, int)
    completed = Signal(str, object)
    status = Signal(str)

    def __init__(self, project, action, name, options, device_factory, generator_factory, parent=None):
        super().__init__(parent)
        self.project, self.action, self.name = project, action, name
        self.options = options
        self.device_factory, self.generator_factory = device_factory, generator_factory
        self.cancel = threading.Event()
        self.error, self.aborted = None, False

    def run(self):
        dev = gen = None
        try:
            options = self.options
            needs_hardware = self.action in ('measure', 'ch1', 'ch2')
            transfer = None
            if self.action != 'measure':
                options['transfer'].validate()
                transfer = PuttyTransfer(options['transfer'], self.cancel)
            backend = CalibrationController(None, None, self.project,
                dwell_sec=options['dwell'], operator=options['operator'], transfer=transfer,
                cancel=self.cancel, progress=self.progress.emit,
                completed=self.completed.emit, status=self.status.emit)
            if needs_hardware:
                self.status.emit("Connecting DUT and generator…")
                dev = self.device_factory(options['dut_ip'])
                backend.dev = dev
                if not dev.open(tdoa_setting=False):
                    raise ConnectionError("Could not connect to DUT.")
                gen = self.generator_factory(options['generator_ip'], options['generator_port'])
                backend.gen = gen
                if not gen.open(tdoa_setting=False):
                    raise ConnectionError("Could not connect to signal generator.")
            backend.run(self.action, self.name)
        except Aborted:
            self.aborted = True
        except Exception as exc:
            self.error = str(exc) or type(exc).__name__
        finally:
            cleanup_errors = []
            if gen is not None:
                try:
                    if gen.connected:
                        gen.cmd('OUTP:STAT 0')
                except Exception as exc:
                    cleanup_errors.append(f"Cannot turn generator output off: {exc}")
                try:
                    gen.close()
                except Exception as exc:
                    cleanup_errors.append(f"Cannot close generator: {exc}")
            if dev is not None:
                try:
                    dev.close()
                except Exception as exc:
                    cleanup_errors.append(f"Cannot close DUT: {exc}")
            if cleanup_errors:
                self.error = '; '.join(([self.error] if self.error else []) + cleanup_errors)


class WorkflowTab(QWidget):
    validity_changed = Signal(bool)

    def __init__(self, title, description, parent=None):
        super().__init__(parent)
        self.project = None
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"<h2>{title}</h2>"))
        label = QLabel(description)
        label.setWordWrap(True)
        layout.addWidget(label)
        self.location = QLabel("No project loaded.")
        layout.addWidget(self.location)
        layout.addStretch()

    def load_project(self, project):
        self.project = project
        self.location.setText(f"Project folder: {project.root}")
        self.validity_changed.emit(False)


class CalibrationTab(QWidget):
    validity_changed = Signal(bool)
    busy_changed = Signal(bool)
    message = Signal(str)

    def __init__(self, parent=None, device_factory=None, generator_factory=None):
        super().__init__(parent)
        self.project = self.backend = self._thread = None
        self._external_busy = False
        self.device_factory = device_factory or default_device_factory
        self.generator_factory = generator_factory or default_generator_factory
        self.rows = {}
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        self.ch1 = QPushButton('CALIBRATE CH1')
        self.ch2 = QPushButton('CALIBRATE CH2')
        self.download_all = QPushButton('Download All')
        self.abort = QPushButton('Abort')
        for button in (self.ch1, self.ch2, self.download_all, self.abort):
            top.addWidget(button)
        top.addStretch()
        layout.addLayout(top)
        self.ch1.clicked.connect(lambda: self.start('ch1'))
        self.ch2.clicked.connect(lambda: self.start('ch2'))
        self.download_all.clicked.connect(lambda: self.start('download_all'))
        self.abort.clicked.connect(self.abort_measurement)
        self.settings_box = QGroupBox('Measurement settings')
        form = QFormLayout(self.settings_box)
        settings = QSettings('ReceiverFactory', 'Calibration')
        self.fields = {}
        self.fields['operator'] = QLineEdit(str(settings.value('operator', 'VHU')))
        form.addRow('Operator', self.fields['operator'])
        self.dwell = QDoubleSpinBox()
        self.dwell.setRange(0.001, 60)
        self.dwell.setDecimals(3)
        self.dwell.setSuffix(' s / point')
        self.dwell.setValue(float(settings.value('dwell', 0.1)))
        form.addRow('Dwell time (verify for your DUT)', self.dwell)
        layout.addWidget(self.settings_box)
        self.location = QLabel('No project loaded.')
        layout.addWidget(self.location)
        layout.addWidget(QLabel('Connect the generator to the selected channel before starting its pipeline.'))
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(['Name', 'Available', 'Upload', 'Measure', 'Download', 'Show'])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, 6):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        splitter.addWidget(self.table)
        plot_widget = QWidget()
        plot_layout = QVBoxLayout(plot_widget)
        plot_top = QHBoxLayout()
        plot_top.addWidget(QLabel('Frequency scale'))
        self.scale = QComboBox()
        self.scale.addItems(['Logarithmic', 'Linear'])
        self.scale.currentIndexChanged.connect(self.redraw)
        plot_top.addWidget(self.scale)
        plot_top.addStretch()
        plot_layout.addLayout(plot_top)
        self.chart = QChart()
        self.chart.setTitle('Select calibrations using Show')
        self.chart_view = QChartView(self.chart)
        self.chart_view.setRenderHint(QPainter.RenderHint.Antialiasing)
        plot_layout.addWidget(self.chart_view)
        splitter.addWidget(plot_widget)
        splitter.setSizes([680, 650])
        layout.addWidget(splitter, 1)
        self.status = QLabel('Open a project to begin.')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        layout.addWidget(self.progress)
        self._update_enabled()
        self.redraw()

    @property
    def busy(self):
        return self._thread is not None

    def set_external_busy(self, busy):
        self._external_busy = busy
        self._update_enabled()

    def load_project(self, project):
        if self.busy:
            raise RuntimeError('Cannot change project during calibration.')
        self.project = project
        self.backend = CalibrationController(None, None, project)
        self.location.setText(f'Project folder: {project.root} | DUT: {project.prop_auto.dut_ip}')
        self.table.setRowCount(len(CFG_CALIB_ALL))
        self.rows.clear()
        for row, name in enumerate(CFG_CALIB_ALL):
            item = QTableWidgetItem(name)
            item.setToolTip(name)
            self.table.setItem(row, 0, item)
            led = QLabel()
            led.setFixedSize(18, 18)
            led_holder = QWidget()
            led_layout = QHBoxLayout(led_holder)
            led_layout.setContentsMargins(0, 0, 0, 0)
            led_layout.addWidget(led, alignment=Qt.AlignmentFlag.AlignCenter)
            self.table.setCellWidget(row, 1, led_holder)
            buttons = {}
            for column, action in enumerate(('upload', 'measure', 'download'), 2):
                button = QPushButton(action.capitalize())
                button.clicked.connect(lambda checked=False, action=action, name=name: self.start(action, name))
                self.table.setCellWidget(row, column, button)
                buttons[action] = button
            show = QCheckBox()
            show.toggled.connect(self.redraw)
            self.table.setCellWidget(row, 5, show)
            self.rows[name] = {'led': led, 'show': show, **buttons}
        self.progress.setValue(0)
        if self.backend.errors:
            self._set_status('Some files could not be read; hover their indicators for details.')
        else:
            self._set_status('Ready. Connect cables for CH1 or CH2 before measuring.')
        self._refresh()

    def _refresh(self):
        for name, row in self.rows.items():
            cm = self.backend.calibrations[name]
            ok = measured(cm)
            set_led_ok(row['led'], ok)
            row['led'].setToolTip(self.backend.errors.get(name) or
                                 ('Measured data available locally' if ok else 'No complete measured data'))
            if not ok:
                row['show'].setChecked(False)
        self._update_enabled()
        # Tab readiness means every configured file exists locally. Row LEDs
        # retain the stricter measured-data check used by Upload/Show.
        self.validity_changed.emit(bool(self.rows) and all(
            self.backend.path(name).is_file() for name in self.rows))
        self.redraw()

    def _update_enabled(self):
        enabled = self.project is not None and not self.busy and not self._external_busy
        self.ch1.setEnabled(enabled)
        self.ch2.setEnabled(enabled)
        self.download_all.setEnabled(enabled)
        self.abort.setEnabled(self.busy and not self._thread.cancel.is_set())
        self.settings_box.setEnabled(not self.busy)
        for name, row in self.rows.items():
            available = measured(self.backend.calibrations[name])
            row['upload'].setEnabled(enabled and available)
            row['measure'].setEnabled(enabled)
            row['download'].setEnabled(enabled)
            row['show'].setEnabled(available)

    def _options(self):
        operator = self.fields['operator'].text().strip()
        dwell = self.dwell.value()
        settings = QSettings('ReceiverFactory', 'Calibration')
        settings.setValue('operator', operator)
        settings.setValue('dwell', dwell)
        dut_ip = self.project.prop_auto.dut_ip.strip()
        transfer = TransferSettings(host=dut_ip, username=connections.SSH_USERNAME,
            remote_dir=connections.SSH_REMOTE_CALIB_DIR,
            key_path=str(connections.PUTTY_KEY_PATH),
            pscp=connections.PSCP_EXECUTABLE, port=connections.SSH_PORT,
            timeout=connections.SSH_TRANSFER_TIMEOUT_SEC,
            auto_accept_new_host=connections.SSH_AUTO_ACCEPT_NEW_HOST)
        return dict(dut_ip=dut_ip, generator_ip=connections.GENERATOR_IP,
                    generator_port=connections.GENERATOR_PORT,
                    operator=operator, dwell=dwell, transfer=transfer)

    def start(self, action, name=None):
        if self.busy or self._external_busy or self.project is None:
            return
        options = self._options()
        try:
            if action != 'measure':
                options['transfer'].validate()
            if action in ('measure', 'ch1', 'ch2') and not options['generator_ip']:
                raise ValueError('Set GENERATOR_IP in connection_cfg.py.')
        except Exception as exc:
            QMessageBox.warning(self, 'Calibration settings', str(exc))
            return
        self._thread = _CalibrationThread(self.project, action, name, options,
            self.device_factory, self.generator_factory, self)
        self._thread.progress.connect(self._on_progress)
        self._thread.completed.connect(self._on_completed)
        self._thread.status.connect(self._set_status)
        self._thread.finished.connect(self._finished)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self._set_status('Starting…')
        self._update_enabled()
        self.busy_changed.emit(True)
        self._thread.start()

    def abort_measurement(self):
        if self._thread:
            self._thread.cancel.set()
            self.abort.setEnabled(False)
            self._set_status('Aborting… waiting for the current device call to finish.')

    def _on_progress(self, done, total):
        self.progress.setRange(0, total)
        self.progress.setValue(done)
        self.progress.setFormat('%p% — %v / %m work units')

    def _on_completed(self, name, cm):
        self.backend.calibrations[name] = cm
        self.backend.errors.pop(name, None)
        self._refresh()

    def _set_status(self, text):
        self.status.setText(text)
        self.message.emit(text)

    def _finished(self):
        thread = self._thread
        self._thread = None
        self.backend.reload()
        self._refresh()
        self.busy_changed.emit(False)
        if thread.error:
            self._set_status(f'Failed: {thread.error}')
            QMessageBox.critical(self, 'Calibration failed', thread.error)
        elif thread.aborted:
            self._set_status('Aborted. Completed calibrations have been kept.')
        else:
            self._set_status('Completed. DUT and generator disconnected.')
            self.progress.setValue(self.progress.maximum())
        thread.deleteLater()

    def redraw(self, *_):
        self.chart.removeAllSeries()
        for axis in self.chart.axes():
            self.chart.removeAxis(axis)
            axis.deleteLater()
        if self.scale.currentIndex() == 0:
            x_axis = QLogValueAxis()
            x_axis.setBase(10)
        else:
            x_axis = QValueAxis()
            x_axis.setTickCount(6)
        x_axis.setTitleText('Frequency [MHz]')
        x_axis.setLabelFormat('%.3g')
        y_axis = QValueAxis()
        y_axis.setTitleText('Limit [dB]')
        y_axis.setLabelFormat('%.2f')
        self.chart.addAxis(x_axis, Qt.AlignmentFlag.AlignBottom)
        self.chart.addAxis(y_axis, Qt.AlignmentFlag.AlignLeft)
        palette = ['#0072b2', '#d55e00', '#009e73', '#cc79a7', '#e69f00', '#56b4e9', '#444444']
        all_x, all_y = [], []
        if self.backend:
            for index, (name, row) in enumerate(self.rows.items()):
                cm = self.backend.calibrations[name]
                if not row['show'].isChecked() or not measured(cm):
                    continue
                series = QLineSeries()
                series.setName(Path(name).stem.replace('CALIBRATION_', '').replace('_', ' '))
                series.setColor(QColor(palette[index % len(palette)]))
                xs, ys = np.asarray(cm.freq_hz) / 1e6, np.asarray(cm.limit_dB)
                for x, y in zip(xs, ys):
                    series.append(float(x), float(y))
                self.chart.addSeries(series)
                series.attachAxis(x_axis)
                series.attachAxis(y_axis)
                all_x.extend(xs)
                all_y.extend(ys)
        if all_x:
            lo, hi = min(all_x), max(all_x)
            if lo == hi:
                lo, hi = lo * 0.9, hi * 1.1
            x_axis.setRange(float(lo), float(hi))
            lo, hi = min(all_y), max(all_y)
            margin = max((hi - lo) * 0.05, 0.5)
            y_axis.setRange(float(lo - margin), float(hi + margin))
            self.chart.setTitle('Calibration curves')
        else:
            x_axis.setRange(0.1, 8000)
            y_axis.setRange(-1, 1)
            self.chart.setTitle('Select calibrations using Show')
        self.chart.legend().setVisible(bool(all_x))
        self.chart.legend().setAlignment(Qt.AlignmentFlag.AlignBottom)


class VerificationTab(WorkflowTab):
    def __init__(self, parent=None):
        super().__init__('Verification', 'Receiver parameter verification tests will be added here.', parent)
