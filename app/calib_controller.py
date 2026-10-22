"""Synchronous calibration backend; CalibrationTab runs it in a worker thread."""
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import threading
import numpy as np
from calib_cfg import CFG_CALIB_CH1, CFG_CALIB_PRESS, CFG_CALIB_CH2
from calib import CalibrationMeasurement
from ssh_utils import Aborted, check_abort
from project import CALIB_DIR

CFG_CALIB_ALL = {**CFG_CALIB_CH1, **CFG_CALIB_PRESS, **CFG_CALIB_CH2}
OPERATOR = "VHU"


def measured(cm):
    if cm is None or not cm.available or cm.limit_dB is None:
        return False
    fs, values = np.asarray(cm.freq_hz), np.asarray(cm.limit_dB)
    return (fs.ndim == values.ndim == 1 and fs.size > 0 and fs.size == values.size
            and bool(np.all(np.isfinite(fs) & (fs > 0)))
            and bool(np.all(np.diff(fs) > 0)) and bool(np.all(np.isfinite(values))))


class CalibrationController:
    def __init__(self, dev, gen, prj, *, dwell_sec=0.1, operator=OPERATOR,
                 transfer=None, cancel=None, progress=None, completed=None, status=None):
        self.dev, self.gen, self.prj = dev, gen, prj
        self.dwell_sec, self.operator = dwell_sec, operator
        self.transfer = transfer
        self.cancel = cancel if cancel is not None else threading.Event()
        self.progress = progress or (lambda done, total: None)
        self.completed = completed or (lambda name, cm: None)
        self.status = status or (lambda text: None)
        self.done = self.total = 0
        self.calibrations, self.errors = {}, {}
        self.reload()

    def reload(self):
        self.errors.clear()
        for name in CFG_CALIB_ALL:
            try:
                self.calibrations[name] = CalibrationMeasurement.from_file(self.path(name))
            except Exception as exc:
                self.calibrations[name] = CalibrationMeasurement(name=Path(name).stem)
                self.errors[name] = str(exc)

    def path(self, name):
        if name not in CFG_CALIB_ALL:
            raise KeyError(name)
        return self.prj.root / CALIB_DIR / name

    def _advance(self):
        self.done += 1
        self.progress(self.done, self.total)

    def _publish(self, name, cm):
        self.calibrations[name] = cm
        self.completed(name, replace(cm, freq_hz=cm.freq_hz.copy(),
                                     limit_dB=np.asarray(cm.limit_dB).copy()))

    def measure(self, name):
        check_abort(self.cancel)
        fs, commands = CFG_CALIB_ALL[name]
        fs = np.asarray(fs)
        if not all(isinstance(cmd, str) for cmd in commands):
            raise ValueError(f"{name}: configuration commands must be strings.")
        if fs.size == 0 or not np.all(np.isfinite(fs) & (fs > 0)) or not np.all(np.diff(fs) > 0):
            raise ValueError(f"{name}: invalid frequency axis.")
        if self.dwell_sec <= 0:
            raise ValueError("Measurement dwell must be positive.")
        self.status(f"Measuring {name}")
        self.dev._main_scpi_commands(commands)
        for command in ('POW -039.99', 'SOURCE:POWER:OFFSET -005.00', 'OUTP:STAT 1'):
            self.gen.cmd(command)
        limits = []
        for frequency in fs:
            check_abort(self.cancel)
            self.gen.tune(frequency)
            check_abort(self.cancel)
            value = float(self.dev.measure_point_rms(frequency, self.dwell_sec))
            if not np.isfinite(value):
                raise ValueError(f"Non-finite measurement at {frequency} Hz.")
            limits.append(value)
            self._advance()
        check_abort(self.cancel)
        cm = CalibrationMeasurement(name=Path(name).stem, freq_hz=fs.copy(),
             limit_dB=np.asarray(limits), datetime=datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
             operator=self.operator, temperature=self.prj.prop_auto.calibration_temperature)
        self._save(name, cm)
        self._publish(name, cm)

    def _save(self, name, cm):
        target = self.path(name)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + '.tmp')
        try:
            cm.save_to_file(temporary)
            check_abort(self.cancel)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)

    def upload(self, name):
        check_abort(self.cancel)
        cm = CalibrationMeasurement.from_file(self.path(name))
        if not measured(cm):
            raise ValueError(f"{name} has no complete measured data to upload.")
        if self.transfer is None:
            raise ValueError("Configure SSH transfer settings first.")
        self.status(f"Uploading {name}")
        self.transfer.upload(self.path(name))
        self._advance()

    def download(self, name):
        check_abort(self.cancel)
        if self.transfer is None:
            raise ValueError("Configure SSH transfer settings first.")
        target = self.path(name)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + '.download')
        try:
            self.status(f"Downloading {name}")
            self.transfer.download(name, temporary)
            cm = CalibrationMeasurement.from_file(temporary)
            if not measured(cm):
                raise ValueError(f"Downloaded {name} contains no complete measured data.")
            check_abort(self.cancel)
            temporary.replace(target)
            self._publish(name, cm)
            self._advance()
        finally:
            temporary.unlink(missing_ok=True)

    def reset_and_connect(self):
        check_abort(self.cancel)
        self.status("Restarting DUT; waiting for reconnection…")
        self.dev._main_scpi_command('*rst')
        self.dev.close()
        backoff = 10.0
        for attempt in range(10):
            if self.cancel.wait(backoff):
                raise Aborted("Aborted while waiting for DUT restart")
            try:
                if self.dev.open(tdoa_setting=False):
                    self._advance()
                    return
            except Exception:
                self.dev.close()
            self.status(f"Reconnection attempt {attempt + 1}/10 failed")
            backoff = min(backoff * 1.5, 30)
        raise RuntimeError("DUT could not reconnect after restart.")

    def run(self, action, name=None):
        groups = {'ch1': [CFG_CALIB_CH1, CFG_CALIB_PRESS], 'ch2': [CFG_CALIB_CH2]}
        self.done = 0
        if action in groups:
            stages = groups[action]
            self.total = sum(sum(len(fs) for fs, _ in group.values()) + len(group) + 1
                             for group in stages)
        elif action == 'measure':
            self.total = len(CFG_CALIB_ALL[name][0])
        elif action == 'download_all':
            self.total = len(CFG_CALIB_ALL)
        elif action in ('upload', 'download'):
            self.total = 1
        else:
            raise ValueError(f"Unknown calibration action: {action}")
        self.progress(0, self.total)
        if action in groups:
            if self.transfer is None:
                raise ValueError("Configure SSH transfer settings before starting a pipeline.")
            self.transfer.settings.validate()
            for group in stages:
                for key in group:
                    self.measure(key)
                for key in group:
                    self.upload(key)
                self.reset_and_connect()
        elif action == 'download_all':
            for key in CFG_CALIB_ALL:
                self.download(key)
        else:
            getattr(self, action)(name)

    # Preserve the supplied controller's public pipeline entry points.
    def calib_ch1_pipeline(self):
        self.run('ch1')

    calib_ch1_pipieline = calib_ch1_pipeline

    def calib_ch2_pipeline(self):
        self.run('ch2')
