"""DUT backend. ProjectMenu retains ownership of the active project.

Uses the bundled iz245 package, or an injected device_factory
with the same Device(ip), open(tdoa_setting), device_info(), close() interface.
All device I/O runs in a QThread. Project mutations and notifications run on
Qt's GUI thread after the device has been closed.
"""
from collections.abc import Mapping
from dataclasses import replace
from ipaddress import ip_address
from PySide6.QtCore import QObject, QThread, Signal, Slot
from iz245.device import Device


def default_device_factory(ip):
    return Device(ip)


def properties_from_device_info(info):
    """Map the supplied Device.device_info() output without inventing versions."""
    if not isinstance(info, Mapping):
        raise ValueError("Device info must be a mapping.")
    mapping = {"sn": "serial_number", "HW": "ver_hw",
               "FPGA": "ver_fpga", "FW": "ver_fw"}
    missing = [key for key in mapping if key not in info or
               info[key] is None or not str(info[key]).strip()]
    if missing:
        raise ValueError("Incomplete device info; missing: " + ", ".join(missing))
    return {target: str(info[source]).strip() for source, target in mapping.items()}


class _DeviceInfoThread(QThread):
    def __init__(self, device, parent=None):
        super().__init__(parent)
        self.device = device
        self.updates = None
        self.error = None

    def run(self):
        try:
            if not self.device.open(tdoa_setting=False):
                raise ConnectionError("Device.open() failed; check the address and device availability.")
            self.updates = properties_from_device_info(self.device.device_info())
        except Exception as exc:
            self.error = str(exc) or type(exc).__name__
        finally:
            try:
                self.device.close()
            except Exception as exc:
                cleanup_error = f"Could not disconnect device: {exc}"
                self.error = f"{self.error}; {cleanup_error}" if self.error else cleanup_error


class Controller(QObject):
    """Owns the Device; receives the current project through a provider callable.

    Signals:
        auto_properties_updated: active project's readback has been committed.
        connection_failed: current request failed (no project data was changed).
        busy_changed: hardware I/O started or finished.
        message: informational status, including discarded stale results.
    """
    auto_properties_updated = Signal()
    connection_failed = Signal(str)
    busy_changed = Signal(bool)
    message = Signal(str)

    def __init__(self, project_provider, parent=None, device_factory=None):
        super().__init__(parent)
        self._project_provider = project_provider
        self._device_factory = device_factory or default_device_factory
        self.device = None
        self._thread = None
        self._request_project = None
        self._request_ip = None

    @property
    def busy(self):
        return self._thread is not None

    @Slot(str)
    def connect_device(self, requested_ip):
        """Read identity from the current project's IP and disconnect afterwards."""
        if self.busy:
            self.connection_failed.emit("A DUT request is already running; try again when it finishes.")
            return
        project = self._project_provider()
        if project is None:
            self.connection_failed.emit("No project is open.")
            return
        ip = project.prop_auto.dut_ip.strip()
        try:
            ip_address(ip)
            if requested_ip.strip() != ip:
                raise ValueError("Requested address no longer matches the current project.")
            # The supplied Device constructor does not perform network I/O.
            self.device = self._device_factory(ip)
        except Exception as exc:
            self.connection_failed.emit(str(exc))
            return
        self._request_project = project
        self._request_ip = ip
        self._thread = _DeviceInfoThread(self.device, self)
        self._thread.finished.connect(self._read_finished)
        self.busy_changed.emit(True)
        self._thread.start()

    @Slot()
    def _read_finished(self):
        thread = self._thread
        project = self._request_project
        ip = self._request_ip
        self._thread = None
        self._request_project = None
        self._request_ip = None
        try:
            current = self._project_provider()
            if current is not project or current.prop_auto.dut_ip.strip() != ip:
                self.message.emit("DUT response discarded because the active project or IP changed.")
                return
            if thread.error:
                self.connection_failed.emit(thread.error)
                return
            # Preserve temperature and separate hardware fields not returned by *IDN?.
            project.prop_auto = replace(project.prop_auto, **thread.updates)
            self.auto_properties_updated.emit()
            self.message.emit(f"Device info read from {ip}; device disconnected.")
        finally:
            thread.deleteLater()
            self.busy_changed.emit(False)
