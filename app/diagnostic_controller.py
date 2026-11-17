"""Diagnostic I/O worker. All device calls, FFTs and spectrum writes stay off the GUI thread."""
from datetime import datetime,timezone
from types import SimpleNamespace
import socket
import shutil
import threading
import time
from uuid import uuid4
from PySide6.QtCore import QThread,Signal
from iz245.scpi_utils import scpi_query
from controller import default_device_factory
from generator_connection import default_generator_factory
from ip3_measurement import default_ip3_generator_factory
from measurement_control import Aborted,check_abort
from run_control import pause_checkpoint
from diagnostic_spectrum import DiagnosticSpectrum,DIAGNOSTIC_DIR,measure_diagnostic_spectrum


class DiagnosticThread(QThread):
    log=Signal(str)
    preview=Signal(object)
    record_ready=Signal(str,object)
    progress=Signal(int)
    paused=Signal(bool)

    def __init__(self,project,operation,*,target='DUT',commands='',options=None,source=None,destination=None,
            device_factory=None,generator_factory=None,ip3_generator_factory=None,parent=None):
        super().__init__(parent)
        self.project,self.operation=project,operation
        self.target,self.commands,self.options,self.source=target,commands,options,source
        self.destination=destination
        self.device_factory=device_factory or default_device_factory
        self.generator_factory=generator_factory or default_generator_factory
        self.ip3_generator_factory=ip3_generator_factory or default_ip3_generator_factory
        self.cancel=threading.Event();self.pause_event=threading.Event()
        self.action={'scpi':'Diagnostic SCPI','capture':'Diagnostic spectrum','load':'Load diagnostic spectra','import':'Import diagnostic spectrum','export':'Export diagnostic spectrum'}[operation]
        self.job=SimpleNamespace(pausable=operation=='capture')
        self.error=None;self.aborted=False;self.transport=None;self.completed=0

    def check_cancel(self):check_abort(self.cancel)
    def checkpoint(self):return pause_checkpoint(self.cancel,self.pause_event,self.paused.emit)

    def _connect(self,target):
        settings=self.project.settings
        self.log.emit(f'Connecting {target}…')
        if target=='DUT':
            if not settings.dut_ip:raise ValueError('Set the DUT address in Settings.')
            self.transport=self.device_factory(settings.dut_ip)
            opened=self.transport.open(tdoa_setting=False)
        else:
            ip=settings.generator_ip if target=='Generator 1' else settings.ip3_generator_ip
            port=settings.generator_port if target=='Generator 1' else settings.ip3_generator_port
            if not ip:raise ValueError(f'Set the {target} address in Settings.')
            factory=self.generator_factory if target=='Generator 1' else self.ip3_generator_factory
            self.transport=factory(ip,port);opened=self.transport.open()
        self.check_cancel()
        if opened is False or not getattr(self.transport,'connected',True):raise ConnectionError(f'Cannot connect to {target}.')
        return self.transport

    def _send_commands(self):
        transport=self._connect(self.target)
        for line in self.commands.splitlines():
            command=line.strip()
            if not command or command.startswith('#'):continue
            self.check_cancel();self.log.emit(f'{self.target} > {command}')
            if self.target=='DUT':
                if '?' in command:self.log.emit(str(transport._main_scpi_query(command)))
                else:transport._main_scpi_command(command)
            elif '?' in command:
                with transport.scpi_lock:response=scpi_query(transport.main_scpi,command)
                self.log.emit(str(response))
            else:transport.cmd(command)
        # Manual diagnostics intentionally keep the requested hardware state.
        self.log.emit('SCPI batch completed.')

    def _save_record(self,result):
        self.check_cancel()
        stamp=datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
        filename=f'{stamp}_{uuid4().hex[:10]}.txt'
        result.save_to_file(self.project.root/DIAGNOSTIC_DIR/filename)
        self.record_ready.emit(filename,result)

    def _capture(self):
        device=self._connect('DUT')
        last_progress=0.
        def progress():
            nonlocal last_progress
            self.completed+=1
            now=time.monotonic()
            if self.completed==self.options.fft_count or now-last_progress>=.5:
                self.progress.emit(self.completed);last_progress=now
        result=measure_diagnostic_spectrum(device,self.options,operator=self.project.settings.operator,
            checkpoint=self.checkpoint,check_cancel=self.check_cancel,
            on_spectrum=self.preview.emit,on_progress=progress,on_status=self.log.emit)
        self._save_record(result)
        self.log.emit(f'Saved {result.name}: {result.ffts} FFT windows, ENBW {result.enbw_hz:g} Hz.')

    def _load(self):
        for path in sorted((self.project.root/DIAGNOSTIC_DIR).glob('*.txt')):
            self.check_cancel()
            try:result=DiagnosticSpectrum.from_file(path)
            except Exception as exc:self.log.emit(f'Cannot load {path.name}: {exc}');continue
            self.record_ready.emit(path.name,result)

    def run(self):
        try:
            self.check_cancel()
            if self.operation=='scpi':self._send_commands()
            elif self.operation=='capture':self._capture()
            elif self.operation=='load':self._load()
            elif self.operation=='import':self._save_record(DiagnosticSpectrum.from_file(self.source))
            elif self.operation=='export':
                shutil.copyfile(self.source,self.destination)
                self.log.emit(f'Exported spectrum: {self.destination}')
        except Aborted:self.aborted=True
        except Exception as exc:
            if self.cancel.is_set():self.aborted=True
            else:self.error=str(exc)
        finally:
            if self.transport is not None:
                try:self.transport.close()
                except Exception as exc:self.log.emit(f'Disconnect: {exc}')

    def abort(self):
        self.cancel.set();self.pause_event.clear()
        # FFTProcessor interrupts the capture socket. SCPI queries need their own wakeup.
        if self.transport is not None:
            stream=getattr(self.transport,'main_scpi',None)
            if stream is not None:
                try:stream.shutdown(socket.SHUT_RDWR)
                except OSError:pass
