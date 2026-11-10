"""Combined Test5 and Test6 phase/amplitude noise tab."""

from verification import evaluate_test5,evaluate_test6
from chart_ranges import clipped_curve
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout
from tab_calib import CalibrationTab
from calib_controller import measured
from sweep_chart import SweepChart, Trace
import cfg_test_5_6 as density_cfg


class NoiseDensityTab(CalibrationTab):
    """Paired Test5/Test6 spectra from one shared acquisition per carrier."""
    def __init__(self,parent=None,generator_factory=None,device_factory=None, ip3_generator_factory=None):
        self._live_density=None
        super().__init__(parent,generator_factory,mode='density',device_factory=device_factory)
        old=self.sweep_chart
        panel=QWidget()
        self.density_panel=panel  # keep Python ownership after QSplitter.replaceWidget
        layout=QVBoxLayout(panel)
        layout.setContentsMargins(0,0,0,0)
        self.phase_chart=SweepChart(title='Test5 · phase noise density',
            frequency_label='Offset frequency',display_unit=density_cfg.DISPLAY_UNIT,
            display_offset_db=density_cfg.DISPLAY_OFFSET_DB,value_label='Noise density',hover_enabled=False)
        self.amplitude_chart=SweepChart(title='Test6 · amplitude noise density',
            frequency_label='Offset frequency',display_unit=density_cfg.DISPLAY_UNIT,
            display_offset_db=density_cfg.DISPLAY_OFFSET_DB,value_label='Noise density',hover_enabled=False)
        layout.addWidget(self.phase_chart,1)
        layout.addWidget(self.amplitude_chart,1)
        self.plot_splitter.replaceWidget(1,panel)
        old.deleteLater()
        self.sweep_chart=self.phase_chart
        self.live_readout=self.phase_chart.hover_label
        self.plot_splitter.setOrientation(Qt.Orientation.Horizontal)
        self.plot_splitter.setChildrenCollapsible(False)
        self.plot_splitter.setStretchFactor(0,0);self.plot_splitter.setStretchFactor(1,1)
        self.plot_splitter.setSizes([620,780])
        self.phase_chart.cursor_table.setMaximumHeight(115)
        self.amplitude_chart.cursor_table.setMaximumHeight(115)
        self.connection_hint.setText('Connect the CW generator to RF1. Test5 and Test6 share each IQ acquisition.')

    def _verification_result(self,measurement):
        if not measured(measurement):
            return None,'No complete noise density data'
        phase,amplitude=evaluate_test5(measurement),evaluate_test6(measurement)
        def label(value):
            return 'not evaluated' if value is None else 'pass' if value else 'fail'
        result=None if phase is None or amplitude is None else bool(phase and amplitude)
        return result,f'Test5: {label(phase)}; Test6: {label(amplitude)}'

    def _on_completed(self,name,result):
        super()._on_completed(name,result)
        if name in self.rows:
            self.rows[name]['show'].setChecked(self._show_live)

    def _on_density_updated(self,name,result):
        if name not in self.rows:
            return
        self._live_density=(name,result)
        self._live_name=name
        self.redraw()
        self.status.setText(f'{result.carrier_hz/1e6:g} MHz · averaging FFT {result.ffts}/{self.project.settings.noise_ffts}')
        if not self.busy:
            self.progress.setRange(0,self.project.settings.noise_ffts)
            self.progress.setValue(result.ffts)

    def _clear_live(self):
        self._live_density=None
        super()._clear_live()

    def redraw(self,*_):
        if not hasattr(self,'phase_chart'):
            return
        phase={};amplitude={}
        def add(name,result,live=False):
            if result.offset_hz.size==0:
                return
            phase_x, phase_y = clipped_curve(result.offset_hz,result.phase_noise,
                density_cfg.PLOT_FREQUENCY_LIMITS_HZ,log_x=True,max_points=4096)
            amplitude_x, amplitude_y = clipped_curve(result.offset_hz,result.amplitude_noise,
                density_cfg.PLOT_FREQUENCY_LIMITS_HZ,log_x=True,max_points=4096)
            curve=f'{result.carrier_hz/1e6:g} MHz'+(' (live)' if live else '')
            phase_trace=Trace(phase_x,phase_y,result.unit,None,live,
                               passed=density_cfg.evaluate_test5(result))
            amplitude_trace=Trace(amplitude_x,amplitude_y,result.unit,None,live,
                                   passed=density_cfg.evaluate_test6(result))
            def reference_trace(reference, attribute):
                x,y = clipped_curve(reference.offset_hz,getattr(reference,attribute),
                    density_cfg.PLOT_FREQUENCY_LIMITS_HZ,log_x=True,max_points=4096)
                return Trace(x,y,reference.unit,None)
            self._add_trace_with_reference(phase,curve,phase_trace,name,type(result),
                lambda ref:reference_trace(ref,'phase_noise'))
            self._add_trace_with_reference(amplitude,curve,amplitude_trace,name,type(result),
                lambda ref:reference_trace(ref,'amplitude_noise'))
        if self.backend:
            for name,row in self.rows.items():
                result=self.backend.measurements[name]
                if row['show'].isChecked() and measured(result):
                    add(name,result)
        if self._show_live and self._live_density:
            add(*self._live_density,live=True)
        self.phase_chart.set_traces(phase)
        self.amplitude_chart.set_traces(amplitude)
        for chart in (self.phase_chart,self.amplitude_chart):
            chart.set_x_limits(density_cfg.PLOT_FREQUENCY_LIMITS_HZ)
