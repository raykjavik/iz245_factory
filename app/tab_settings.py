"""Project-owned measurement settings. No global QSettings persistence."""
from pathlib import Path
from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QFormLayout, QGroupBox,
    QLineEdit, QDoubleSpinBox, QSpinBox, QPushButton, QLabel, QComboBox,
    QHBoxLayout, QGridLayout, QFileDialog, QMessageBox, QScrollArea)
from project import AutoProps
from cfg_test8 import CFG_TEST8


class SettingsTab(QWidget):
    changed = Signal()
    validity_changed = Signal(bool)
    connect_requested = Signal(str)
    dut_changed = Signal()
    cable_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.project = None
        self._loading = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24,24,24,24)
        group = QGroupBox('Measurement setup · saved with the project')
        form = QFormLayout(group)
        form.setSpacing(16)
        self.fields = {}
        for name,label in (('operator','Operator'),('dut_ip','DUT IP address'),
                           ('generator_ip','Generator IP address'),
                           ('ip3_generator_ip','Test7 two-tone generator IP address')):
            edit=QLineEdit()
            self.fields[name]=edit
            form.addRow(label,edit)
            edit.textChanged.connect(self._edited)
        self.generator_port=QSpinBox()
        self.generator_port.setRange(1,65535)
        form.addRow('Generator port',self.generator_port)
        self.generator_port.valueChanged.connect(self._edited)
        self.ip3_generator_port=QSpinBox()
        self.ip3_generator_port.setRange(1,65535)
        form.addRow('Test7 generator port',self.ip3_generator_port)
        self.ip3_generator_port.valueChanged.connect(self._edited)
        self.dwells={}
        for name,label in (('calibration_dwell_sec','Calibration dwell'),
                           ('verification_dwell_sec','Verification dwell'),
                           ('ip3_noise_dwell_sec','Test7 noise dwell'),
                           ('ip3_signal_dwell_sec','Test7 P / IM3 dwell')):
            spin=QDoubleSpinBox()
            spin.setRange(.001,60)
            spin.setDecimals(3)
            spin.setSuffix(' s / point')
            form.addRow(label,spin)
            self.dwells[name]=spin
            spin.valueChanged.connect(self._edited)
        self.levels={}
        for name,label,suffix,default in (
            ('calibration_power_dbm','Calibration target power',' dBm',-40),
            ('verification_power_dbm','Verification target power',' dBm',-50),
            ('preselector_power_dbm','Test3 preselector target power',' dBm',-30),
            ('ip3_headroom_db','Test7 per-tone headroom below full range',' dB',3.01029995664),
            ('attenuator_db','Attenuator / static loss compensation',' dB',0),
            ('ip3_attenuator_db','Test7 path attenuation',' dB',0)):
            spin=QDoubleSpinBox()
            spin.setRange(-200,100)
            spin.setDecimals(3)
            spin.setSuffix(suffix)
            spin.setValue(default)
            form.addRow(label,spin)
            self.levels[name]=spin
            spin.valueChanged.connect(self._edited)
        self.levels['attenuator_db'].setToolTip(
            'Positive loss is added to the generator POW set point. Include any fixed cable loss here.')
        self.dwells['verification_dwell_sec'].setToolTip(
            'Other verification tests; Test7 uses its own noise and P / IM3 dwell times.')
        self.levels['ip3_attenuator_db'].setToolTip(
            'Test7 static path loss only, added to both generator channel power set points. '
            'Other tests use the general attenuator setting.')
        cable_row=QHBoxLayout()
        self.cable_path=QLineEdit()
        self.cable_path.setReadOnly(True)
        self.cable_path.setPlaceholderText('None — no frequency-dependent correction')
        browse=QPushButton('Browse…')
        clear=QPushButton('Clear')
        cable_row.addWidget(self.cable_path,1)
        cable_row.addWidget(browse)
        cable_row.addWidget(clear)
        form.addRow('Cable calibration path',cable_row)
        browse.clicked.connect(self._select_cable)
        clear.clicked.connect(lambda:self.set_cable_calibration(None))
        self.cable_status=QLabel()
        self.cable_status.setWordWrap(True)
        form.addRow('',self.cable_status)
        self.noise_ffts=QSpinBox()
        self.noise_ffts.setRange(1,10000)
        self.noise_ffts.setValue(50)
        self.noise_ffts.setSuffix(' windows / carrier')
        form.addRow('Test5/6 FFT averages',self.noise_ffts)
        self.noise_ffts.valueChanged.connect(self._edited)
        self.test8_ffts={}
        for spec in CFG_TEST8.values():
            spin=QSpinBox()
            spin.setRange(1,1000000)
            spin.setValue(spec.ffts)
            spin.setSuffix(' windows')
            spin.setToolTip(f'BAND {spec.reciver_bandwidth/1e6:g} MHz; N={spec.window_samples}')
            form.addRow(f'Test8 · {spec.filter_label}',spin)
            self.test8_ffts[spec.filter_label]=spin
            spin.valueChanged.connect(self._edited)
        self.connect_button=QPushButton('Connect DUT / read identity')
        self.connect_button.clicked.connect(self._connect)
        form.addRow('',self.connect_button)
        self.status=QLabel('Create or open a project to edit its setup.')
        self.status.setWordWrap(True)
        scroll=QScrollArea()
        scroll.setWidgetResizable(True)
        # Move the same controls into grouped columns; persistence stays unchanged.
        detached=[]
        while form.rowCount():
            detached.append(form.takeRow(0))
        content=QWidget()
        grid=QGridLayout(content)
        grid.setContentsMargins(0,8,8,8)
        grid.setSpacing(16)
        grid.setColumnStretch(0,1);grid.setColumnStretch(1,1)
        self.groups={}
        def card(title,row,column,span=1):
            box=QGroupBox(title)
            box_form=QFormLayout(box)
            box_form.setHorizontalSpacing(18);box_form.setVerticalSpacing(10)
            box_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
            grid.addWidget(box,row,column,1,span)
            self.groups[title]=box
            return box_form
        lan=card('LAN connections',0,0)
        setup=card('Measurement setup',0,1)
        level_form=card('Generator levels',1,0)
        fft=card('FFT averaging',1,1)
        cable=card('Cable calibration',2,0,2)
        lan.addRow('DUT IP',self.fields['dut_ip'])
        for label,name,port in (('Generator IP','generator_ip',self.generator_port),
                                ('Test7 SMATE200A IP','ip3_generator_ip',self.ip3_generator_port)):
            row=QHBoxLayout();row.addWidget(self.fields[name],1);row.addWidget(QLabel('Port'))
            port.setMaximumWidth(100);row.addWidget(port);lan.addRow(label,row)
        lan.addRow('',self.connect_button)
        setup.addRow('Operator',self.fields['operator'])
        setup.addRow('Calibration dwell',self.dwells['calibration_dwell_sec'])
        setup.addRow('Verification dwell',self.dwells['verification_dwell_sec'])
        setup.addRow('Test7 noise dwell',self.dwells['ip3_noise_dwell_sec'])
        setup.addRow('Test7 P / IM3 dwell',self.dwells['ip3_signal_dwell_sec'])
        for name,label in (('calibration_power_dbm','Calibration power'),
                           ('verification_power_dbm','Verification power'),
                           ('preselector_power_dbm','Test3 preselector power'),
                           ('ip3_headroom_db','Test7 per-tone headroom'),
                           ('attenuator_db','Attenuator / static loss'),
                           ('ip3_attenuator_db','Test7 path attenuation')):
            level_form.addRow(label,self.levels[name])
        fft.addRow('Test5/6',self.noise_ffts)
        for label,spin in self.test8_ffts.items():fft.addRow('Test8 · '+label,spin)
        cable.addRow('Calibration file',cable_row)
        cable.addRow('',self.cable_status)
        grid.setRowStretch(3,1)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(content)
        title=QLabel('Measurement settings')
        title.setStyleSheet('font-size:20px;font-weight:600;color:#233c55;')
        subtitle=QLabel('Connections, acquisition parameters and corrections saved with the project.')
        subtitle.setStyleSheet('color:#64748b;')
        layout.insertWidget(0,title);layout.insertWidget(1,subtitle)
        self.setObjectName('settings_page')
        self.setStyleSheet("""
            QWidget#settings_page QGroupBox {background:white;border:1px solid #d8dee6;
                border-radius:8px;margin-top:12px;padding:14px 12px 10px;font-weight:600;}
            QWidget#settings_page QGroupBox::title {subcontrol-origin:margin;left:12px;
                padding:0 6px;color:#233c55;}
            QWidget#settings_page QLineEdit,QWidget#settings_page QSpinBox,
            QWidget#settings_page QDoubleSpinBox,QWidget#settings_page QComboBox {
                min-height:28px;font-weight:400;}
            QWidget#settings_page QPushButton {min-height:28px;padding:0 10px;}
        """)
        layout.addWidget(scroll,1)
        layout.addWidget(self.status)

        self.setEnabled(False)

    def load_project(self,project):
        self.project=project
        self._loading=True
        for name,edit in self.fields.items():
            edit.setText(getattr(project.settings,name))
        self.generator_port.setValue(project.settings.generator_port)
        self.ip3_generator_port.setValue(project.settings.ip3_generator_port)
        self.noise_ffts.setValue(project.settings.noise_ffts)
        for label,spin in self.test8_ffts.items():
            spin.setValue(project.settings.test8_ffts[label])
        for name,spin in self.dwells.items():
            spin.setValue(getattr(project.settings,name))
        for name,spin in self.levels.items():
            spin.setValue(getattr(project.settings,name))
        self._refresh_cable()
        self._loading=False
        self.status.setText(f'Settings for {project.name}')
        self.setEnabled(True)
        self.validity_changed.emit(True)

    def _edited(self,*_):
        if self.project is None or self._loading:
            return
        old_ip=self.project.settings.dut_ip
        for name,edit in self.fields.items():
            setattr(self.project.settings,name,edit.text().strip())
        self.project.settings.generator_port=self.generator_port.value()
        self.project.settings.ip3_generator_port=self.ip3_generator_port.value()
        self.project.settings.noise_ffts=self.noise_ffts.value()
        self.project.settings.test8_ffts.update({label:spin.value() for label,spin in self.test8_ffts.items()})
        for name,spin in self.dwells.items():
            setattr(self.project.settings,name,spin.value())
        for name,spin in self.levels.items():
            setattr(self.project.settings,name,spin.value())
        if old_ip != self.project.settings.dut_ip:
            old=self.project.prop_auto
            self.project.prop_auto=AutoProps(dut_ip=self.project.settings.dut_ip,
                operator=self.project.settings.operator,cable_calib_path=old.cable_calib_path)
            self.dut_changed.emit()
        self.project.sync_settings()
        self.changed.emit()
        self.validity_changed.emit(bool(self.project.settings.operator and self.project.settings.dut_ip))

    def _refresh_cable(self):
        self.cable_path.setText(self.project.settings.cable_calib_path)
        self.cable_path.setToolTip(self.project.settings.cable_calib_path)
        if self.project.cable_calib_error:
            self.cable_status.setText('Cable calibration unavailable: '+self.project.cable_calib_error)
        elif self.project.cable_calib is not None:
            fs,_=self.project.cable_calib
            self.cable_status.setText(f'{len(fs)} points, {fs[0]:g}–{fs[-1]:g} Hz; frequency correction only.')
        else:
            self.cable_status.setText('No fixed cable offset is applied. Include static loss in the attenuator value.')

    def _select_cable(self):
        if self.project is None:
            return
        filename,_=QFileDialog.getOpenFileName(self,'Select cable calibration',
            self.project.settings.cable_calib_path or str(self.project.root),
            'Cable calibration (*.txt *.csv);;All files (*)')
        if filename:
            self.set_cable_calibration(Path(filename))

    def set_cable_calibration(self,path):
        if self.project is None:
            return
        try:
            self.project.set_cable_calibration(path)
        except (OSError,ValueError,ImportError) as exc:
            QMessageBox.warning(self,'Cable calibration unavailable',str(exc))
            return
        self._refresh_cable()
        self.cable_changed.emit()
        self.changed.emit()

    def _connect(self):
        if self.project is not None:
            self.status.setText('Reading DUT identity…')
            self.connect_requested.emit(self.project.settings.dut_ip)

    def connection_failed(self,message):
        self.status.setText('Connection failed: '+message)

    def connection_complete(self):
        self.status.setText('DUT identity read; device disconnected.')
