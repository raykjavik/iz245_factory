"""Finite Device captures, a bounded FFT queue, and throttled Qt notifications.

Debug prints are enabled by default; pass debug=False to disable all debug scans.
This version preserves the existing capture sizes and FFT calculations.

Call FFTProcessor.run() from a measurement QThread, never the GUI thread.
Capture callbacks only copy/enqueue IQ. The FFT thread averages linear values;
spectrum_updated crosses to the GUI through the application's queued signals.
"""
from dataclasses import dataclass
from queue import Queue, Empty, Full
import socket
import threading
import time
import traceback
import numpy as np
from PySide6.QtCore import QObject, Signal


def hann_window(count):
    return .5 - .5 * np.cos(2 * np.pi * np.arange(count) / count)


def two_sided_psd(iq, sample_rate_hz):
    """Complex IQ density in sample-units²/Hz, negative and positive offsets."""
    iq = np.asarray(iq)
    window = hann_window(iq.size)
    density = np.abs(np.fft.fft(iq * window))**2 / (sample_rate_hz * np.sum(window**2))
    return (np.fft.fftshift(np.fft.fftfreq(iq.size, 1 / sample_rate_hz)),
            np.fft.fftshift(density))


def one_sided_psd(samples, sample_rate_hz):
    """Real-signal density in sample-units²/Hz; interior bins doubled.

    Complex IQ must use two_sided_psd: discarding its negative side loses data.
    """
    samples = np.asarray(samples)
    if np.iscomplexobj(samples):
        raise ValueError('one_sided_psd expects real samples, not complex IQ.')
    window = hann_window(samples.size)
    density = np.abs(np.fft.rfft(samples * window))**2 / (sample_rate_hz * np.sum(window**2))
    density[1:-1 if samples.size % 2 == 0 else None] *= 2
    return np.fft.rfftfreq(samples.size, 1 / sample_rate_hz), density


def power_spectrum(iq, sample_rate_hz):
    """Two-sided linear power in each Hann ENBW, in sample-units².

    This is PSD times ENBW (1.5*fs/N), not dBm. Absolute power needs the
    receiver header calibration; do not sum these bins for integrated power.
    """
    frequency, density = two_sided_psd(iq, sample_rate_hz)
    window = hann_window(np.asarray(iq).size)
    enbw = sample_rate_hz * np.sum(window**2) / np.sum(window)**2
    return frequency, density * enbw


@dataclass(frozen=True)
class FFTAverage:
    frequency_hz: np.ndarray
    values: tuple[np.ndarray, ...]  # One mean per output of the transform.
    completed: int


def iq_debug_summary(iq):
    """Scan only for debugging. Do not alter, replace or skip any IQ samples."""
    iq = np.asarray(iq).reshape(-1)
    if not iq.size:
        return 'empty frame'
    zeros = iq == 0
    count = int(np.count_nonzero(zeros))
    first = int(np.argmax(zeros)) if count else None
    last = int(iq.size-1-np.argmax(zeros[::-1])) if count else None
    leading = int(np.argmin(zeros)) if count < iq.size else int(iq.size)
    trailing = int(np.argmin(zeros[::-1])) if count < iq.size else int(iq.size)
    nonfinite = int(iq.size-np.count_nonzero(np.isfinite(iq)))
    return (
        f'size={iq.size} dtype={iq.dtype} zeros={count} '
        f'first_zero={first} last_zero={last} '
        f'leading_zeros={leading} trailing_zeros={trailing} nonfinite={nonfinite} '
        f'I_min/max=({np.min(iq.real):g},{np.max(iq.real):g}) '
        f'Q_min/max=({np.min(iq.imag):g},{np.max(iq.imag):g}) '
        f'head={iq[:4].tolist()} tail={iq[-4:].tolist()}'
    )


class FFTProcessor(QObject):
    spectrum_updated = Signal(object)
    progress = Signal(int)

    def __init__(self, device, *, window_samples, fft_count, overlap=.5,
                 sample_rate_hz, transform=two_sided_psd, update_interval=.5,
                 batch_ffts=16, queue_frames=4, capture_buffer_bytes=64*1024**2,
                 parent=None, debug=True):
        super().__init__(parent)
        self.device = device
        self.n, self.count = int(window_samples), int(fft_count)
        self.overlap, self.fs = float(overlap), float(sample_rate_hz)
        self.hop = self.n - int(self.n*self.overlap)
        if self.n < 3 or self.count < 1 or not 0 <= self.overlap < 1 or self.fs <= 0:
            raise ValueError('Invalid FFT size, count, overlap or sampling rate.')
        max_samples = max(self.n, int(capture_buffer_bytes)//np.dtype(np.complex64).itemsize)
        self.batch_ffts = max(1, min(int(batch_ffts),1+(max_samples-self.n)//self.hop))
        self.queue_frames = max(1,int(queue_frames))
        self.transform = transform
        self.update_interval = max(.5,float(update_interval))
        self.result = None
        self.debug = bool(debug)
        self._print_lock = threading.Lock()
        self._debug_origin = time.monotonic()

    def _debug(self, text):
        if self.debug:
            with self._print_lock:
                elapsed = time.monotonic()-self._debug_origin
                print(f'[FFT {id(self):x} +{elapsed:.3f}s '
                      f'{threading.current_thread().name}] {text}',flush=True)

    def run(self, *, checkpoint=lambda:None, check_cancel=lambda:None,
            on_average=lambda average:None, on_progress=lambda:None):
        """Call from a measurement worker, not the GUI thread.

        Original finite batching is preserved, including a shorter final batch.
        Receive callbacks copy/enqueue IQ; a separate thread calculates FFTs.
        Debugging scans the copied frames on receipt and again before FFT.
        It adds overhead: use debug=False after diagnosing the problem.
        """
        frames = Queue(maxsize=self.queue_frames)
        errors = Queue()
        stopped,received = threading.Event(),threading.Event()
        self.result = None
        self._debug_origin = time.monotonic()
        processed,enqueued = [0],[0]
        capture_context = {}
        self._debug(
            f'RUN start n={self.n} count={self.count} overlap={self.overlap} '
            f'hop={self.hop} fs={self.fs:g} batch_ffts={self.batch_ffts} '
            f'queue_frames={self.queue_frames} '
            f'sample_bytes={getattr(self.device,"sample_bytes",None)} '
            f'transform={getattr(self.transform,"__name__",type(self.transform).__name__)}')

        def enqueue(frame):
            if stopped.is_set():
                raise RuntimeError('Capture stopped')
            # Make the exact copy that will be consumed by the FFT worker.
            owned = np.array(frame,dtype=np.complex64,copy=True)
            frame_id = enqueued[0]
            batch = capture_context['batch']
            local_id = frame_id-capture_context['first_frame']
            offset = local_id*self.hop
            header = getattr(self.device,'header',None)
            header_snapshot = {key:getattr(header,key,None) for key in (
                'magic','version','data_type','data_subtype','packet_counter',
                'sample_count','center_freq','sample_rate','filter_BW',
                'full_scale_definition_constant','full_range_peak_dBm',
                'receiver_status','time_stamp')}
            context = dict(frame_id=frame_id,batch=batch,window=local_id,
                           offset=offset,header=header_snapshot)
            if self.debug:
                self._debug(
                    f'RX frame={frame_id} batch={batch} window={local_id} '
                    f'sample_range=[{offset},{offset+self.n}) '
                    f'queue_before={frames.qsize()} {iq_debug_summary(owned)}')
                self._debug(f'RX frame={frame_id} HEADER {header_snapshot} '
                            f'sample_bytes={getattr(self.device,"sample_bytes",None)}')
            warned = False
            while not stopped.is_set():
                try:
                    frames.put((context,owned),timeout=.05)
                    enqueued[0] += 1
                    self._debug(f'QUEUED frame={frame_id} enqueued={enqueued[0]} '
                                f'queue_now={frames.qsize()}')
                    return
                except Full:
                    if not warned:
                        self._debug(f'QUEUE FULL frame={frame_id}; waiting for FFT worker')
                        warned = True
            raise RuntimeError('Capture stopped')

        def receive():
            try:
                remaining,batch = self.count,0
                while remaining and not stopped.is_set():
                    self._debug(f'BATCH {batch} checkpoint remaining={remaining} '
                                f'processed={processed[0]} enqueued={enqueued[0]}')
                    checkpoint()
                    check_cancel()
                    if stopped.is_set():
                        break
                    if remaining == self.count:
                        self._debug('CAPTURE selecting LINEAR mode')
                        self.device.set_linear_mode()
                    count = min(remaining,self.batch_ffts)
                    samples = self.n+(count-1)*self.hop
                    capture_context.update(batch=batch,first_frame=enqueued[0])
                    buffer = np.empty(samples,dtype=np.complex64)
                    self._debug(
                        f'BATCH {batch} REQUEST windows={count} IQ_samples={samples} '
                        f'SEND_components={2*samples} buffer_bytes={buffer.nbytes} '
                        f'expected_payload_bytes={samples*getattr(self.device,"sample_bytes",8)}')
                    self.device.request_capture(samples)
                    self._debug(f'BATCH {batch} READ start')
                    started = time.monotonic()
                    self.device.read_capture_perpartes(
                        clb=enqueue,write_buffer=buffer,n=self.n,
                        cnt=count,overlap=self.overlap)
                    remaining -= count
                    self._debug(f'BATCH {batch} READ returned elapsed={time.monotonic()-started:.3f}s '
                                f'remaining={remaining} processed={processed[0]} enqueued={enqueued[0]}')
                    if enqueued[0] != self.count-remaining:
                        raise RuntimeError('Capture callback returned an unexpected number of windows.')
                    self._debug(f'BATCH {batch} waiting for FFT drain target={self.count-remaining}')
                    while processed[0] < self.count-remaining and not stopped.wait(.01):
                        pass
                    self._debug(f'BATCH {batch} drain ended processed={processed[0]} '
                                f'stopped={stopped.is_set()}')
                    batch += 1
            except BaseException as exc:
                # Log original traceback here; do not mask it with a new error.
                self._debug(f'RECEIVE ERROR {type(exc).__name__}: {exc}\n{traceback.format_exc()}')
                errors.put(exc)
                stopped.set()
            finally:
                received.set()
                self._debug('RECEIVE worker exited')

        def calculate():
            context = None
            try:
                totals = None
                completed = 0
                last_update = time.monotonic()
                while not stopped.is_set():
                    try:
                        context,frame = frames.get(timeout=.05)
                    except Empty:
                        if received.is_set():
                            break
                        continue
                    check_cancel()
                    if self.debug:
                        self._debug(
                            f'FFT START frame={context["frame_id"]} batch={context["batch"]} '
                            f'window={context["window"]} completed_before={completed} '
                            f'queue_now={frames.qsize()} {iq_debug_summary(frame)}')
                    started = time.monotonic()
                    frequency,*values = self.transform(frame,self.fs)
                    self._debug(f'FFT TRANSFORM OK frame={context["frame_id"]} '
                                f'elapsed={time.monotonic()-started:.3f}s '
                                f'frequency_bins={len(frequency)} outputs={len(values)}')
                    check_cancel()
                    if stopped.is_set():
                        break
                    if totals is None:
                        totals = [np.array(value,dtype=np.float64,copy=True) for value in values]
                    else:
                        for total,value in zip(totals,values):
                            total += value
                    completed += 1
                    on_progress()
                    self.progress.emit(completed)
                    now = time.monotonic()
                    if completed == self.count or now-last_update >= self.update_interval:
                        average = FFTAverage(np.array(frequency,copy=True),
                            tuple(total/completed for total in totals),completed)
                        self.result = average
                        self._debug(f'PUBLISH average completed={completed}/{self.count}')
                        on_average(average)
                        self.spectrum_updated.emit(average)
                        last_update = now
                    processed[0] = completed
                    self._debug(f'FFT DONE frame={context["frame_id"]} '
                                f'completed={completed}/{self.count}')
                if completed != self.count and not stopped.is_set():
                    raise RuntimeError(f'Capture returned {completed}/{self.count} FFT windows.')
            except BaseException as exc:
                self._debug(f'FFT ERROR context={context} '
                            f'{type(exc).__name__}: {exc}\n{traceback.format_exc()}')
                errors.put(exc)
                stopped.set()
            finally:
                self._debug('FFT worker exited')

        reader = threading.Thread(target=receive,name='IQ capture',daemon=True)
        fft = threading.Thread(target=calculate,name='FFT averaging',daemon=True)
        reader.start()
        fft.start()
        try:
            while reader.is_alive() or fft.is_alive():
                check_cancel()
                if not errors.empty():
                    raise errors.get()
                reader.join(.025)
                fft.join(.025)
            if not errors.empty():
                raise errors.get()
            check_cancel()
            self._debug(f'RUN SUCCESS processed={processed[0]} enqueued={enqueued[0]}')
            return self.result
        finally:
            stopped.set()
            self._debug(f'CLEANUP reader_alive={reader.is_alive()} fft_alive={fft.is_alive()}')
            if reader.is_alive():
                capture_socket = getattr(self.device,'capture_socket',None)
                if capture_socket is not None:
                    try:
                        self._debug('CLEANUP shutting down capture socket to interrupt receive')
                        capture_socket.shutdown(socket.SHUT_RDWR)
                    except OSError as exc:
                        self._debug(f'CLEANUP socket shutdown: {exc}')
            reader.join()
            fft.join()
            self._debug(f'CLEANUP complete processed={processed[0]} enqueued={enqueued[0]}')


from scipy.signal import detrend

class NoiseDensityEstimator:
    def __init__(self,window_samples,fs):
        self.n=int(window_samples)
        self.fs=float(fs)
        if self.n<3 or not np.isfinite(self.fs) or self.fs<=0:
            raise ValueError('Noise density needs at least 3 samples and a positive sample rate.')
        n=np.arange(self.n)
        self.window=0.5-0.5*np.cos(2*np.pi*n/self.n)
        self.normalization=self.fs*np.sum(self.window**2)
        frequency=np.fft.rfftfreq(self.n,d=1/self.fs)
        self.keep=(frequency>0)&(frequency<self.fs/2)
        self.frequency=frequency[self.keep]

    def densities(self,iq):
        iq=np.asarray(iq,dtype=np.complex128)
        if iq.ndim!=1 or iq.size!=self.n or not np.all(np.isfinite(iq)):
            raise ValueError('IQ must be a finite one-dimensional complete window.')
        amplitude=np.abs(iq)
        if np.any(amplitude==0):
            raise ValueError('Phase is undefined for zero-magnitude IQ samples.')
        phase=detrend(np.unwrap(np.angle(iq)),type='linear')
        fractional_amplitude=amplitude/amplitude.mean()-1
        phase_fft=np.fft.rfft(phase*self.window)
        amplitude_fft=np.fft.rfft(fractional_amplitude*self.window)
        # SSB = one-sided real fluctuation PSD / 2, for non-endpoint bins.
        return (np.abs(phase_fft[self.keep])**2/self.normalization,
                np.abs(amplitude_fft[self.keep])**2/self.normalization)


def to_dbc_hz(density):
    with np.errstate(divide='ignore'):
        return 10*np.log10(density)


def phase_amplitude_noise_iq(iq,fs):
    """Single-window API matching the supplied calculation."""
    estimator=NoiseDensityEstimator(np.asarray(iq).size,fs)
    phase,amplitude=estimator.densities(iq)
    return estimator.frequency,to_dbc_hz(phase),to_dbc_hz(amplitude)

