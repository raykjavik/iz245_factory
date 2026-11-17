"""Diagnostic spectra: calibrated density, display conversions and text persistence."""
from dataclasses import dataclass,field,replace
from datetime import datetime,timezone
from pathlib import Path
import numpy as np
from measurement import ENCODING
from cfg_common import DBM_TO_DBUV_50_OHM
import cfg_test8
from measurement_specs import IFSpectrumSpec
from spectrum_display import min_max_envelope

DIAGNOSTIC_DIR='diagnostics'
DISPLAY_UNITS=('dBµV','dBm','dB')
DISPLAY_LABELS=('RMS dBµV','P [dBm] (50 Ω)','NF [dB] (density − (−174))')


@dataclass
class DiagnosticSpectrum:
    name: str='Spectrum'
    offset_hz: np.ndarray=field(default_factory=lambda:np.array([]))
    density_dbm_hz: np.ndarray=field(default_factory=lambda:np.array([]))
    sample_rate_hz: float=0.
    window_samples: int=65536
    overlap: float=.5
    ffts: int=0
    carrier_hz: float=0.
    bandwidth_hz: float=0.
    datetime: str=''
    operator: str=''

    @property
    def enbw_hz(self):
        # Periodic Hann, identical to FFTProcessor.power_spectrum used by Test8.
        return 1.5*self.sample_rate_hz/self.window_samples

    def levels(self,unit):
        if unit=='dBm/Hz':return np.asarray(self.density_dbm_hz)
        if unit=='dB':return np.asarray(self.density_dbm_hz)+174.0
        if unit not in DISPLAY_UNITS:raise ValueError(f'Unknown spectrum unit: {unit}')
        if self.enbw_hz<=0:raise ValueError('Spectrum has no valid sampling rate/window size.')
        power=np.asarray(self.density_dbm_hz)+10*np.log10(self.enbw_hz)
        return power+DBM_TO_DBUV_50_OHM if unit=='dBµV' else power

    def preview(self):
        frequency,values=min_max_envelope(self.offset_hz,self.density_dbm_hz)
        return replace(self,offset_hz=frequency,density_dbm_hz=values)

    def save_to_file(self,path):
        path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
        temporary=path.with_name(path.name+'.tmp')
        comments={'FORMAT':'diagnostic-spectrum-v1','NAME':self.name,'UNIT':'dBm/Hz',
            'DATETIME_UTC':self.datetime,'OPERATOR':self.operator,'CARRIER_HZ':self.carrier_hz,
            'BANDWIDTH_HZ':self.bandwidth_hz,'SAMPLE_RATE_HZ':self.sample_rate_hz,
            'WINDOW_SAMPLES':self.window_samples,'OVERLAP':self.overlap,'FFTS':self.ffts,
            'WINDOW':'periodic Hann','ENBW_HZ':self.enbw_hz,'AVERAGING':'linear power'}
        try:
            with temporary.open('w',encoding=ENCODING) as stream:
                for key,value in comments.items():stream.write(f'#!{key}: {value}\n')
                stream.write('offset[Hz];Density[dBm/Hz];\n')
                np.savetxt(stream,np.column_stack((self.offset_hz,self.density_dbm_hz)),delimiter=';',fmt='%.15g')
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    @classmethod
    def from_file(cls,path):
        path=Path(path);comments={};rows=[]
        with path.open(encoding=ENCODING) as stream:
            for line in stream:
                if line.startswith('#!'):
                    key,value=line[2:].split(':',1);comments[key.strip()]=value.strip()
                elif line.strip() and not line.startswith('offset['):rows.append([float(v) for v in line.split(';')[:2]])
        diagnostic=comments.get('FORMAT')=='diagnostic-spectrum-v1' and comments.get('UNIT')=='dBm/Hz'
        if_power=(comments.get('UNIT')=='dBm' and
            comments.get('SPECTRUM')=='two-sided Hann power spectrum; fftshift')
        if not diagnostic and not if_power:
            raise ValueError('Select a saved diagnostic or calibrated Test8 spectrum (.txt).')
        data=np.asarray(rows,dtype=float)
        if data.ndim!=2 or data.shape[1]!=2 or not len(data):raise ValueError('Spectrum contains no data.')
        result=cls(name=comments.get('NAME',path.stem),offset_hz=data[:,0],density_dbm_hz=data[:,1],
            sample_rate_hz=float(comments['SAMPLE_RATE_HZ']),window_samples=int(comments['WINDOW_SAMPLES']),
            overlap=float(comments['OVERLAP']),ffts=int(comments['FFTS']),
            carrier_hz=float(comments['CARRIER_HZ']),bandwidth_hz=float(comments.get('BANDWIDTH_HZ',comments.get('IF_BANDWIDTH_HZ',0.))),
            datetime=comments.get('DATETIME_UTC',''),operator=comments.get('OPERATOR',''))
        if result.sample_rate_hz<=0 or result.window_samples<3 or result.ffts<1 or not 0<=result.overlap<1:
            raise ValueError('Spectrum has invalid acquisition metadata.')
        if if_power:
            result.density_dbm_hz=result.density_dbm_hz-10*np.log10(result.enbw_hz)
            if comments.get('DATE') and comments.get('TIME_UTC'):
                result.datetime=datetime.strptime(comments['DATE']+' '+comments['TIME_UTC'],'%d/%m/%Y %H:%M:%S').isoformat()
        return result


@dataclass(frozen=True)
class CaptureOptions:
    name: str='Spectrum'
    window_samples: int=65536
    fft_count: int=100
    overlap: float=.5
    iq_bits: str='Auto'
    bandwidth_hz: float=20e6
    carrier_hz: float=500e6


def measure_diagnostic_spectrum(device,options,*,operator='',checkpoint=lambda:None,
        check_cancel=lambda:None,on_spectrum=lambda result:None,on_progress=lambda:None,
        on_status=lambda text:None):
    """Apply BAND and await completion; Test8 applies FREQ with awaited tuning."""
    checkpoint();check_cancel()
    on_status(f'Setting BAND {options.bandwidth_hz:g} Hz…')
    device._main_scpi_command(f'BAND {options.bandwidth_hz:g}')
    response=device._main_scpi_query('*OPC?').strip()
    if response!='1':raise RuntimeError(f'Unexpected BAND *OPC? response: {response!r}')
    check_cancel()
    bandwidth=float(device._main_scpi_query('BAND?'))
    carrier=options.carrier_hz
    # A missing IQ response must produce an error, rather than block forever.
    stream=getattr(device,'capture_socket',None)
    if stream is not None and hasattr(stream,'settimeout'):
        fs=float(device.get_sampling_rate_hz())
        stream.settimeout(max(10.,4*options.window_samples*min(options.fft_count,16)/fs))
    spec=IFSpectrumSpec(if_bandwidth_hz=bandwidth,commands=(),carrier_hz=carrier,
        reciver_bandwidth=bandwidth,window_samples=options.window_samples,
        overlap=options.overlap,ffts=options.fft_count)
    def convert(spectrum):
        enbw=1.5*spectrum.sample_rate_hz/spectrum.window_samples
        return DiagnosticSpectrum(name=options.name,offset_hz=spectrum.offset_hz.copy(),
            density_dbm_hz=np.asarray(spectrum.power_db)-10*np.log10(enbw),
            sample_rate_hz=spectrum.sample_rate_hz,window_samples=spectrum.window_samples,
            overlap=spectrum.overlap,ffts=spectrum.ffts,carrier_hz=spectrum.carrier_hz,
            bandwidth_hz=bandwidth,operator=operator,
            datetime=spectrum.datetime or datetime.now(timezone.utc).replace(tzinfo=None).isoformat())
    on_status(f'Preparing capture at {carrier:g} Hz, BAND {bandwidth:g} Hz…')
    spectrum=cfg_test8.measure_test8(device,spec,name=options.name,operator=operator,
        checkpoint=checkpoint,check_cancel=check_cancel,
        on_spectrum=lambda current:on_spectrum(convert(current)),
        on_progress=on_progress,on_status=on_status,iq_bits=options.iq_bits,fft_debug=False)
    check_cancel()
    return convert(spectrum)
