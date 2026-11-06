"""Binary calibration transfers over the system OpenSSH client."""
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import shlex
import subprocess
import tempfile
import time
from measurement_control import Aborted, check_abort


class RemoteFileMissing(FileNotFoundError):
    """The requested calibration does not exist on the DUT."""


class SSHTransferError(RuntimeError):
    def __init__(self, returncode, detail):
        super().__init__(f'SSH transfer failed (exit {returncode}): {detail}')
        self.returncode = returncode
        self.detail = detail


@dataclass(frozen=True)
class TransferSettings:
    host: str
    username: str
    remote_dir: str
    key_path: str
    ssh: str = 'ssh'
    port: int = 22
    timeout: float = 120.0
    auto_accept_new_host: bool = True

    def validate(self):
        if not self.host or self.host.startswith('-') or any(c.isspace() for c in self.host):
            raise ValueError('Invalid project DUT IP for SSH.')
        if not self.username or not all(c.isalnum() or c in '._-' for c in self.username):
            raise ValueError('Invalid SSH_USERNAME in connection_cfg.py.')
        if not self.remote_dir.startswith('/') or not all(c.isalnum() or c in '/._-' for c in self.remote_dir):
            raise ValueError('Set SSH_REMOTE_CALIB_DIR to the absolute Linux calibration directory.')
        if not Path(self.key_path).expanduser().is_file():
            raise ValueError(f'SSH private key is missing: {self.key_path}')
        if not self.ssh.strip():
            raise ValueError('Set SSH_EXECUTABLE in connection_cfg.py or add ssh to PATH.')
        if not 1 <= self.port <= 65535 or self.timeout <= 0:
            raise ValueError('Invalid SSH port or transfer timeout.')


class SSHTransfer:
    def __init__(self, settings, cancel=None):
        self.settings = settings
        self.cancel = cancel

    def _remote_path(self, name):
        if (PurePosixPath(name).name != name or name in ('.', '..') or
                not all(c.isalnum() or c in '._-' for c in name)):
            raise ValueError('Invalid calibration filename.')
        return str(PurePosixPath(self.settings.remote_dir) / name)

    def _command(self, remote_command):
        s = self.settings
        return [s.ssh, '-T', '-p', str(s.port),
                '-i', str(Path(s.key_path).expanduser().resolve()),
                '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes',
                '-o', 'StrictHostKeyChecking=' + ('accept-new' if s.auto_accept_new_host else 'yes'),
                '-o', 'ConnectTimeout=5', '-o', 'ConnectionAttempts=1',
                '-o', 'ServerAliveInterval=5', '-o', 'ServerAliveCountMax=2',
                f'{s.username}@{s.host}', remote_command]

    def _run(self, remote_command, *, source=None, target=None):
        check_abort(self.cancel)
        self.settings.validate()
        args = self._command(remote_command)
        with tempfile.TemporaryFile() as errors:
            try:
                process = subprocess.Popen(args, shell=False,
                    stdin=source if source is not None else subprocess.DEVNULL,
                    stdout=target if target is not None else subprocess.DEVNULL,
                    stderr=errors,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            except FileNotFoundError as exc:
                raise RuntimeError('OpenSSH client not found. Install Windows OpenSSH Client or set SSH_EXECUTABLE.') from exc
            start = time.monotonic()
            try:
                while process.poll() is None:
                    check_abort(self.cancel)
                    if time.monotonic() - start > self.settings.timeout:
                        raise TimeoutError('Calibration SSH transfer timed out.')
                    if self.cancel is not None:
                        self.cancel.wait(0.1)
                    else:
                        time.sleep(0.1)
                check_abort(self.cancel)
                if process.returncode:
                    errors.seek(0)
                    detail = errors.read(16384).decode(errors='replace').strip()
                    raise SSHTransferError(process.returncode, detail)
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait()

    def upload(self, local_path):
        path = Path(local_path).resolve()
        # The local Python process opens Windows paths; only the Linux path
        # passes through a remote shell. No local shell or text transcoding.
        remote = shlex.quote(self._remote_path(path.name))
        with path.open('rb') as source:
            self._run(f'cat > {remote}', source=source)

    def download(self, file_name, local_path):
        remote = shlex.quote(self._remote_path(file_name))
        with Path(local_path).open('wb') as target:
            try:
                self._run(f'LC_ALL=C cat {remote}', target=target)
            except SSHTransferError as exc:
                # Match cat's missing-file diagnostic, never a local missing
                # key/client, authentication failure, permissions error or timeout.
                missing = any(line.startswith('cat:') and 'No such file or directory' in line
                              for line in exc.detail.splitlines())
                if exc.returncode != 255 and missing:
                    raise RemoteFileMissing(f'Remote calibration file is missing: {file_name}') from exc
                raise


def upload_calibrations(local_paths, settings, cancel=None):
    transfer = SSHTransfer(settings, cancel)
    for path in local_paths:
        transfer.upload(path)


def download_calibrations(file_names, settings, destination, cancel=None):
    transfer = SSHTransfer(settings, cancel)
    for name in file_names:
        transfer.download(name, Path(destination) / name)
