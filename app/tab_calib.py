"""Calibration controls, threaded hardware work, and frequency plots."""

import cfg_test2
import cfg_test3
from pathlib import Path
from dataclasses import replace
import logging
from datetime import datetime, timezone
import threading
import numpy as np
from PySide6.QtCore import Qt, QThread, Signal, QSignalBlocker
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QCheckBox, QHeaderView, QSplitter,
    QProgressBar, QMessageBox, QLineEdit, QFileDialog, QPlainTextEdit)
from helpers import set_led_ok
from measurement import SweepMeasurement
from verification import evaluate_verification
from sweep_chart import SweepChart, Trace
from reference_data_provider import load_reference
from calib_controller import (MeasurementController as CalibrationController,
    CFG_CALIB_ALL, CFG_TEST1_ALL, CFG_NOISE_ALL, measured, MEASUREMENT_SPECS)
from measurement_jobs import make_job
from cfg import CFG_NOISE_DENSITY, CFG_TEST7_RF1, CFG_TEST7_RF2
from cfg_test8 import CFG_TEST8
from ssh_transfer import TransferSettings, SSHTransfer
from measurement_control import Aborted, check_abort
from controller import default_device_factory
from generator_connection import default_generator_factory
from ip3_measurement import default_ip3_generator_factory
import connection_cfg as connections


class _CalibrationThread(QThread):
    progress = Signal(int, int)
    completed = Signal(str, object)
    measurement_started = Signal(str)
    point_measured = Signal(str, float, float)
    density_updated = Signal(str, object)
    spectrum_updated = Signal(str, object)
    ip3_updated = Signal(str, object)
    pause_changed = Signal(bool)
    status = Signal(str)
    warning = Signal(str)

    def __init__(self, project, action, name, options, generator_factory, parent=None, *, device_factory=None, ip3_generator_factory=None):
        super().__init__(parent)
        self.project, self.action, self.name = project, action, name
        self.options = options
        self.job=make_job(action,name)
        self.action=self.job.action
        self.name=self.job.single_name
        self.device_factory=device_factory or default_device_factory
        self.ip3_generator_factory=ip3_generator_factory
        self.generator_factory = generator_factory
        self.backend = None
        self.cancel = threading.Event()
        self.pause_event = threading.Event()
        self.error, self.aborted = None, False
        self.warnings = []

    def run(self):
        gen = backend = None
        try:
            check_abort(self.cancel)
            options = self.options
            job = self.job
            transfer = None
            if job.needs_transfer:
                options['transfer'].validate()
                transfer = SSHTransfer(options['transfer'], self.cancel)
            backend = CalibrationController(None, None, self.project,
                calibration_dwell_sec=options['calibration_dwell'],
                verification_dwell_sec=options['verification_dwell'],
                operator=options['operator'], transfer=transfer,
                cancel=self.cancel, progress=self.progress.emit,
                completed=self.completed.emit, status=self.status.emit, warning=self._warn,
                measurement_started=self.measurement_started.emit, point_measured=self.point_measured.emit, density_updated=self.density_updated.emit,
                ip3_updated=self.ip3_updated.emit, spectrum_updated=self.spectrum_updated.emit,
                pause_event=self.pause_event, pause_changed=self.pause_changed.emit,
                load_existing=False)
            self.backend = backend
            check_abort(self.cancel)
            if job.needs_generator:
                factory = self.generator_factory
                ip, port = options['generator_ip'], options['generator_port']
                if job.generator_role == 'ip3':
                    factory = self.ip3_generator_factory or default_ip3_generator_factory
                    ip, port = self.project.settings.ip3_generator_ip, self.project.settings.ip3_generator_port
                    if not ip:
                        raise ValueError('Set the Test7 two-tone generator IP in Settings.')
                gen = factory(ip, port)
                backend.gen = gen
                if options['cable_calib_path'] is not None:
                    self.status.emit('Loading cable calibration…')
                    gen.load_calibration(options['cable_calib_path'])
                    for name in job.names:
                        for frequency in MEASUREMENT_SPECS[name].generator_frequencies:
                            gen.get_cable_offset(float(frequency))
            if job.needs_dut:
                check_abort(self.cancel)
                self.status.emit('Connecting DUT…')
                backend.connect_dut(options['dut_ip'], self.device_factory)
            check_abort(self.cancel)
            if gen is not None:
                self.status.emit('Connecting signal generator…')
            if gen is not None and not gen.open(tdoa_setting=False):
                check_abort(self.cancel)
                raise ConnectionError('Could not connect to signal generator.')
            check_abort(self.cancel)
            if gen is not None and job.generator_role == 'ip3':
                gen.cmds(['OUTP1:STAT 0','OUTP2:STAT 0'])
                gen.opc()
            backend.run(job)
        except Aborted:
            self.aborted = True
        except Exception as exc:
            if self.cancel.is_set():
                self.aborted = True
            else:
                self.error = str(exc) or type(exc).__name__
        finally:
            cleanup_errors = []
            if gen is not None:
                self.status.emit('Stopping generator output and disconnecting…')
                try:
                    if gen.connected:
                        if self.job.generator_role=='ip3':
                            gen.cmds(['OUTP1:STAT 0','OUTP2:STAT 0'])
                        else:
                            gen.cmd('OUTP:STAT 0')
                except Exception as exc:
                    cleanup_errors.append(f"Cannot turn generator output off: {exc}")
                try:
                    gen.close()
                except Exception as exc:
                    cleanup_errors.append(f"Cannot close generator: {exc}")
            if backend is not None and backend.device is not None:
                self.status.emit('Disconnecting DUT…')
                try:
                    backend.disconnect_dut()
                except Exception as exc:
                    cleanup_errors.append(f"Cannot close DUT: {exc}")
            if cleanup_errors:
                self.error = '; '.join(([self.error] if self.error else []) + cleanup_errors)

    def _warn(self, text):
        self.warnings.append(text)
        self.warning.emit(text)


class CalibrationTab(QWidget):
    changed = Signal()
    validity_changed = Signal(bool)
    busy_changed = Signal(bool)
    message = Signal(str)
    control_state_changed = Signal()
    run_finished = Signal()
    measurement_completed = Signal(str, object)
    measurement_started = Signal(str)
    point_measured = Signal(str, float, float)
    density_updated = Signal(str, object)
    spectrum_updated = Signal(str, object)
    ip3_updated = Signal(str, object)

    def __init__(self, parent=None, generator_factory=None, mode='calibration', verification_check=None, device_factory=None, ip3_generator_factory=None):
        super().__init__(parent)
        self.mode = mode
        self.verification_check = verification_check or evaluate_verification
        self.configs = {'calibration': CFG_CALIB_ALL, 'test1': CFG_TEST1_ALL,
                        'noise': CFG_NOISE_ALL, 'density': CFG_NOISE_DENSITY,
                        'ip3': {**CFG_TEST7_RF1, **CFG_TEST7_RF2}, 'if_spectrum': CFG_TEST8}[mode]
        self.project = self.backend = self._thread = None
        self._external_busy = False
        self.device_factory = device_factory or default_device_factory
        self.generator_factory = generator_factory or default_generator_factory
        self.ip3_generator_factory = ip3_generator_factory
        self.rows = {}
        self._live_name = None
        self._live_points = []
        self._show_live = True
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        self.ch1 = QPushButton('Measure RF1 calibrations' if mode == 'calibration' else
                                 'Run Test1 RF1' if mode == 'test1' else
                                 'Run Test5/6 · all carriers' if mode == 'density' else
                                 'Run Test7 RF1' if mode == 'ip3' else
                                 'Run Test8 · all IF filters' if mode == 'if_spectrum' else 'Run RF1 · Test2 + Test3')
        self.ch2 = QPushButton('Measure RF2 calibrations' if mode == 'calibration' else
                                 'Run Test1 RF2' if mode == 'test1' else
                                 'Run Test7 RF2' if mode == 'ip3' else 'Run RF2 · Test2')
        self.preselectors=QPushButton('Measure preselector calibrations')
        self.preselectors.setVisible(mode=='calibration')
        self.preselectors.clicked.connect(lambda:self.start('measure_preselectors'))
        self.download_all = QPushButton('Download All')
        self.upload_all = QPushButton('Upload all calibrations')
        self.test4 = QPushButton('Run Test4 · internal source')
        self.test4.setVisible(mode == 'noise')
        for button in (self.ch1, self.preselectors, self.ch2, self.upload_all, self.download_all, self.test4):
            top.addWidget(button)
        top.addStretch()
        self.show_all_button = QPushButton('Show all')
        self.hide_all_button = QPushButton('Hide all')
        self.show_all_button.clicked.connect(lambda:self._set_all_shown(True))
        self.hide_all_button.clicked.connect(lambda:self._set_all_shown(False))
        top.addWidget(self.show_all_button)
        top.addWidget(self.hide_all_button)
        layout.addLayout(top)
        self.ch1.clicked.connect(lambda: self.start(
            {'calibration': 'measure_calibrations_rf1', 'test1': 'test1_rf1', 'noise': 'noise_rf1', 'density':'noise_density', 'ip3':'test7_rf1','if_spectrum':'test8'}[self.mode]))
        self.ch2.setVisible(mode not in ('density','if_spectrum'))
        self.ch2.clicked.connect(lambda: self.start(
            {'calibration': 'measure_calibrations_rf2', 'test1': 'test1_rf2', 'noise': 'noise_rf2', 'density':'noise_density', 'ip3':'test7_rf2','if_spectrum':'test8'}[self.mode]))
        self.download_all.setVisible(mode == 'calibration')
        self.upload_all.setVisible(mode == 'calibration')
        self.upload_all.clicked.connect(lambda:self.start('upload_all'))
        self.download_all.clicked.connect(lambda: self.start('download_all'))
        self.test4.clicked.connect(lambda: self.start('test4'))
        self.cable_status = QLabel()
        self.cable_status.setWordWrap(True)
        self.cable_status.setVisible(mode not in ('noise','if_spectrum'))
        layout.addWidget(self.cable_status)
        self.location = QLabel('No project loaded.')
        layout.addWidget(self.location)
        self.connection_hint=QLabel(
            'Connect the generator to the selected RF input. Each RF pipeline stops before a cable switch.'
            if mode != 'noise' else
            'Connect the termination resistor to the selected RF input. No generator commands are sent.')
        self.connection_hint.setWordWrap(True)
        layout.addWidget(self.connection_hint)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.columns = (['Name', 'Available', 'Date', 'Time (local)', 'Operator',
                         'Upload', 'Measure', 'Download', 'Show'] if mode == 'calibration' else
                        ['Name', 'Result', 'Date', 'Time (local)', 'Operator', 'Measure', 'Show'])
        self.table = QTableWidget(0, len(self.columns))
        self.table.setHorizontalHeaderLabels(self.columns)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(36)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, len(self.columns)):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        splitter.addWidget(self.table)
        self.sweep_chart = SweepChart()
        self.plot_splitter=splitter
        splitter.addWidget(self.sweep_chart)
        self.live_readout = self.sweep_chart.hover_label
        splitter.setSizes([680, 650])
        layout.addWidget(splitter, 1)
        self.status = QLabel('Open a project to begin.')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.warning_log = QPlainTextEdit()
        self.warning_log.setReadOnly(True)
        self.warning_log.setMaximumHeight(100)
        self.warning_log.setAccessibleName('Measurement warnings')
        self.warning_log.setStyleSheet('color: #9a5b00')
        self.warning_log.hide()
        layout.addWidget(self.warning_log)
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

    def _set_all_shown(self, shown):
        self._show_live = shown
        for row in self.rows.values():
            checkbox = row['show']
            with QSignalBlocker(checkbox):
                checkbox.setChecked(bool(shown and checkbox.isEnabled()))
        self.redraw()

    def load_project(self, project):
        if self.busy:
            raise RuntimeError('Cannot change project during calibration.')
        self.project = project
        self._show_live = True
        self._clear_live()
        self.warning_log.clear()
        self.warning_log.hide()
        self.backend = CalibrationController(None, None, project, measurement_names=self.configs)
        self.reload_cable_calibration()
        self.location.setText(f'Project folder: {project.root} | DUT: {project.prop_auto.dut_ip}')
        self.table.setRowCount(len(self.configs))
        self.rows.clear()
        for row, name in enumerate(self.configs):
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
            date_item, time_item = QTableWidgetItem('—'), QTableWidgetItem('—')
            for column, stamp_item in ((2, date_item), (3, time_item)):
                stamp_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                stamp_item.setToolTip('Measurement timestamp converted from UTC to local time.')
                self.table.setItem(row, column, stamp_item)
            operator_item = QTableWidgetItem('—')
            self.table.setItem(row, 4, operator_item)
            buttons = {}
            actions = ('upload', 'measure', 'download') if self.mode == 'calibration' else ('measure',)
            for column, action in enumerate(actions, 5):
                button = QPushButton(action.capitalize())
                button.clicked.connect(lambda checked=False, action=action, name=name: self.start(action, name))
                self.table.setCellWidget(row, column, button)
                buttons[action] = button
            show = QCheckBox()
            show.toggled.connect(self.redraw)
            self.table.setCellWidget(row, len(self.columns) - 1, show)
            self.rows[name] = {'led': led, 'show': show, 'date': date_item, 'time': time_item,
                               'operator': operator_item, **buttons}
        self.progress.setValue(0)
        if self.backend.errors:
            self._set_status('Some files could not be read; hover their indicators for details.')
        else:
            self._set_status('Ready. Connect the termination resistor to the selected RF input.' if self.mode == 'noise'
                             else 'Ready. Connect the generator to RF1 or RF2 before measuring.')
        self._refresh()

    def reload_cable_calibration(self):
        self.project.load_cable_calibration()
        self.setup_changed()

    def setup_changed(self):
        if self.project is None:
            return
        settings=self.project.settings
        self.location.setText(f'Project folder: {self.project.root} | DUT: {settings.dut_ip}')
        if self.project.cable_calib_error:
            self.cable_status.setText('Cable calibration unavailable: '+self.project.cable_calib_error)
        else:
            cable='frequency-dependent cable table' if self.project.cable_calib is not None else 'no cable correction'
            self.cable_status.setText(f'Setup in Settings: {settings.attenuator_db:g} dB static compensation; {cable}.')
        self._update_enabled()

    def _refresh(self):
        results = []
        for name, row in self.rows.items():
            cm = self.backend.calibrations[name]
            date_text = time_text = '—'
            if cm.datetime:
                try:
                    stamp = datetime.fromisoformat(cm.datetime)
                    if stamp.tzinfo is None:
                        stamp = stamp.replace(tzinfo=timezone.utc)
                    stamp = stamp.astimezone()
                    date_text, time_text = stamp.strftime('%Y-%m-%d'), stamp.strftime('%H:%M:%S')
                except (ValueError, TypeError):
                    pass
            row['date'].setText(date_text)
            row['time'].setText(time_text)
            row['operator'].setText(cm.operator or '—')
            if self.mode == 'calibration':
                ok = self.backend.path(name).is_file()
                explanation = 'Calibration file exists locally' if ok else 'Calibration file missing'
            else:
                result, explanation = self._row_verification_result(name,cm)
                ok = result is True
            results.append(ok)
            set_led_ok(row['led'], ok)
            row['led'].setToolTip(self.backend.errors.get(name) or explanation)
            if not measured(cm):
                row['show'].setChecked(False)
        self._update_enabled()
        self.validity_changed.emit(bool(results) and all(results))
        self.redraw()

    def _verification_result(self, measurement):
        if not measured(measurement):
            return None, 'No complete measured data to evaluate'
        try:
            result = self.verification_check(measurement)
            if result is None:
                return None, 'Not evaluated: acceptance criteria are not configured'
            passed = bool(result)
            return passed, 'Verification passed' if passed else 'Verification failed'
        except Exception as exc:
            return False, f'Verification evaluation failed: {exc}'

    def _row_verification_result(self, name, measurement):
        return self._verification_result(measurement)

    def _update_enabled(self):
        enabled = self.project is not None and not self.busy and not self._external_busy
        self.show_all_button.setEnabled(self.project is not None)
        self.hide_all_button.setEnabled(self.project is not None)
        measure_enabled = enabled and (self.mode in ('noise','if_spectrum') or not getattr(self.project, 'cable_calib_error', ''))
        self.ch1.setEnabled(bool(measure_enabled))
        self.ch2.setEnabled(bool(measure_enabled))
        self.preselectors.setEnabled(bool(measure_enabled))
        self.download_all.setEnabled(enabled)
        self.upload_all.setEnabled(enabled and self.mode == 'calibration' and
            any(measured(value) for value in self.backend.measurements.values()))
        self.test4.setEnabled(enabled)
        self.control_state_changed.emit()
        for name, row in self.rows.items():
            available = measured(self.backend.calibrations[name])
            if 'upload' in row:
                row['upload'].setEnabled(enabled and available)
            row['measure'].setEnabled(bool(measure_enabled))
            if 'download' in row:
                row['download'].setEnabled(enabled)
            row['show'].setEnabled(available)

    def _options(self):
        settings = self.project.settings
        dut_ip = settings.dut_ip.strip()
        transfer = TransferSettings(host=dut_ip, username=connections.SSH_USERNAME,
            remote_dir=connections.SSH_REMOTE_CALIB_DIR,
            key_path=str(connections.SSH_KEY_PATH),
            ssh=connections.SSH_EXECUTABLE, port=connections.SSH_PORT,
            timeout=connections.SSH_TRANSFER_TIMEOUT_SEC,
            auto_accept_new_host=connections.SSH_AUTO_ACCEPT_NEW_HOST)
        return dict(dut_ip=dut_ip, generator_ip=settings.generator_ip,
                    generator_port=settings.generator_port,
                    operator=settings.operator, calibration_dwell=settings.calibration_dwell_sec,
                    verification_dwell=settings.verification_dwell_sec, transfer=transfer,
                    cable_calib_path=Path(settings.cable_calib_path) if settings.cable_calib_path else None)

    def start(self, action, name=None):
        if self.busy or self._external_busy or self.project is None:
            return
        job = make_job(action,name)
        if job.needs_generator:
            self.reload_cable_calibration()
            if self.project.cable_calib_error:
                QMessageBox.warning(self, 'Cable calibration unavailable', self.project.cable_calib_error)
                return
        options = self._options()
        try:
            if job.needs_transfer:
                options['transfer'].validate()
            generator_ip = (self.project.settings.ip3_generator_ip if job.generator_role == 'ip3'
                            else options['generator_ip'])
            if job.needs_generator and not generator_ip:
                raise ValueError('Set the Test7 generator IP in Settings.' if job.generator_role == 'ip3'
                                 else 'Set the generator IP in Settings.')
        except Exception as exc:
            QMessageBox.warning(self, 'Measurement settings', str(exc))
            return
        self._thread = _CalibrationThread(self.project, action, name, options,
            self.generator_factory, self, device_factory=self.device_factory,
            ip3_generator_factory=self.ip3_generator_factory)
        self._thread.progress.connect(self._on_progress)
        self._thread.completed.connect(self._on_completed)
        self._thread.completed.connect(self.measurement_completed.emit)
        self._thread.measurement_started.connect(self.measurement_started.emit)
        self._thread.point_measured.connect(self.point_measured.emit)
        self._thread.spectrum_updated.connect(self._on_spectrum_updated)
        self._thread.spectrum_updated.connect(self.spectrum_updated.emit)
        self._thread.ip3_updated.connect(self._on_ip3_updated)
        self._thread.ip3_updated.connect(self.ip3_updated.emit)
        self._thread.density_updated.connect(self._on_density_updated)
        self._thread.density_updated.connect(self.density_updated.emit)
        self._thread.measurement_started.connect(self._on_measurement_started)
        self._thread.point_measured.connect(self._on_point_measured)
        self._thread.pause_changed.connect(self._on_pause_changed)
        self._thread.status.connect(self._set_status)
        self._thread.warning.connect(self._on_warning)
        self.warning_log.clear()
        self.warning_log.hide()
        self._thread.finished.connect(self._finished)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self._clear_live()
        self._set_status('Starting…')
        self._update_enabled()
        self.busy_changed.emit(True)
        self._thread.start()

    def pause_measurement(self):
        if self.busy and not self._thread.cancel.is_set():
            self._thread.pause_event.set()
            self._update_enabled()
            self._set_status('Pause requested; waiting for the current point or operation to finish…')

    def resume_measurement(self):
        if self.busy and not self._thread.cancel.is_set():
            self._thread.pause_event.clear()
            self._update_enabled()
            self._set_status('Resuming calibration…')

    def _on_pause_changed(self, paused):
        if not self.busy or self._thread.cancel.is_set():
            return
        self._update_enabled()
        if paused and self._thread.pause_event.is_set():
            self._set_status('Paused. Resume to continue, or Abort to stop.')
        elif not self._thread.pause_event.is_set():
            self._set_status('Resuming calibration…')

    def abort_measurement(self):
        if self._thread:
            self._thread.cancel.set()
            self._thread.pause_event.clear()
            self._update_enabled()
            self._set_status('Aborting… waiting for the current device call to finish.')

    def _on_progress(self, done, total):
        self.progress.setRange(0, total)
        self.progress.setValue(done)
        self.progress.setFormat('%p% — %v / %m work units')

    def _on_completed(self, name, cm):
        if name not in self.rows:
            return
        self.backend.calibrations[name] = cm
        self.backend.errors.pop(name, None)
        if self._live_name == name:
            self._clear_live()
        self._refresh()

    def _clear_live(self):
        self._live_name = None
        self._live_points = []
        self.live_readout.clear()

    def _on_measurement_started(self, name):
        if name not in self.rows:
            return
        self._live_name = name
        self._live_points = []
        self.live_readout.setText(f'Current: {name} — waiting for first point…')
        self.redraw()

    def _on_spectrum_updated(self, name, result):
        pass  # handled by IFSpectrumTab

    def _on_ip3_updated(self, name, result):
        pass  # handled by IP3Tab

    def _on_density_updated(self,name,result):
        pass  # handled by NoiseDensityTab; sweep pages ignore paired spectra

    def _on_point_measured(self, name, frequency_hz, value):
        if name != self._live_name:
            return
        self._live_points.append((frequency_hz, value))
        self.redraw()

    def _on_warning(self, text):
        self.warning_log.appendPlainText('Warning: ' + text)
        self.warning_log.show()
        self.message.emit('Warning: ' + text)

    def _set_status(self, text):
        self.status.setText(text)
        self.message.emit(text)

    def _finished(self):
        thread = self._thread
        self._thread = None
        self._clear_live()
        # Completed results were delivered by the worker's completed signals.
        # Do not reread potentially million-row spectra after every abort/run.
        self._refresh()
        self.busy_changed.emit(False)
        if thread.error:
            self._set_status(f'Failed: {thread.error}')
            QMessageBox.critical(self, 'Measurement failed', thread.error)
        elif thread.aborted:
            self._set_status('Aborted. Completed measurements have been kept.')
        elif thread.warnings:
            self._set_status(f'Completed with warnings: {len(thread.warnings)} missing file(s) skipped.')
            self.progress.setValue(self.progress.maximum())
        else:
            self._set_status('Completed. Measurement connections closed.')
            self.progress.setValue(self.progress.maximum())
        thread.deleteLater()
        self.run_finished.emit()

    def refresh_external_results(self):
        if self.backend is not None:
            self._clear_live()
            self.backend.reload()
            self._refresh()

    def finish_external_run(self):
        """Results have already arrived through measurement_completed signals."""
        if self.backend is not None:
            self._clear_live()
            self._refresh()

    def _curve_passed(self,name,measurement):
        if self.mode == 'calibration':
            return self.backend.path(name).is_file()
        return self._row_verification_result(name,measurement)[0]

    def _live_measurement(self,name,points,spec):
        return SweepMeasurement(name=Path(name).stem,freq_hz=points[:,0],limit_dB=points[:,1],
            unit=spec.unit,reference_dbm=spec.power_dbm,available=True,
            quantity='noise_density' if spec.kind == 'test2' else '')

    def _add_trace_with_reference(self, traces, label, trace, name, measurement_class, build_reference):
        """Add one project/live curve and at most one GUI-only reference overlay."""
        trace.color_key = name
        traces[label] = trace
        if any(item.is_reference and item.color_key == name for item in traces.values()):
            return
        reference = load_reference(name, measurement_class, calibration=self.mode == 'calibration')
        if reference is None:
            return
        try:
            overlay = build_reference(reference)
        except (ValueError, TypeError) as exc:
            logging.getLogger(__name__).warning('Cannot plot optional reference %s: %s', name, exc)
            return
        if overlay is not None:
            label = label.removeprefix('Current: ').replace(' (live)', '') + ' (reference)'
            traces[label] = replace(overlay, live=False, is_reference=True, color_key=name,
                                    color=trace.color, passed=None)

    def _sweep_reference(self, reference, spec):
        if spec.kind == 'test2':
            return Trace(np.asarray(reference.freq_hz),cfg_test2.noise_figure_density(reference),'dB/Hz',None,
                display_unit=cfg_test2.DISPLAY_UNIT,display_offset_db=0.)
        if spec.kind == 'test3':
            return Trace(np.asarray(reference.freq_hz),cfg_test3.absolute_dbm(reference),'dBm',reference.reference_dbm,
                display_unit=cfg_test3.DISPLAY_UNIT,display_offset_db=cfg_test3.DISPLAY_OFFSET_DB)
        return Trace(np.asarray(reference.freq_hz), np.asarray(reference.limit_dB), reference.unit,
            reference.reference_dbm, display_unit=spec.display_unit, display_offset_db=spec.display_offset_db)

    def _sweep_traces(self):
        traces = {}
        if self.backend:
            for name,row in self.rows.items():
                cm = self.backend.measurements[name]
                if not row['show'].isChecked() or not measured(cm):
                    continue
                reference = cm.reference_dbm
                if reference is None:
                    reference = self.backend.spec_for(name).power_dbm
                spec=self.backend.spec_for(name)
                try:
                    trace = self._sweep_reference(cm,spec)
                except ValueError as exc:
                    logging.getLogger(__name__).warning('Cannot plot %s: %s',name,exc)
                    continue
                trace.passed=self._curve_passed(name,cm)
                trace.reference_dbm=reference
                self._add_trace_with_reference(traces,name,trace,name,SweepMeasurement,
                    lambda ref:self._sweep_reference(ref,spec))
        if self._show_live and self._live_name and self._live_points:
            spec = self.backend.spec_for(self._live_name)
            points = np.asarray(self._live_points)
            trace = Trace(points[:,0],points[:,1],spec.unit,
                spec.power_dbm,live=True,display_unit=spec.display_unit,display_offset_db=spec.display_offset_db,
                passed=self._curve_passed(self._live_name,self._live_measurement(self._live_name,points,spec)))
            self._add_trace_with_reference(traces,'Current: '+self._live_name,trace,self._live_name,
                SweepMeasurement,lambda ref:self._sweep_reference(ref,spec))
        return traces

    def redraw(self, *_):
        self.sweep_chart.set_traces(self._sweep_traces())
