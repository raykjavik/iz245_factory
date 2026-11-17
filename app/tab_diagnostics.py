"""Manual SCPI and saved, comparable diagnostic spectra."""
from pathlib import Path
from PySide6.QtGui import QFontDatabase
from PySide6.QtCore import Qt,Signal,Slot
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QGroupBox,
    QComboBox,QLineEdit,QPlainTextEdit,QPushButton,QLabel,QSpinBox,QDoubleSpinBox,
    QTableWidget,QTableWidgetItem,QHeaderView,QSplitter,QProgressBar,QFileDialog,QMessageBox,
    QDialog,QDialogButtonBox)
from diagnostic_controller import DiagnosticThread
from diagnostic_spectrum import CaptureOptions,DIAGNOSTIC_DIR,DISPLAY_UNITS,DISPLAY_LABELS
from sweep_chart import SweepChart,Trace

SCPI_HELP_PATH=Path(__file__).with_name('scpi_help.txt')


class DiagnosticsTab(QWidget):
    changed=Signal()
    message=Signal(str)
    validity_changed=Signal(bool)
    busy_changed=Signal(bool)
    control_state_changed=Signal()

    def __init__(self,parent=None,*,device_factory=None,generator_factory=None,ip3_generator_factory=None):
        super().__init__(parent)
        self.project=None;self.records={};self._previews={};self._live=None;self._thread=None
        self._external_busy=False;self._populating=False;self._show_live=True
        self._help_dialog=None
        self.factories=dict(device_factory=device_factory,generator_factory=generator_factory,
                            ip3_generator_factory=ip3_generator_factory)
        layout=QVBoxLayout(self);top=QHBoxLayout()
        scpi=QGroupBox('Manual SCPI');scpi_layout=QVBoxLayout(scpi)
        target_row=QHBoxLayout();self.target=QComboBox();self.target.addItems(['DUT','Generator 1','Generator 2'])
        self.endpoint=QLabel();target_row.addWidget(self.target);target_row.addWidget(self.endpoint,1)
        scpi_layout.addLayout(target_row)
        self.commands=QPlainTextEdit();self.commands.setPlaceholderText('One command or query per line:\nBAND 20M\nFREQ 500MHz\n*IDN?')
        self.commands.setMaximumHeight(130);scpi_layout.addWidget(self.commands)
        self.send=QPushButton('Send SCPI');self.help_button=QPushButton('Help…')
        scpi_buttons=QHBoxLayout();scpi_buttons.addWidget(self.send,1);scpi_buttons.addWidget(self.help_button)
        scpi_layout.addLayout(scpi_buttons)
        capture=QGroupBox('Averaged spectrum · capture settings');form=QFormLayout(capture)
        self.name=QLineEdit('Spectrum');self.samples=QComboBox()
        self.bandwidth=QDoubleSpinBox();self.bandwidth.setRange(.001,1000);self.bandwidth.setDecimals(3)
        self.bandwidth.setSuffix(' MHz');self.bandwidth.setValue(20)
        self.frequency=QDoubleSpinBox();self.frequency.setRange(.000001,100000);self.frequency.setDecimals(6)
        self.frequency.setSuffix(' MHz');self.frequency.setValue(500)
        self.bandwidth.setToolTip('Receiver BAND, sent before each capture and synchronized with *OPC?.')
        self.frequency.setToolTip('Receiver FREQ, applied with awaited tuning before each capture.')
        for exponent in range(10,23):self.samples.addItem(f'{2**exponent:,}',2**exponent)
        self.samples.setCurrentIndex(6)
        self.fft_count=QSpinBox();self.fft_count.setRange(1,1_000_000);self.fft_count.setValue(100)
        self.overlap=QDoubleSpinBox();self.overlap.setRange(0,99);self.overlap.setDecimals(1);self.overlap.setValue(50);self.overlap.setSuffix(' %')
        self.iq_bits=QComboBox();self.iq_bits.addItems(['Auto','16','32'])
        self.iq_bits.setToolTip('Auto: 16-bit IQ for receiver BAND > 40 MHz, otherwise 32-bit; same as Test8.')
        for label,control in [('Name',self.name),('BAND',self.bandwidth),('FREQ',self.frequency),('Samples / FFT',self.samples),('FFT windows',self.fft_count),('Overlap',self.overlap),('IQ format',self.iq_bits)]:form.addRow(label,control)
        self.capture=QPushButton('Capture averaged spectrum');form.addRow(self.capture)
        log_group=QGroupBox('SCPI responses and acquisition log');log_layout=QVBoxLayout(log_group)
        self.log=QPlainTextEdit();self.log.setReadOnly(True);self.log.setMaximumBlockCount(2000);log_layout.addWidget(self.log)
        top.addWidget(capture,2);top.addWidget(scpi,2);top.addWidget(log_group,2);layout.addLayout(top)
        controls=QHBoxLayout();self.import_button=QPushButton('Load spectrum…')
        self.show_all=QPushButton('Show all');self.hide_all=QPushButton('Hide all')
        self.units=QComboBox()
        for label,unit in zip(DISPLAY_LABELS,DISPLAY_UNITS):self.units.addItem(label,unit)
        self.units.setToolTip('RMS voltage and 50-ohm power use the Hann ENBW. NF = density in dBm/Hz − (−174 dBm/Hz).')
        controls.addWidget(self.import_button);controls.addWidget(self.show_all);controls.addWidget(self.hide_all)
        controls.addStretch();controls.addWidget(QLabel('Display:'));controls.addWidget(self.units);layout.addLayout(controls)
        self.location=QLabel('Open a project. Completed spectra are saved in its diagnostics folder.');layout.addWidget(self.location)
        self.table=QTableWidget(0,8);self.table.setHorizontalHeaderLabels(['Show','Name','Date / time (UTC)','Carrier','Samples','FFTs','Save copy','Delete'])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers);self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(36)
        for column in range(8):self.table.horizontalHeader().setSectionResizeMode(column,QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1,QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(1,240)
        self.table.setMinimumHeight(200);self.table.setMinimumWidth(360)
        self.chart=SweepChart(title='Diagnostic spectra',frequency_label='Offset from carrier',
            display_unit='dBµV',display_offset_db=0.,value_label='RMS level',hover_enabled=False,spectral=True)
        self.chart.scale.setCurrentText('Linear');self.chart.scale.hide()
        self.splitter=QSplitter(Qt.Orientation.Horizontal);self.splitter.addWidget(self.table);self.splitter.addWidget(self.chart)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setStretchFactor(0,0);self.splitter.setStretchFactor(1,1)
        self.splitter.setSizes([480,920]);layout.addWidget(self.splitter,1)
        self.status=QLabel('Capture applies BAND and FREQ with OPC synchronization before acquiring IQ; other DUT settings are retained.')
        self.status.setWordWrap(True);layout.addWidget(self.status)
        self.progress=QProgressBar();self.progress.setRange(0,1);self.progress.setValue(0);layout.addWidget(self.progress)
        self.target.currentIndexChanged.connect(self.setup_changed);self.commands.textChanged.connect(self._update_enabled)
        self.send.clicked.connect(lambda:self._start('scpi'));self.capture.clicked.connect(lambda:self._start('capture'))
        self.help_button.clicked.connect(self._show_scpi_help)
        self.import_button.clicked.connect(self._import)
        self.show_all.clicked.connect(lambda:self._set_shown(True));self.hide_all.clicked.connect(lambda:self._set_shown(False))
        self.units.currentTextChanged.connect(self.redraw);self.table.itemChanged.connect(self._item_changed)
        self._update_enabled()

    @property
    def busy(self):return self._thread is not None

    def _show_scpi_help(self):
        if self._help_dialog is not None and self._help_dialog.isVisible():
            self._help_dialog.raise_();self._help_dialog.activateWindow();return
        try:text=SCPI_HELP_PATH.read_text(encoding='utf-8')
        except OSError as exc:
            QMessageBox.warning(self,'SCPI help unavailable',str(exc));return
        if self._help_dialog is not None:self._help_dialog.deleteLater()
        dialog=QDialog(self);dialog.setWindowTitle('SCPI command reference');dialog.resize(1000,700)
        layout=QVBoxLayout(dialog)
        viewer=QPlainTextEdit();viewer.setReadOnly(True);viewer.setPlainText(text)
        viewer.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        viewer.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        layout.addWidget(viewer)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject);layout.addWidget(buttons)
        self._help_dialog=dialog;dialog.open()

    def load_project(self,project):
        if self.busy:raise RuntimeError('Wait for diagnostic work to finish before changing project.')
        self.project=project;self.records.clear();self._previews.clear();self._live=None;self.table.setRowCount(0);self.chart.set_traces({})
        self.chart.reset_view()
        self._show_live=True;self.validity_changed.emit(False);self.setup_changed()
        self.location.setText(f'Spectra: {project.root/DIAGNOSTIC_DIR} · completed captures saved automatically')
        self._start('load')

    def setup_changed(self,*_):
        if self.project:
            settings=self.project.settings
            self.endpoint.setText(f'{settings.dut_ip}' if self.target.currentText()=='DUT' else
                f'{settings.generator_ip}:{settings.generator_port}' if self.target.currentText()=='Generator 1' else
                f'{settings.ip3_generator_ip or "Set Test7 generator IP in Settings"}:{settings.ip3_generator_port}')
        self._update_enabled()

    def set_external_busy(self,busy):self._external_busy=busy;self._update_enabled()

    def _update_enabled(self,*_):
        enabled=self.project is not None and not self.busy and not self._external_busy
        self.send.setEnabled(enabled and bool(self.commands.toPlainText().strip()))
        self.capture.setEnabled(enabled);self.import_button.setEnabled(enabled);self.target.setEnabled(enabled)
        for control in (self.name,self.bandwidth,self.frequency,self.samples,self.fft_count,self.overlap,self.iq_bits):
            control.setEnabled(enabled)
        for row in range(self.table.rowCount()):
            for column in (6,7):self.table.cellWidget(row,column).setEnabled(enabled)

    def _start(self,operation,source=None,destination=None):
        if self.project is None or self.busy or self._external_busy:return
        options=CaptureOptions(name=self.name.text().strip() or 'Spectrum',window_samples=int(self.samples.currentData()),
            fft_count=self.fft_count.value(),overlap=self.overlap.value()/100,iq_bits=self.iq_bits.currentText(),
            bandwidth_hz=self.bandwidth.value()*1e6,carrier_hz=self.frequency.value()*1e6)
        if operation=='capture':self._live=None
        worker=DiagnosticThread(self.project,operation,target=self.target.currentText(),
            commands=self.commands.toPlainText(),options=options,source=source,destination=destination,parent=self,**self.factories)
        self._thread=worker
        worker.log.connect(self.log.appendPlainText);worker.preview.connect(self._on_preview)
        worker.record_ready.connect(self._record_ready);worker.progress.connect(self._on_progress)
        worker.paused.connect(self._on_paused);worker.finished.connect(self._finished)
        self.progress.setRange(0,options.fft_count if operation=='capture' else 0);self.progress.setValue(0)
        self.progress.setFormat('%v / %m FFT windows' if operation=='capture' else '%p%')
        self.status.setText(worker.action+'…');self._update_enabled();self.busy_changed.emit(True);worker.start()

    @Slot(object)
    def _on_preview(self,result):
        self._live=result;self.redraw()
        self.status.setText(f'Averaging {result.ffts}/{self._thread.options.fft_count} FFT windows · ENBW {result.enbw_hz:g} Hz')
    @Slot(int)
    def _on_progress(self,completed):self.progress.setValue(completed)
    @Slot(bool)
    def _on_paused(self,paused):
        self.status.setText('Paused; resume or abort from the toolbar.' if paused else 'Capturing spectrum…')
        self.control_state_changed.emit()

    @Slot(str,object)
    def _record_ready(self,filename,result):
        self.records[filename]=result
        self._previews[filename]=result  # Full resolution allows resampling after zoom.
        self._populating=True
        row=self.table.rowCount();self.table.insertRow(row)
        show=QTableWidgetItem();show.setFlags(Qt.ItemFlag.ItemIsEnabled|Qt.ItemFlag.ItemIsUserCheckable)
        show.setCheckState(Qt.CheckState.Checked if self._show_live else Qt.CheckState.Unchecked)
        show.setData(Qt.ItemDataRole.UserRole,filename);self.table.setItem(row,0,show)
        for column,text in [(1,result.name),(2,result.datetime.replace('T',' ')[:19]),(3,f'{result.carrier_hz/1e6:g} MHz'),(4,str(result.window_samples)),(5,str(result.ffts))]:
            item=QTableWidgetItem(text);item.setToolTip(f'{filename}\nOverlap {result.overlap:g}; fs {result.sample_rate_hz:g} Hz; ENBW {result.enbw_hz:g} Hz')
            self.table.setItem(row,column,item)
        export=QPushButton('Save copy…');delete=QPushButton('Delete')
        export.clicked.connect(lambda _,key=filename:self._export(key));delete.clicked.connect(lambda _,key=filename:self._delete(key))
        self.table.setCellWidget(row,6,export);self.table.setCellWidget(row,7,delete)
        self._populating=False
        if self._thread and self._thread.operation=='capture':self._live=None
        if self._thread and self._thread.operation!='load':self.changed.emit()
        self.validity_changed.emit(bool(self.records));self._update_enabled();self.redraw()

    @Slot()
    def _finished(self):
        worker=self._thread;self._live=None
        if worker.error:
            self.status.setText(worker.error);self.log.appendPlainText('Error: '+worker.error);self.message.emit(worker.error)
        elif worker.aborted:self.status.setText('Aborted; completed saved spectra are retained.')
        else:self.status.setText('Ready. Completed spectra are saved automatically; select Show to compare.')
        self.progress.setRange(0,max(1,worker.options.fft_count) if worker.operation=='capture' else 1)
        if not worker.error and not worker.aborted:self.progress.setValue(self.progress.maximum())
        self._thread=None;worker.deleteLater();self._update_enabled();self.redraw();self.busy_changed.emit(False);self.control_state_changed.emit()

    def pause_measurement(self):
        if self.busy and self._thread.job.pausable:self._thread.pause_event.set();self.control_state_changed.emit()
    def resume_measurement(self):
        if self.busy:self._thread.pause_event.clear();self.control_state_changed.emit()
    def abort_measurement(self):
        if self.busy:self._thread.abort();self.status.setText('Aborting…');self.control_state_changed.emit()

    def _set_shown(self,shown):
        self._show_live=shown;self._populating=True
        for row in range(self.table.rowCount()):self.table.item(row,0).setCheckState(Qt.CheckState.Checked if shown else Qt.CheckState.Unchecked)
        self._populating=False;self.redraw()
    def _item_changed(self,*_):
        if not self._populating:self.redraw()

    def _import(self):
        path,_=QFileDialog.getOpenFileName(self,'Load diagnostic or calibrated Test8 spectrum','','Spectra (*.txt)')
        if path:self._start('import',path)
    def _export(self,key):
        path,_=QFileDialog.getSaveFileName(self,'Save spectrum copy',str(self.project.root/key),'Spectra (*.txt)')
        if not path:return
        source=self.project.root/DIAGNOSTIC_DIR/key;destination=Path(path)
        if not destination.suffix:destination=destination.with_suffix('.txt')
        if source.resolve()==destination.resolve():return
        self._start('export',source,destination)
    def _delete(self,key):
        if self.busy or self._external_busy:return
        try:(self.project.root/DIAGNOSTIC_DIR/key).unlink(missing_ok=True)
        except OSError as exc:QMessageBox.warning(self,'Cannot delete spectrum',str(exc));return
        self.records.pop(key,None);self._previews.pop(key,None)
        for row in range(self.table.rowCount()):
            if self.table.item(row,0).data(Qt.ItemDataRole.UserRole)==key:self.table.removeRow(row);break
        self.changed.emit();self.validity_changed.emit(bool(self.records));self.redraw()

    def redraw(self,*_):
        unit=self.units.currentData();traces={}
        def add(key,result,live=False):
            display=result if live else self._previews[key]
            x,y=display.offset_hz,display.levels(unit)
            label=f'{result.name} · {"live" if live else key[-14:-4]}'
            traces[label]=Trace(x,y,unit,None,live,display_unit=unit,display_offset_db=0.,color_key=key)
        for row in range(self.table.rowCount()):
            item=self.table.item(row,0)
            if item.checkState()==Qt.CheckState.Checked:
                key=item.data(Qt.ItemDataRole.UserRole);add(key,self.records[key])
        if self._live is not None and self._show_live:add('current',self._live,True)
        self.chart.display_unit=unit;self.chart.value_label='NF' if unit=='dB' else 'Power' if unit=='dBm' else 'RMS level'
        self.chart.set_traces(traces)
