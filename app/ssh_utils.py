"""Windows/Linux PuTTY transfers. Keys stay in their original .ppk format."""
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import subprocess
import tempfile
import time


class Aborted(RuntimeError):
    pass


def check_abort(cancel):
    if cancel is not None and cancel.is_set():
        raise Aborted("Aborted by operator")


@dataclass(frozen=True)
class TransferSettings:
    host: str
    username: str
    remote_dir: str
    key_path: str
    host_key: str = ""
    pscp: str = "pscp.exe"
    port: int = 22
    timeout: float = 120.0
    auto_accept_new_host: bool = False

    def validate(self):
        if not self.host or self.host.startswith('-') or any(c.isspace() for c in self.host):
            raise ValueError("Invalid project DUT IP for SSH.")
        if not self.username or not all(c.isalnum() or c in '._-' for c in self.username):
            raise ValueError("Invalid SSH_USERNAME in connection_cfg.py.")
        # Restrict remote shell syntax because pscp may fall back to SCP.
        if not self.remote_dir.startswith('/') or not all(c.isalnum() or c in '/._-' for c in self.remote_dir):
            raise ValueError("Set SSH_REMOTE_CALIB_DIR in connection_cfg.py to the absolute Linux calibration directory.")
        if not Path(self.key_path).is_file():
            raise ValueError(f"Packaged PuTTY private key is missing: {self.key_path}")
        if not self.host_key.strip() and not self.auto_accept_new_host:
            raise ValueError("Enter the DUT SSH host-key fingerprint verified with your administrator.")
        if not self.pscp.strip():
            raise ValueError("Set PSCP_EXECUTABLE in connection_cfg.py or add pscp.exe to PATH.")
        if not 1 <= self.port <= 65535 or self.timeout <= 0:
            raise ValueError("Invalid SSH port or transfer timeout.")


class PuttyTransfer:
    def __init__(self, settings, cancel=None):
        self.settings = settings
        self.cancel = cancel

    def _remote(self, name):
        if PurePosixPath(name).name != name or not all(c.isalnum() or c in '._-' for c in name):
            raise ValueError("Invalid calibration filename.")
        s = self.settings
        return f"{s.username}@{s.host}:{s.remote_dir.rstrip('/')}/{name}"

    def _run(self, source, target):
        check_abort(self.cancel)
        s = self.settings
        s.validate()
        args = [s.pscp, '-P', str(s.port), '-i', s.key_path]
        accept_new = s.auto_accept_new_host and not s.host_key
        if s.host_key:
            args.extend(['-batch', '-hostkey', s.host_key])
        elif not accept_new:
            args.append('-batch')
        args.extend([source, target])
        # Separate file handles let us read prompts without moving the child
        # process's output offset, and avoid pipe deadlocks on Windows.
        with tempfile.TemporaryDirectory(prefix='calibration-transfer-') as folder:
            log_path = Path(folder) / 'pscp.log'
            with log_path.open('wb') as output:
                process = subprocess.Popen(args,
                    stdin=subprocess.PIPE if accept_new else subprocess.DEVNULL,
                    stdout=output, stderr=subprocess.STDOUT,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                start = time.monotonic()
                accepted = False
                try:
                    while process.poll() is None:
                        check_abort(self.cancel)
                        if time.monotonic() - start > s.timeout:
                            raise TimeoutError("Calibration transfer timed out.")
                        if accept_new and not accepted:
                            with log_path.open('rb') as reader:
                                text = reader.read(65536).decode(errors='replace').lower()
                            # Accept only a new-host prompt. Changed cached keys
                            # never receive an automatic yes.
                            if ('potential security breach' in text or
                                'does not match the one putty has cached' in text):
                                raise RuntimeError("DUT SSH host key changed from the cached key.")
                            if ('host key is not cached' in text and '(y/n' in text):
                                process.stdin.write(b'y\n')
                                process.stdin.flush()
                                process.stdin.close()
                                accepted = True
                        if self.cancel is not None:
                            self.cancel.wait(0.1)
                        else:
                            time.sleep(0.1)
                    check_abort(self.cancel)
                    if process.returncode:
                        with log_path.open('rb') as reader:
                            detail = reader.read(8192).decode(errors='replace').strip()
                        raise RuntimeError(f"PuTTY transfer failed: {detail}")
                finally:
                    if process.poll() is None:
                        process.kill()
                    process.wait()
                    if process.stdin is not None and not process.stdin.closed:
                        process.stdin.close()

    def upload(self, local_path):
        path = Path(local_path).resolve()
        self._run(str(path), self._remote(path.name))

    def download(self, file_name, local_path):
        self._run(self._remote(file_name), str(Path(local_path).resolve()))


def upload_calibrations(local_paths, settings, cancel=None):
    transfer = PuttyTransfer(settings, cancel)
    for path in local_paths:
        transfer.upload(path)


def download_calibrations(file_names, settings, destination, cancel=None):
    transfer = PuttyTransfer(settings, cancel)
    for name in file_names:
        transfer.download(name, Path(destination) / name)
