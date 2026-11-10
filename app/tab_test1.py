"""Test1 calibration verification tab."""

import cfg_test1 as test1
import numpy as np
from tab_calib import CalibrationTab
from calib_controller import measured
from measurement import SweepMeasurement
from sweep_chart import Trace


class CalibrationVerificationTab(CalibrationTab):
    """Test1 absolute-level chart; detailed result matrices are report-only."""
    def __init__(self, parent=None, generator_factory=None, verification_check=None, device_factory=None, ip3_generator_factory=None):
        super().__init__(parent, generator_factory, verification_check=verification_check, device_factory=device_factory, mode='test1')
        self.sweep_chart.display_unit = test1.DISPLAY_UNIT
        self.sweep_chart.display_offset_db = test1.DISPLAY_OFFSET_DB
        self.sweep_chart.value_label = 'RMS received level'
        self.sweep_chart.title = 'Test1 calibration verification'
        self.sweep_chart.scale.setCurrentText('Log' if test1.CHART_LOG_X else 'Linear')
        self.sweep_chart.scale.hide()  # Axis convention is shared with the protocol.
        self.redraw()

    def setup_changed(self):
        super().setup_changed()
        self.redraw()

    def _on_completed(self,name,result):
        super()._on_completed(name,result)
        if name in self.rows:
            self.rows[name]['show'].setChecked(self._show_live)

    def redraw(self,*_):
        traces, references = {}, set()
        def reference_trace(measurement):
            return Trace(np.asarray(measurement.freq_hz),test1.absolute_dbm(measurement),'dBm',
                measurement.reference_dbm,display_unit=test1.DISPLAY_UNIT,display_offset_db=test1.DISPLAY_OFFSET_DB)
        if self.backend:
            for name,row in self.rows.items():
                measurement = self.backend.measurements[name]
                if not row['show'].isChecked() or not measured(measurement):
                    continue
                try:
                    values = test1.absolute_dbm(measurement)
                except ValueError:
                    continue
                label = test1.configuration_label(name).replace('\n', ', ')+(' · RF1' if '_RF1_' in name else ' · RF2')
                trace = Trace(
                    np.asarray(measurement.freq_hz),values,'dBm',measurement.reference_dbm,
                    display_unit=test1.DISPLAY_UNIT,display_offset_db=test1.DISPLAY_OFFSET_DB,
                    passed=self._curve_passed(name,measurement))
                self._add_trace_with_reference(traces,label,trace,name,SweepMeasurement,reference_trace)
                if measurement.reference_dbm is not None:
                    references.add(measurement.reference_dbm)
            if self._show_live and self._live_name and self._live_points:
                points = np.asarray(self._live_points)
                reference = self.backend.spec_for(self._live_name).power_dbm
                references.add(reference)
                label = 'Current: '+test1.configuration_label(self._live_name).replace('\n', ', ')
                trace = Trace(
                    points[:,0],points[:,1],'dBm',reference,live=True,
                    display_unit=test1.DISPLAY_UNIT,display_offset_db=test1.DISPLAY_OFFSET_DB,
                    passed=self._curve_passed(self._live_name,self._live_measurement(
                        self._live_name,points,self.backend.spec_for(self._live_name))))
                self._add_trace_with_reference(traces,label,trace,self._live_name,SweepMeasurement,reference_trace)
            if not references and self.project is not None:
                references.add(self.project.settings.verification_power_dbm)
        self.sweep_chart.set_traces(traces)
        limits = []
        for reference in sorted(references):
            for label,bound in zip(('Lower','Upper'),test1.limits_dbm(reference)):
                value = bound+test1.DISPLAY_OFFSET_DB
                limits.append((f'{label} {value:.0f} dBµV',value))
        self.sweep_chart.set_limits(limits)


VerificationTab = CalibrationVerificationTab
