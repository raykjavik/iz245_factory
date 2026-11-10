"""Combined Test2, Test3 and Test4 measurement tab."""

import cfg_test2
import cfg_test3
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QPushButton
from tab_calib import CalibrationTab
from calib_controller import measured
from sweep_chart import SweepChart


class NoisePreselectorsTab(CalibrationTab):
    """Separate voltage-level and noise-density charts for Tests2/3/4."""
    def __init__(self, parent=None, generator_factory=None, verification_check=None, device_factory=None, ip3_generator_factory=None):
        self._noise_charts_ready=False
        super().__init__(parent,generator_factory,verification_check=verification_check,
            device_factory=device_factory,mode='noise')
        self.ch1.setText('Run Test2 RF1')
        self.ch2.setText('Run Test2 RF2')
        self.test3_button=QPushButton('Run Test3 preselectors')
        self.layout().itemAt(0).layout().insertWidget(2,self.test3_button)
        self.test3_button.clicked.connect(lambda:self.start('test3_rf1'))
        panel=QWidget();self.noise_panel=panel
        layout=QVBoxLayout(panel);layout.setContentsMargins(0,0,0,0)
        self.level_chart=SweepChart(title='Test3 & Test4 · RMS level',frequency_label='Frequency',
            value_label='RMS level',display_unit=cfg_test3.DISPLAY_UNIT,display_offset_db=cfg_test3.DISPLAY_OFFSET_DB)
        self.density_chart=SweepChart(title='Test2 · noise figure',frequency_label='Frequency',
            value_label='NF density',display_unit='dB/Hz',display_offset_db=0.)
        layout.addWidget(self.density_chart,1)
        layout.addWidget(self.level_chart,1)
        old=self.sweep_chart;self.plot_splitter.replaceWidget(1,panel);old.deleteLater()
        self.sweep_chart=self.level_chart  # existing integration / cursor compatibility
        self.live_readout=self.level_chart.hover_label
        self.plot_splitter.setOrientation(Qt.Orientation.Horizontal)
        self.plot_splitter.setChildrenCollapsible(False)
        self.plot_splitter.setStretchFactor(0,0);self.plot_splitter.setStretchFactor(1,1)
        self.plot_splitter.setSizes([620,780])
        self.connection_hint.setText('Test2: terminate the selected RF input in 50 Ω; no generator is used. '
            'Test3: connect the generator to RF1. Run separately after switching the connection. '
            'Test4 uses the internal source.')
        self._noise_charts_ready=True
        self._update_enabled();self.redraw()

    def load_project(self,project):
        super().load_project(project)
        self.status.setText('Ready. Test2: 50 Ω termination; Test3: generator on RF1; Test4: internal source.')

    def _update_enabled(self):
        super()._update_enabled()
        if hasattr(self,'test3_button'):
            self.test3_button.setEnabled(self.project is not None and not self.busy and not self._external_busy
                and not getattr(self.project,'cable_calib_error',''))

    def _verification_result(self,measurement):
        if measurement.name.startswith(('TEST2_','TEST4')):
            passed=bool(measurement.available)
            return passed,'Measurement exists; no level threshold' if passed else 'Measurement missing'
        if measurement.name.startswith('TEST3') and measured(measurement):
            try:
                cfg_test3.absolute_dbm(measurement)
            except ValueError as exc:
                return False,str(exc)
        return super()._verification_result(measurement)

    def setup_changed(self):
        super().setup_changed();self.redraw()

    def redraw(self,*_):
        if not self._noise_charts_ready:
            return
        level,nf={},{}
        for label,trace in self._sweep_traces().items():
            destination=nf if (trace.color_key or label).startswith('TEST2') else level
            destination[label]=trace
        self.level_chart.set_traces(level);self.density_chart.set_traces(nf)
        references=set()
        if self.backend:
            for name,row in self.rows.items():
                result=self.backend.measurements[name]
                if name.startswith('TEST3_') and row['show'].isChecked() and measured(result) and result.unit=='dBm' and result.reference_dbm is not None:
                    references.add(result.reference_dbm)
            if self._show_live and self._live_name and self._live_points and self._live_name.startswith('TEST3_'):
                references.add(self.backend.spec_for(self._live_name).power_dbm)
        self.level_chart.set_limits([(f'Test3 lower limit {cfg_test3.limit_dbm(reference)+cfg_test3.DISPLAY_OFFSET_DB:.2f} dBµV',
            cfg_test3.limit_dbm(reference)+cfg_test3.DISPLAY_OFFSET_DB) for reference in sorted(references)])
        self.density_chart.set_limits([])
