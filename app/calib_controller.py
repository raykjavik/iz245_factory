"""Synchronous calibration backend; CalibrationTab runs it in a worker thread."""
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import threading
import numpy as np
from cfg_common import sweep_bandwidth_hz
from cfg import CFG_CALIB_RF1, CFG_PCALIB, CFG_CALIB_RF2,CFG_TEST1_RF1,CFG_TEST2,CFG_TEST1_RF2,CFG_TEST2_RF2,CFG_TEST3,CFG_TEST4,CFG_NOISE_DENSITY,MEASUREMENT_SPECS
from measurement import SweepMeasurement,NoiseDensityMeasurement,IP3Measurement,IFSpectrumMeasurement
from cfg_test8 import CFG_TEST8
from cfg import CFG_TEST7_RF1, CFG_TEST7_RF2
from measurement_jobs import make_job
from measurement_control import Aborted, check_abort
from ssh_transfer import RemoteFileMissing
from project import CALIB_DIR, TEST_DIR
from run_control import pause_checkpoint
from measurement_handlers import HANDLERS
from measurement_specs import CALIB_POWER, VERIFICATION_POW, NOISE_UNIT

CFG_CALIB_ALL = {**CFG_CALIB_RF1, **CFG_PCALIB, **CFG_CALIB_RF2}
CFG_TEST1_ALL = {**CFG_TEST1_RF1, **CFG_TEST1_RF2}
CFG_NOISE_ALL = {**CFG_TEST2, **CFG_TEST2_RF2, **CFG_TEST3, **CFG_TEST4}
CFG_VERIFICATION_ALL = {**CFG_TEST1_ALL, **CFG_NOISE_ALL}
CFG_VERIFIACATION_ALL = CFG_VERIFICATION_ALL  # compatibility with uploaded spelling
CFG_ALL = {**CFG_CALIB_ALL, **CFG_VERIFICATION_ALL}


def measured(measurement):
    return measurement is not None and measurement.has_data()


class MeasurementController:
    def __init__(self, dev, gen, prj, *, dwell_sec=None, operator=None,
                 calibration_dwell_sec=None, verification_dwell_sec=None, handlers=None,
                 transfer=None, cancel=None, progress=None, completed=None, status=None, warning=None,
                 measurement_started=None, point_measured=None, density_updated=None,
                 pause_event=None, pause_changed=None, ip3_updated=None,
                 measurement_names=None, load_existing=True, spectrum_updated=None):
        self._dev, self.gen, self.prj = dev, gen, prj
        self.handlers = {**HANDLERS, **(handlers or {})}
        settings = prj.settings
        self.calibration_dwell_sec = (calibration_dwell_sec if calibration_dwell_sec is not None
                                      else dwell_sec if dwell_sec is not None else settings.calibration_dwell_sec)
        self.verification_dwell_sec = (verification_dwell_sec if verification_dwell_sec is not None
                                       else dwell_sec if dwell_sec is not None else settings.verification_dwell_sec)
        self.operator = prj.settings.operator if operator is None else operator
        self.transfer = transfer
        self.cancel = cancel if cancel is not None else threading.Event()
        self.progress = progress or (lambda done, total: None)
        self.completed = completed or (lambda name, cm: None)
        self.status = status or (lambda text: None)
        self.warning = warning or self.status
        self.measurement_started = measurement_started or (lambda name: None)
        self.point_measured = point_measured or (lambda name, frequency, value: None)
        self.pause_event = pause_event
        self.pause_changed = pause_changed or (lambda paused: None)
        self.ip3_updated = ip3_updated or (lambda name, result: None)
        self.spectrum_updated = spectrum_updated or (lambda name,result:None)
        self.density_updated=density_updated or (lambda name,result:None)
        self.done = self.total = 0
        self.measurements, self.errors = {}, {}
        self.calibrations = self.measurements  # existing UI compatibility
        self.verifications = {}
        self.measurement_names = tuple(MEASUREMENT_SPECS if measurement_names is None else measurement_names)
        if load_existing:
            self.reload()

    @property
    def dev(self):
        return self._dev

    @property
    def device(self):
        return self.dev

    def connect_dut(self, ip, device_factory):
        """Own the single Device used by all domain procedures."""
        self._checkpoint()
        self._dev = device_factory(ip)
        self._dev.open(tdoa_setting=False)
        check_abort(self.cancel)
        if not self.dev.connected:
            raise ConnectionError('Device could not connect to DUT.')

    def disconnect_dut(self):
        if self.dev is not None:
            self.dev.close()

    def reload(self):
        self.errors.clear()
        for name in self.measurement_names:
            try:
                self.calibrations[name] = MEASUREMENT_SPECS[name].measurement_class.from_file(self.path(name))
            except Exception as exc:
                self.calibrations[name] = MEASUREMENT_SPECS[name].measurement_class(name=Path(name).stem)
                self.errors[name] = str(exc)
        self.verifications = {name:value for name,value in self.measurements.items()
                              if MEASUREMENT_SPECS[name].storage==TEST_DIR}

    def path(self, name):
        return self.prj.root / MEASUREMENT_SPECS[name].storage / name

    def _checkpoint(self):
        return pause_checkpoint(self.cancel, self.pause_event, self.pause_changed)

    def _advance(self):
        self.done += 1
        self.progress(self.done, self.total)

    def _publish(self, name, cm):
        self.measurements[name] = cm
        self.errors.pop(name, None)
        if MEASUREMENT_SPECS[name].storage == TEST_DIR:
            self.verifications[name] = cm
        self.completed(name, cm.snapshot())

    def spec_for(self, name):
        spec = MEASUREMENT_SPECS[name]
        if spec.kind=='if_spectrum':
            return replace(spec,ffts=spec.work_units_for(self.prj.settings))
        setting = getattr(spec, 'power_setting', None)
        return replace(spec, power_dbm=getattr(self.prj.settings, setting)) if setting else spec

    def register_handler(self, kind, handler):
        self.handlers[kind] = handler

    def record_point(self, name, frequency, value):
        self.point_measured(name, float(frequency), float(value))
        self._advance()

    def measure(self, name):
        self._checkpoint()
        spec = self.spec_for(name)
        dwell = (self.calibration_dwell_sec if spec.storage == CALIB_DIR
                 else self.verification_dwell_sec)
        self.measurement_started(name)
        self.status(f'Measuring {name}')
        # Each domain function owns its setup and procedure.
        if spec.kind == 'spectrum':
            # Retain setup for the existing custom spectrum-handler extension.
            self.dev._main_scpi_commands(list(spec.commands))
        result = self.handlers[spec.kind](self, name, spec, dwell)
        self._checkpoint()
        cm = result if isinstance(result, (SweepMeasurement,NoiseDensityMeasurement,IP3Measurement,IFSpectrumMeasurement)) else SweepMeasurement(
            name=Path(name).stem, freq_hz=np.asarray(spec.frequencies).copy(),
            limit_dB=np.asarray(result), datetime=datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
            operator=self.operator, temperature=self.prj.prop_auto.calibration_temperature,
            unit=spec.unit,
            reference_dbm=spec.power_dbm,dwell_sec=dwell,
            bandwidth_hz=sweep_bandwidth_hz(spec.commands))
        self.status(f'Saving {name}')
        self._save(name, cm)
        self._publish(name, cm)

    def wait(self, seconds):
        if self.cancel.wait(seconds):
            raise Aborted('Aborted during measurement settling')
        check_abort(self.cancel)

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
        if name not in CFG_CALIB_ALL:
            raise ValueError('Verification results are local report data and cannot be uploaded.')
        self._checkpoint()
        cm = SweepMeasurement.from_file(self.path(name))
        if not measured(cm):
            raise ValueError(f"{name} has no complete measured data to upload.")
        if self.transfer is None:
            raise ValueError("Configure SSH transfer settings first.")
        self.status(f"Uploading {name}")
        self.transfer.upload(self.path(name))
        self._advance()

    def download(self, name):
        if name not in CFG_CALIB_ALL:
            raise ValueError('Verification results are measured locally, not downloaded.')
        check_abort(self.cancel)
        if self.transfer is None:
            raise ValueError("Configure SSH transfer settings first.")
        target = self.path(name)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + '.download')
        try:
            self.status(f"Downloading {name}")
            self.transfer.download(name, temporary)
            cm = SweepMeasurement.from_file(temporary)
            if not measured(cm):
                raise ValueError(f"Downloaded {name} contains no complete measured data.")
            check_abort(self.cancel)
            temporary.replace(target)
            self._publish(name, cm)
            self._advance()
        finally:
            temporary.unlink(missing_ok=True)

    def reset_and_connect(self):
        self._checkpoint()
        self.status("Restarting DUT; waiting for reconnection…")
        self.dev._main_scpi_command('*rst')
        self.dev.close()
        backoff = 10.0
        for attempt in range(10):
            if self.cancel.wait(backoff):
                raise Aborted("Aborted while waiting for DUT restart")
            try:
                self.dev.open(tdoa_setting=False)
                connected = self.dev.connected
                if connected:
                    self._checkpoint()
                    self._advance()
                    return
            except Aborted:
                raise
            except Exception:
                self.dev.close()
            self.status(f"Reconnection attempt {attempt + 1}/10 failed")
            backoff = min(backoff * 1.5, 30)
        raise RuntimeError("DUT could not reconnect after restart.")

    def measure_group(self,group):
        for name in group:
            self.measure(name)

    def upload_group(self,group):
        for name in group:
            self.upload(name)

    def calibrate_group(self,group):
        self.measure_group(group)
        self.upload_group(group)
        self.reset_and_connect()

    def measure_calibrations_rf1(self,_name=None):
        self.measure_group(CFG_CALIB_RF1)

    def measure_calibrations_rf2(self,_name=None):
        self.measure_group(CFG_CALIB_RF2)

    def measure_preselectors(self,_name=None):
        self.measure_group(CFG_PCALIB)

    def run_rf1_pipeline(self,_name=None):
        self.calibrate_group(CFG_CALIB_RF1)
        self.calibrate_group(CFG_PCALIB)
        self.run_test1_rf1()
        self.run_noise_density()

    def run_rf2_pipeline(self,_name=None):
        self.calibrate_group(CFG_CALIB_RF2)
        self.run_test1_rf2()

    def run_test1_rf1(self,_name=None):
        self.measure_group(CFG_TEST1_RF1)

    def run_test1_rf2(self,_name=None):
        self.measure_group(CFG_TEST1_RF2)

    def run_noise_rf1(self,_name=None):
        self.measure_group(CFG_TEST2)

    def run_noise_rf2(self,_name=None):
        self.measure_group(CFG_TEST2_RF2)

    def run_test3_rf1(self,_name=None):
        self.measure_group(CFG_TEST3)

    def run_test4(self,_name=None):
        self.measure_group(CFG_TEST4)

    def run_noise_density(self,_name=None):
        self.measure_group(CFG_NOISE_DENSITY)

    def run_test8(self, _name=None):
        self.measure_group(CFG_TEST8)

    def run_test7_rf1(self, _name=None):
        self.measure_group(CFG_TEST7_RF1)

    def run_test7_rf2(self, _name=None):
        self.measure_group(CFG_TEST7_RF2)

    def run_download_all(self,_name=None):
        for name in CFG_CALIB_ALL:
            try:
                self.download(name)
            except RemoteFileMissing as exc:
                self.warning(str(exc)+' — skipped; existing local data kept.')
                self._advance()

    def run(self,action,name=None):
        job=make_job(action,name)
        self.done=0
        self.total=job.fixed_work+sum(MEASUREMENT_SPECS[key].work_units_for(self.prj.settings)
                                     for key in job.names)
        self.progress(0,self.total)
        if job.needs_transfer:
            if self.transfer is None:
                raise ValueError('Configure SSH transfer settings before calibration transfers.')
            self.transfer.settings.validate()
        job.execute(self)

    def calib_ch1_pipeline(self):
        self.run('ch1')

    calib_ch1_pipieline=calib_ch1_pipeline

    def calib_ch2_pipeline(self):
        self.run('ch2')


CalibrationController = MeasurementController
