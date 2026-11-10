"""Manual template fields and read-only DUT properties.

DUT integration contract:
    connect_requested(ip) -> external controller starts asynchronous I/O
    controller calls set_auto_properties(mapping) or connection_failed(message)
The mapping must belong to the currently loaded project and address. Controllers
must discard stale results and deliver callbacks on Qt's GUI thread.
"""
from ipaddress import ip_address
from PySide6.QtCore import Signal
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QGroupBox, QLineEdit, QLabel, QScrollArea, QPushButton, QPlainTextEdit)
from project import AutoProps, manual_keys, format_manual_key

AUTO_LABELS = {
    "dut_ip": "DUT IP address",
    "serial_number": "Serial number",
    "calibration_temperature": "Calibration temperature",
    "ver_hw": "Hardware version",
    "ver_hw_rf": "RF hardware version",
    "ver_hw_fpga": "FPGA hardware version",
    "ver_fpga": "FPGA version",
    "ver_fw": "Firmware version",
    "cable_calib_path": "Cable calibration",
    "operator": "Operator",
}


class ProjectTab(QWidget):
    changed = Signal()
    validity_changed = Signal(bool)
    connect_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._device_info_ok = False
        self.project = None
        self.fields = {}
        self.template_error = None
        self._connecting = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(14)
        self.notice = QLabel("Create or open a project from the Project menu.")
        self.notice.setWordWrap(True)
        outer.addWidget(self.notice)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        body = QWidget()
        self.body_layout = QVBoxLayout(body)
        self.body_layout.setSpacing(18)
        details = QGroupBox("Project details · manual fields")
        self.form = QFormLayout(details)
        self.form.setContentsMargins(16, 24, 16, 16)
        self.form.setSpacing(12)
        self.form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.body_layout.addWidget(details)
        hw = QGroupBox("Device under test")
        hw_layout = QVBoxLayout(hw)
        hw_layout.setContentsMargins(16, 24, 16, 16)
        hw_layout.setSpacing(12)
        # Connection settings and Connect action live in SettingsTab.
        self.connection_status = QLabel("DUT connection is not configured yet.")
        self.connection_status.setWordWrap(True)
        hw_layout.addWidget(self.connection_status)
        hw_layout.addWidget(QLabel("Automatic properties · read only"))
        self.auto_props_text = QPlainTextEdit()
        self.auto_props_text.setReadOnly(True)
        self.auto_props_text.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.auto_props_text.setMinimumHeight(200)
        self.auto_props_text.setPlaceholderText("DUT properties will appear here.")
        hw_layout.addWidget(self.auto_props_text)
        self.body_layout.addWidget(hw)
        self.body_layout.addStretch()
        scroll.setWidget(body)
        outer.addWidget(scroll)
        self.setEnabled(False)

    def load_project(self, project):
        self._device_info_ok = False
        self.project = project
        self._connecting = False
        while self.form.rowCount():
            self.form.removeRow(0)
        self.fields.clear()
        self.template_error = None
        try:
            keys = manual_keys()
        except Exception as exc:
            keys = []
            self.template_error = str(exc)
        for key in keys:
            edit = QLineEdit(str(project.prop_manual.get(key, "")))
            self.fields[key] = edit
            self.form.addRow(format_manual_key(key), edit)
            edit.textChanged.connect(self._edited)
        self.notice.setText(
            f"Template fields unavailable: {self.template_error}\n"
            "Place template.docx beside app.py and reopen the project."
            if self.template_error else f"Project: {project.name}")
        self.connection_status.setText("Saved values shown below; no live DUT connection confirmed.")
        self._refresh_auto_display()
        self.setEnabled(True)
        self.validity_changed.emit(self.is_valid())

    def is_valid(self):
        return self.project is not None and self._device_info_ok

    def _edited(self, *_):
        if self.project is None:
            return
        self.project.prop_manual.update({key: edit.text() for key, edit in self.fields.items()})
        self.changed.emit()
        self.validity_changed.emit(self.is_valid())

    def invalidate_device(self):
        self._device_info_ok = False
        self.connection_status.setText('DUT address changed; read its identity again in Settings.')
        self._refresh_auto_display()
        self.validity_changed.emit(False)

    def _refresh_auto_display(self):
        data = self.project.prop_auto.to_dict()
        width = max(len(label) for label in AUTO_LABELS.values())
        self.auto_props_text.setPlainText("\n".join(
            f"{AUTO_LABELS[key]:<{width}} : {value or '—'}" for key, value in data.items()))

    def set_auto_properties(self, data):
        """Replace DUT readback after a successful connection; IP remains user-owned.

        data may be AutoProps or a mapping (dut_ip may be omitted). This replaces
        readback fields so omitted values cannot remain stale from a prior query.
        """
        if self.project is None:
            return
        payload = data.to_dict() if isinstance(data, AutoProps) else dict(data)
        current_ip = self.project.prop_auto.dut_ip
        if "dut_ip" in payload and payload["dut_ip"] != current_ip:
            raise ValueError("DUT response address does not match the current project.")
        payload["dut_ip"] = current_ip
        payload.setdefault("cable_calib_path", self.project.prop_auto.cable_calib_path)
        payload.setdefault("operator", self.project.prop_auto.operator)
        automatic = AutoProps.from_dict(payload)
        self.project.prop_auto = automatic
        self._connecting = False
        self._refresh_auto_display()
        self.connection_status.setText(f"Properties received from {current_ip}.")
        self.changed.emit()
        self.validity_changed.emit(self.is_valid())

    def refresh_auto_properties(self):
        """Refresh after the backend has updated the active project itself."""
        if self.project is None:
            return
        self._connecting = False
        self._refresh_auto_display()
        self.connection_status.setText(
            f"Properties read from {self.project.prop_auto.dut_ip}; device disconnected.")
        self._device_info_ok = True
        self.validity_changed.emit(self.is_valid())

    def connection_failed(self, message):
        self._device_info_ok = False
        self.validity_changed.emit(False)
        self._connecting = False
        self.connection_status.setText(f"Connection failed: {message}")
