"""Run with: python -m unittest -v test_calibration.py"""
import os
import io
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
import calib_controller as backend_module
from calib import CalibrationMeasurement
from calib_controller import CalibrationController, measured
from ssh_utils import Aborted, TransferSettings, PuttyTransfer


class Device:
    connected = False
    def __init__(self, ip='test'):
        self.ip, self.calls = ip, []
    def open(self, tdoa_setting):
        self.calls.append(('open', tdoa_setting))
        self.connected = True
        return True
    def close(self):
        self.connected = False
    def _main_scpi_commands(self, cmds):
        self.calls.append(tuple(cmds))
    def _main_scpi_command(self, cmd):
        self.calls.append(cmd)
    def measure_point_rms(self, f, dwell):
        self.calls.append((f, dwell))
        return f / 1e6


class Generator(Device):
    def tune(self, f):
        self.calls.append(f)
    def cmd(self, cmd):
        self.calls.append(cmd)


class Transfer:
    def __init__(self):
        self.settings = SimpleNamespace(validate=lambda: None)
        self.uploaded = []
        self.download_data = None
    def upload(self, path):
        self.uploaded.append(Path(path).name)
    def download(self, name, target):
        Path(target).write_bytes(self.download_data)


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.prj = SimpleNamespace(root=Path(self.tmp.name), prop_auto=SimpleNamespace(calibration_temperature='24'))
        self.names = ['first.txt', 'pres.txt', 'second.txt']
        self.cfg = {n: (np.array([100000, 1000000]), ['sys:cal:off']) for n in self.names}
        for attr, value in [('CFG_CALIB_ALL', self.cfg), ('CFG_CALIB_CH1', {self.names[0]: self.cfg[self.names[0]]}),
                            ('CFG_CALIB_PRESS', {self.names[1]: self.cfg[self.names[1]]}),
                            ('CFG_CALIB_CH2', {self.names[2]: self.cfg[self.names[2]]})]:
            patcher = patch.object(backend_module, attr, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.events, self.progress = [], []
        self.transfer = Transfer()
        self.controller = CalibrationController(Device(), Generator(), self.prj,
            transfer=self.transfer, completed=lambda n, cm: self.events.append((n, cm)),
            progress=lambda d, t: self.progress.append((d, t)), dwell_sec=0.05)

    def test_measure_saves_axis_and_publishes_complete_data(self):
        self.controller.run('measure', self.names[0])
        cm = CalibrationMeasurement.from_file(self.controller.path(self.names[0]))
        self.assertTrue(measured(cm))
        np.testing.assert_array_equal(cm.freq_hz, [100000, 1000000])
        self.assertEqual(cm.temperature, '24')
        self.assertTrue(cm.datetime)
        self.assertEqual(self.progress[-1], (2, 2))
        self.assertEqual(len(self.events), 1)
        self.assertIn((100000, 0.05), self.controller.dev.calls)

    def test_abort_keeps_previous_file(self):
        self.controller.run('measure', self.names[0])
        path = self.controller.path(self.names[0])
        old = path.read_bytes()
        self.events.clear()
        self.controller.progress = lambda d, t: self.controller.cancel.set() if d == 1 else None
        with self.assertRaises(Aborted):
            self.controller.run('measure', self.names[0])
        self.assertEqual(path.read_bytes(), old)
        self.assertEqual(self.events, [])

    def test_ch1_pipeline_stages_publish_then_upload_and_reset(self):
        resets = []
        def reset():
            resets.append(list(self.transfer.uploaded))
            self.controller._advance()
        self.controller.reset_and_connect = reset
        self.controller.run('ch1')
        self.assertEqual([n for n, _ in self.events], self.names[:2])
        self.assertEqual(self.transfer.uploaded, self.names[:2])
        self.assertEqual(resets, [[self.names[0]], self.names[:2]])
        self.assertEqual(self.progress[-1], (8, 8))
        self.assertFalse(self.controller.path(self.names[2]).exists())

    def test_invalid_download_preserves_previous(self):
        self.controller.run('measure', self.names[0])
        path = self.controller.path(self.names[0])
        old = path.read_bytes()
        self.transfer.download_data = b'freq[Hz];Limit[dB];\n100000;;\n'
        with self.assertRaises(ValueError):
            self.controller.run('download', self.names[0])
        self.assertEqual(path.read_bytes(), old)
        self.assertFalse(path.with_name(path.name + '.download').exists())

    def test_successful_download_publishes_and_upload_is_transfer_only(self):
        self.controller.run('measure', self.names[0])
        self.transfer.download_data = self.controller.path(self.names[0]).read_bytes()
        self.controller.run('download', self.names[1])
        self.assertTrue(measured(self.controller.calibrations[self.names[1]]))
        calls = list(self.controller.dev.calls)
        self.controller.run('upload', self.names[1])
        self.assertEqual(calls, self.controller.dev.calls)
        self.assertEqual(self.transfer.uploaded, [self.names[1]])

    def test_download_all_updates_each_file_and_progress(self):
        self.controller.run('measure', self.names[0])
        self.transfer.download_data = self.controller.path(self.names[0]).read_bytes()
        self.events.clear()
        self.controller.run('download_all')
        self.assertEqual([name for name, cm in self.events], self.names)
        self.assertEqual(self.progress[-1], (3, 3))
        self.assertTrue(all(measured(cm) for cm in self.controller.calibrations.values()))

    def test_abort_download_all_preserves_completed_files(self):
        self.controller.run('measure', self.names[0])
        self.transfer.download_data = self.controller.path(self.names[0]).read_bytes()
        self.events.clear()
        self.controller.progress = lambda done, total: self.controller.cancel.set() if done == 1 else None
        with self.assertRaises(Aborted):
            self.controller.run('download_all')
        self.assertEqual([name for name, cm in self.events], self.names[:1])
        self.assertFalse(self.controller.path(self.names[1]).exists())

    def test_incomplete_or_nonfinite_data_not_available(self):
        for values in (None, np.array([1]), np.array([1, np.nan])):
            cm = CalibrationMeasurement(freq_hz=np.array([1, 2]), limit_dB=values, available=True)
            self.assertFalse(measured(cm))

    def test_reconnect_retries_false_results_and_passes_open_argument(self):
        class InstantEvent:
            def is_set(self): return False
            def wait(self, seconds): return False
        self.controller.cancel = InstantEvent()
        with patch.object(self.controller.dev, 'open', side_effect=[False, True]) as opening:
            self.controller.reset_and_connect()
        self.assertEqual(opening.call_count, 2)
        opening.assert_called_with(tdoa_setting=False)

    def test_corrupt_local_file_does_not_block_other_rows(self):
        path = self.controller.path(self.names[0])
        path.parent.mkdir()
        path.write_text('broken')
        self.controller.reload()
        self.assertIn(self.names[0], self.controller.errors)
        self.assertFalse(measured(self.controller.calibrations[self.names[0]]))


class TransferTests(unittest.TestCase):
    def test_first_host_prompt_receives_yes_and_changed_key_does_not(self):
        class Input(io.BytesIO):
            sent = b''
            def write(self, value):
                self.sent += value
                return super().write(value)
        class Process:
            returncode = None
            def __init__(self, output, prompt):
                self.stdin = Input()
                self.output, self.prompt, self.count = output, prompt, 0
                self.killed = False
            def poll(self):
                self.count += 1
                if self.count == 1:
                    self.output.write(self.prompt)
                    self.output.flush()
                    return None
                if self.stdin.sent:
                    self.returncode = 0
                    return 0
                return None
            def kill(self):
                self.killed = True
                self.returncode = -1
            def wait(self): return self.returncode
        settings = TransferSettings('host', 'root', '/calib', __file__, auto_accept_new_host=True)
        for prompt, should_accept in [
            (b'The host key is not cached for this server.\nStore key in cache? (y/n) ', True),
            (b'WARNING - POTENTIAL SECURITY BREACH! The host key does not match the one PuTTY has cached.', False),
        ]:
            processes = []
            def spawn(args, **kwargs):
                self.assertNotIn('-batch', args)
                process = Process(kwargs['stdout'], prompt)
                processes.append(process)
                return process
            with patch('ssh_utils.subprocess.Popen', side_effect=spawn):
                if should_accept:
                    PuttyTransfer(settings).upload(__file__)
                else:
                    with self.assertRaisesRegex(RuntimeError, 'host key changed'):
                        PuttyTransfer(settings).upload(__file__)
            self.assertEqual(processes[0].stdin.sent, b'y\n' if should_accept else b'')
            if not should_accept:
                self.assertTrue(processes[0].killed)

    def test_transfer_process_abort(self):
        cancel = threading.Event()
        settings = TransferSettings('host', 'user', '/calib', __file__, 'fingerprint')
        transfer = PuttyTransfer(settings, cancel)
        class Process:
            returncode = None
            stdin = None
            killed = False
            def poll(self):
                cancel.set()
                return None
            def kill(self): self.killed = True
            def wait(self): return -1
        process = Process()
        with patch('ssh_utils.subprocess.Popen', return_value=process):
            with self.assertRaises(Aborted):
                transfer.upload(__file__)
        self.assertTrue(process.killed)


if __name__ == '__main__':
    unittest.main()
