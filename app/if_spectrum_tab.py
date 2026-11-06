"""Test8 controls and a signed-frequency spectrum chart."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTableWidgetItem,QHeaderView
from calib_tab import CalibrationTab
import cfg_test8 as test8_cfg
from sweep_chart import SweepChart, Trace
from spectrum_display import max_envelope


class IFSpectrumTab(CalibrationTab):
    def __init__(self, parent=None, device_factory=None):
        self._live_if = None
        super().__init__(parent, device_factory=device_factory,
                         mode='if_spectrum')
        self.columns=self.columns[:-1]+['BAND (MHz)','Samples','FFT averages','Show']
        self.table.setColumnCount(len(self.columns))
        self.table.setHorizontalHeaderLabels(self.columns)
        for column in range(6,len(self.columns)):
            self.table.horizontalHeader().setSectionResizeMode(column,QHeaderView.ResizeMode.ResizeToContents)
        self.if_chart = SweepChart(title='Test8 · IF filter spectra',
            frequency_label='Offset from 500 MHz', display_unit=test8_cfg.DISPLAY_UNIT,display_offset_db=test8_cfg.DISPLAY_OFFSET_DB,
            value_label='RMS level',hover_enabled=False)
        self.if_chart.scale.setCurrentText('Linear')
        self.if_chart.scale.hide()  # a signed offset axis cannot use log frequency
        old = self.sweep_chart
        self.plot_splitter.replaceWidget(1,self.if_chart)
        old.deleteLater()
        self.sweep_chart = self.if_chart
        self.live_readout = self.if_chart.hover_label
        self.plot_splitter.setOrientation(Qt.Orientation.Vertical)
        self.table.setMinimumHeight(150)
        self.table.setMaximumHeight(190)
        self.plot_splitter.setSizes([170,500])
        self.connection_hint.setText(
            'Terminate RF1 in 50 Ω. No generator is used. Fixed 500 MHz tuning; receiver BAND and FFT size depend on the filter. '
            'The spectrum includes negative offsets, DC and positive offsets.')

    def load_project(self,project):
        super().load_project(project)
        self._refresh_parameters()
        self.status.setText('Ready. Terminate RF1 in 50 Ω before measuring IF filters.')

    def _row_verification_result(self, name, measurement):
        # Even an empty/unreadable existing file satisfies this presence-only
        # policy; plotting still requires complete data, as for other tabs.
        if self.backend is not None:
            passed = self.backend.path(name).is_file()
        else:
            passed = test8_cfg.evaluate_test8(measurement)
        return passed, 'Measurement file exists' if passed else 'Measurement file missing'

    def setup_changed(self):
        super().setup_changed()
        self._refresh_parameters()

    def _refresh_parameters(self):
        if self.project is None or self.backend is None:
            return
        for row,name in enumerate(self.configs):
            if row>=self.table.rowCount():continue
            spec=self.backend.spec_for(name)
            for column,value in ((6,f'{spec.reciver_bandwidth/1e6:g}'),
                                 (7,str(spec.window_samples)),(8,str(spec.ffts))):
                self.table.setItem(row,column,QTableWidgetItem(value))
            item=self.table.item(row,0)
            if item is not None:
                bits=16 if spec.reciver_bandwidth>40e6 else 32
                item.setToolTip(f'{name}\nBAND {spec.reciver_bandwidth/1e6:g} MHz; '
                                f'{spec.window_samples:,} samples; {spec.ffts} averages; {bits}-bit IQ reader')

    def _on_spectrum_updated(self, name, result):
        if name not in self.rows:
            return
        self._live_name = name
        self._live_if = (name,result)
        self.redraw()
        self.status.setText(f'IF {result.if_bandwidth_hz/1e6:g} MHz · averaging FFT '
                            f'{result.ffts}/{self.backend.spec_for(name).ffts}')

    def _on_completed(self, name, result):
        super()._on_completed(name,result)
        if name in self.rows:
            self.rows[name]['show'].setChecked(self._show_live)

    def _clear_live(self):
        self._live_if = None
        super()._clear_live()

    def redraw(self, *_):
        if not hasattr(self,'if_chart'):
            return
        traces = {}
        widths = []
        def add(name,result,live=False):
            if result.offset_hz.size == 0:
                return
            frequency,maximum=max_envelope(result.offset_hz,result.power_db)
            label=f'IF {result.if_bandwidth_hz/1e6:g} MHz'+(' (live)' if live else '')
            widths.append(result.if_bandwidth_hz)
            trace=Trace(frequency,maximum,result.unit,None,live,
                display_unit=test8_cfg.DISPLAY_UNIT if result.unit == 'dBm' else result.unit,
                display_offset_db=test8_cfg.DISPLAY_OFFSET_DB if result.unit == 'dBm' else 0.,
                passed=test8_cfg.evaluate_test8(result))
            def reference_trace(reference):
                if reference.unit != result.unit:
                    return None
                x,y = max_envelope(reference.offset_hz,reference.power_db)
                return Trace(x,y,reference.unit,None,
                    display_unit=test8_cfg.DISPLAY_UNIT if reference.unit == 'dBm' else reference.unit,
                    display_offset_db=test8_cfg.DISPLAY_OFFSET_DB if reference.unit == 'dBm' else 0.)
            self._add_trace_with_reference(traces,label+' · max',trace,name,type(result),reference_trace)
        if self.backend:
            for name,row in self.rows.items():
                if row['show'].isChecked():
                    add(name,self.backend.measurements[name])
        if self._show_live and self._live_if:
            add(*self._live_if,live=True)
        self.if_chart.set_traces(traces)
        self.if_chart.set_vertical_limits([edge for width in widths for edge in test8_cfg.filter_edges_hz(width)])
        focus = self._live_if[1].if_bandwidth_hz if self._show_live and self._live_if else max(widths,default=0)
        self.if_chart.set_x_limits(test8_cfg.filter_view_hz(focus) if focus else None)
