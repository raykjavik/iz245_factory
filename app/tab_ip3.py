"""Test7 results with simultaneous IP3, NF and SFDR sweep charts."""
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QSplitter, QTableWidget,
    QTableWidgetItem, QHeaderView,
)

from tab_calib import CalibrationTab
from cfg_test_7 import DISPLAY_METRICS
from measurement import IP3_COLUMNS, IP3_ARRAY_FIELDS
from sweep_chart import SweepChart, Trace


class IP3Tab(CalibrationTab):
    def __init__(self, parent=None, device_factory=None,
                 ip3_generator_factory=None):
        self._live_ip3 = None
        self._charts_ready = False
        super().__init__(
            parent,
            device_factory=device_factory,
            mode='ip3',
            ip3_generator_factory=ip3_generator_factory,
        )

        self.ip3_panel = QWidget()
        layout = QVBoxLayout(self.ip3_panel)
        layout.setContentsMargins(0, 0, 0, 0)

        self.result_table = QTableWidget(0, 1 + len(IP3_COLUMNS))
        self.result_table.setHorizontalHeaderLabels(
            ['Configuration', *IP3_COLUMNS]
        )
        self.result_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        header = self.result_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.result_table.setMinimumHeight(80)
        self.result_table.setMaximumHeight(155)

        # DISPLAY_METRICS entries: label, measurement attribute, unit, offset.
        self.chart_specs = {
            label: (attribute, unit, offset)
            for label, attribute, unit, offset in DISPLAY_METRICS
        }
        self.charts = {}
        self.chart_splitter = QSplitter(Qt.Orientation.Vertical)
        self.chart_splitter.setChildrenCollapsible(False)

        for label in ('IP3', 'NF', 'SFDR'):
            attribute, unit, offset = self.chart_specs[label]
            chart = SweepChart(
                title=f'Test7 · {"NF density" if label == "NF" else label}',
                frequency_label='Frequency',
                value_label="NF density" if label == "NF" else label,
                display_unit=unit,
                display_offset_db=offset,
            )
            chart.setMinimumWidth(240)
            self.charts[label] = chart
            self.chart_splitter.addWidget(chart)

        self.chart_splitter.setSizes([400, 400, 400])
        layout.addWidget(self.chart_splitter, 1)

        self.ip3_chart = self.charts['IP3']
        self.nf_chart = self.charts['NF']
        self.sfdr_chart = self.charts['SFDR']

        old = self.sweep_chart
        self.plot_splitter.replaceWidget(1, self.ip3_panel)
        old.deleteLater()
        self.sweep_chart = self.ip3_chart
        self.live_readout = self.ip3_chart.hover_label

        self.table_panel = QSplitter(Qt.Orientation.Vertical)
        self.table_panel.setChildrenCollapsible(False)
        self.plot_splitter.replaceWidget(0, self.table_panel)
        self.table_panel.addWidget(self.table)
        self.table_panel.addWidget(self.result_table)
        self.result_table.setMaximumHeight(16777215)
        self.table_panel.setSizes([400, 300])
        self.plot_splitter.setOrientation(Qt.Orientation.Horizontal)
        self.plot_splitter.setChildrenCollapsible(False)
        self.plot_splitter.setStretchFactor(0, 0)
        self.plot_splitter.setStretchFactor(1, 1)
        self.plot_splitter.setSizes([620, 780])
        self.connection_hint.setText(
            'Connect the combined SMATE200A RF outputs to the selected RF input and the DUT 10 MHz reference output to SMATE200A REF IN. '
            'RF1 and RF2 run separately; this test uses the Test7 generator address.'
        )

        self._charts_ready = True
        self.redraw()

    def _on_ip3_updated(self, name, result):
        if name in self.rows:
            self._live_name = name
            self._live_ip3 = (name, result)
            self.redraw()

    def _on_completed(self, name, result):
        super()._on_completed(name, result)
        if name in self.rows:
            self.rows[name]['show'].setChecked(self._show_live)

    def _clear_live(self):
        self._live_ip3 = None
        super()._clear_live()

    def redraw(self, *_):
        # CalibrationTab calls redraw during its own construction.
        if not self._charts_ready:
            return

        selected = {}
        if self.backend:
            for name, row in self.rows.items():
                if row['show'].isChecked() and self.backend.measurements[name].noise_unit == 'dB/Hz':
                    selected[name] = self.backend.measurements[name]

        if self.backend and any(row['show'].isChecked() and self.backend.measurements[name].noise_unit != 'dB/Hz' for name,row in self.rows.items()):
            self.status.setText('Legacy Test7 noise conversion: remeasure for corrected NF density and SFDR.')

        # A live result replaces the saved result of the same configuration.
        if self._show_live and self._live_ip3:
            selected[self._live_ip3[0]] = self._live_ip3[1]

        self.result_table.setRowCount(
            sum(len(result.freq_mhz) for result in selected.values())
        )
        traces = {label: {} for label in self.charts}
        row_index = 0

        for name, result in selected.items():
            live = self._show_live and self._live_ip3 is not None and self._live_ip3[0] == name
            frequency_hz = np.asarray(result.freq_mhz) * 1e6

            for label in self.charts:
                attribute, unit, offset = self.chart_specs[label]
                trace = Trace(
                    frequency_hz,
                    np.asarray(getattr(result, attribute)),
                    unit,
                    None,
                    live,
                    passed=self.verification_check(result),
                )
                self._add_trace_with_reference(traces[label],name,trace,name,type(result),
                    lambda ref:Trace(np.asarray(ref.freq_mhz)*1e6,
                        np.asarray(getattr(ref,attribute)),unit,None) if ref.noise_unit == 'dB/Hz' else None)

            for values in zip(
                *(getattr(result, field) for field in IP3_ARRAY_FIELDS)
            ):
                for column, text in enumerate(
                    [name, *(f'{value:.6g}' for value in values)]
                ):
                    item = QTableWidgetItem(text)
                    item.setToolTip(text)
                    self.result_table.setItem(row_index, column, item)
                row_index += 1

        for label, chart in self.charts.items():
            chart.set_traces(traces[label])
