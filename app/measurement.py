
from dataclasses import replace
from dataclasses import dataclass, field
from datetime import datetime as DateTime
from pathlib import Path
import numpy as np

ENCODING = "cp1252"

IF_SPECTRUM_UNIT = 'dBm'


@dataclass
class IFSpectrumMeasurement:
    """Test8 two-sided RMS power spectrum; signed offsets from carrier_hz."""
    name: str = ''
    offset_hz: np.ndarray = field(default_factory=lambda: np.array([]))
    power_db: np.ndarray = field(default_factory=lambda: np.array([]))
    carrier_hz: float = 500e6
    if_bandwidth_hz: float = 0.
    sample_rate_hz: float = 0.
    window_samples: int = 2**14
    overlap: float = .5
    ffts: int = 0
    available: bool = False
    datetime: str = ''
    operator: str = ''
    temperature: str = ''
    unit: str = IF_SPECTRUM_UNIT

    def has_data(self):
        f, p = np.asarray(self.offset_hz), np.asarray(self.power_db)
        return bool(self.available and f.ndim == p.ndim == 1 and f.size > 0 and f.size == p.size
                    and np.all(np.isfinite(f)) and np.all(np.diff(f) > 0)
                    and not np.any(np.isnan(p) | np.isposinf(p)))

    def snapshot(self, max_points=None):
        indices = slice(None) if max_points is None else np.unique(np.append(
            np.linspace(0, len(self.offset_hz)-1, min(max_points,len(self.offset_hz)), dtype=int),
            np.argmin(np.abs(self.offset_hz))))
        return replace(self, offset_hz=self.offset_hz[indices].copy(), power_db=self.power_db[indices].copy())

    @classmethod
    def from_file(cls, file_path):
        path = Path(file_path)
        result = cls(name=path.stem, available=path.is_file())
        # Older uncalibrated files must never be relabelled as absolute power.
        result.unit = 'dB re 1 IQ²/Hz'
        if not result.available:
            return result
        comments, rows = {}, []
        with path.open(encoding=ENCODING) as file:
            for line in file:
                if line.startswith('#!'):
                    key, value = line[2:].split(':', 1)
                    comments[key.strip()] = value.strip()
                elif line.strip() and not line.startswith('offset[Hz]'):
                    rows.append([float(value) for value in line.strip().split(';')[:2]])
        for key, attr in (('NAME','name'),('UNIT','unit'),('TEMP','temperature'),('OPERATOR','operator')):
            if key in comments:
                setattr(result,attr,comments[key])
        for key, attr in (('CARRIER_HZ','carrier_hz'),('IF_BANDWIDTH_HZ','if_bandwidth_hz'),
                          ('SAMPLE_RATE_HZ','sample_rate_hz'),('OVERLAP','overlap')):
            if comments.get(key):
                setattr(result,attr,float(comments[key]))
        for key, attr in (('WINDOW_SAMPLES','window_samples'),('FFTS','ffts')):
            if comments.get(key):
                setattr(result,attr,int(comments[key]))
        if comments.get('DATE') and comments.get('TIME_UTC'):
            result.datetime = DateTime.strptime(comments['DATE']+' '+comments['TIME_UTC'],
                                               '%d/%m/%Y %H:%M:%S').isoformat()
        if rows:
            result.offset_hz, result.power_db = np.asarray(rows).T
        return result

    def save_to_file(self, file_path):
        stamp = DateTime.fromisoformat(self.datetime) if self.datetime else None
        comments = {'NAME':self.name,'UNIT':self.unit,'DATE':stamp.strftime('%d/%m/%Y') if stamp else '',
            'TIME_UTC':stamp.strftime('%H:%M:%S') if stamp else '', 'TEMP':self.temperature,
            'OPERATOR':self.operator,'CARRIER_HZ':self.carrier_hz,'IF_BANDWIDTH_HZ':self.if_bandwidth_hz,
            'SAMPLE_RATE_HZ':self.sample_rate_hz,'WINDOW_SAMPLES':self.window_samples,
            'OVERLAP':self.overlap,'FFTS':self.ffts,'WINDOW':'periodic Hann',
            'SPECTRUM':('two-sided Hann power spectrum; fftshift' if self.unit == 'dBm'
                        else 'two-sided complex IQ PSD; fftshift'), 'AVERAGING':'linear power'}
        with Path(file_path).open('w',encoding=ENCODING) as file:
            for key,value in comments.items():
                file.write(f'#!{key}: {value}\n')
            file.write(f'offset[Hz];Level[{self.unit}];\n')
            np.savetxt(file,np.column_stack((self.offset_hz,self.power_db)),delimiter=';',fmt='%.12g')
        self.available = True

IP3_COLUMNS = ('freq[MHz]', 'P signal[dBm]', 'P IM3[dBm]', 'IP3[dBm]', 'NF density[dB/Hz]', 'SFDR[dB]')
IP3_ARRAY_FIELDS = ('freq_mhz', 'signal_dbm', 'im3_dbm', 'ip3_dbm', 'nf_db', 'sfdr_db')


@dataclass
class IP3Measurement:
    name: str = ''
    freq_mhz: np.ndarray = field(default_factory=lambda: np.array([]))
    signal_dbm: np.ndarray = field(default_factory=lambda: np.array([]))
    im3_dbm: np.ndarray = field(default_factory=lambda: np.array([]))
    ip3_dbm: np.ndarray = field(default_factory=lambda: np.array([]))
    noise_unit: str = 'dB/Hz'  # Unit of receiver-provided nf_db; no +174 conversion.
    nf_db: np.ndarray = field(default_factory=lambda: np.array([]))
    sfdr_db: np.ndarray = field(default_factory=lambda: np.array([]))
    available: bool = False
    datetime: str = ''
    operator: str = ''
    temperature: str = ''
    tone_spacing_hz: float = 100e3
    noise_bandwidth_db: float = 34.8
    per_tone_headroom_db: float = 3.01029995664

    def has_data(self):
        arrays = [np.asarray(getattr(self, name)) for name in IP3_ARRAY_FIELDS]
        return bool(self.available and arrays[0].size and all(
            a.ndim == 1 and a.size == arrays[0].size and np.all(np.isfinite(a)) for a in arrays))

    def snapshot(self, max_points=None):
        return replace(self, **{name: np.asarray(getattr(self, name)).copy() for name in IP3_ARRAY_FIELDS})

    @classmethod
    def from_file(cls, file_path):
        path = Path(file_path)
        result = cls(name=path.stem, available=path.is_file(), noise_unit='dB')
        if not result.available:
            return result
        comments, rows = {}, []
        with path.open(encoding=ENCODING) as file:
            for line in file:
                if line.startswith('#!'):
                    key, value = line[2:].split(':', 1)
                    comments[key.strip()] = value.strip()
                elif line.strip() and not line.startswith('freq[MHz]'):
                    rows.append([float(v) for v in line.strip().split(';')[:6]])
        for key, attr in (('NAME', 'name'), ('OPERATOR', 'operator'), ('TEMP', 'temperature'), ('NOISE_UNIT', 'noise_unit')):
            if key in comments:
                setattr(result, attr, comments[key])
        for key, attr in (('TONE_SPACING_HZ', 'tone_spacing_hz'),
                          ('NOISE_BANDWIDTH_DB', 'noise_bandwidth_db'),
                          ('PER_TONE_HEADROOM_DB', 'per_tone_headroom_db')):
            if comments.get(key):
                setattr(result, attr, float(comments[key]))
        if comments.get('DATE') and comments.get('TIME_UTC'):
            result.datetime = DateTime.strptime(comments['DATE'] + ' ' + comments['TIME_UTC'],
                                               '%d/%m/%Y %H:%M:%S').isoformat()
        if rows:
            for attr, values in zip(IP3_ARRAY_FIELDS, np.asarray(rows).T):
                setattr(result, attr, values)
        return result

    def save_to_file(self, file_path):
        timestamp = DateTime.fromisoformat(self.datetime) if self.datetime else None
        comments = {'NAME': self.name, 'DATE': timestamp.strftime('%d/%m/%Y') if timestamp else '',
                    'TIME_UTC': timestamp.strftime('%H:%M:%S') if timestamp else '',
                    'TEMP': self.temperature, 'OPERATOR': self.operator, 'NOISE_UNIT': self.noise_unit,
                    'TONE_SPACING_HZ': self.tone_spacing_hz, 'NOISE_BANDWIDTH_DB': self.noise_bandwidth_db,
                    'PER_TONE_HEADROOM_DB': self.per_tone_headroom_db}
        with Path(file_path).open('w', encoding=ENCODING) as file:
            for key, value in comments.items():
                file.write(f'#!{key}: {value}\n')
            columns = IP3_COLUMNS if self.noise_unit == 'dB/Hz' else (*IP3_COLUMNS[:4], f'NF[{self.noise_unit}]', IP3_COLUMNS[5])
            file.write(';'.join(columns) + ';\n')
            np.savetxt(file, np.column_stack([getattr(self, name) for name in IP3_ARRAY_FIELDS]),
                       delimiter=';', fmt='%.12g')
        self.available = True

@dataclass
class SweepMeasurement:
    name: str = ""
    freq_hz: np.ndarray = field(default_factory=lambda: np.array([]))
    limit_dB: np.ndarray | None = None
    available: bool = False
    datetime: str = ""
    operator: str = ""
    unit: str = "dB"
    temperature: str = ""
    reference_dbm: float | None = None
    dwell_sec: float | None = None
    bandwidth_hz: float | None = None
    quantity: str = ''




    def has_data(self):
        if not self.available or self.limit_dB is None:
            return False
        f,v=np.asarray(self.freq_hz),np.asarray(self.limit_dB)
        return bool(f.ndim==v.ndim==1 and f.size>0 and f.size==v.size
                    and np.all(np.isfinite(f)&(f>0)) and np.all(np.diff(f)>0)
                    and np.all(np.isfinite(v)))

    def snapshot(self,max_points=None):
        return replace(self,freq_hz=self.freq_hz.copy(),
                       limit_dB=None if self.limit_dB is None else np.asarray(self.limit_dB).copy())

    @classmethod
    def from_file(cls, file_path):
        path = Path(file_path)
        measurement = cls(name=path.stem, available=path.is_file())

        if not measurement.available:
            return measurement

        comments = {}
        frequencies = []
        limits = []

        with path.open(encoding=ENCODING) as file:
            for line in file:
                if line.startswith("#!"):
                    key, value = line[2:].split(":", 1)
                    comments[key.strip()] = value.strip()
                elif line.strip() and not line.startswith("freq[Hz]"):
                    frequency, limit, *_ = line.strip().split(";")
                    frequencies.append(float(frequency))
                    limits.append(float(limit) if limit else np.nan)

        comment_attributes = {
            "NAME": "name",
            "UNIT": "unit",
            "TEMP": "temperature",
            "OPERATOR": "operator",
            "QUANTITY": "quantity",
        }

        for comment, attribute in comment_attributes.items():
            if comment in comments:
                setattr(measurement, attribute, comments[comment])

        if comments.get("DATE") and comments.get("TIME_UTC"):
            measurement.datetime = DateTime.strptime(
                f"{comments['DATE']} {comments['TIME_UTC']}",
                "%d/%m/%Y %H:%M:%S",
            ).isoformat()

        if comments.get('REFERENCE_DBM'):
            measurement.reference_dbm = float(comments['REFERENCE_DBM'])
        for key,attribute in (('DWELL_SEC','dwell_sec'),('BANDWIDTH_HZ','bandwidth_hz')):
            if comments.get(key):
                setattr(measurement,attribute,float(comments[key]))
        measurement.freq_hz = np.array(frequencies)
        measurement.limit_dB = (
            np.array(limits)
            if any(not np.isnan(value) for value in limits)
            else None
        )

        return measurement

    def save_to_file(self, file_path):
        timestamp = (
            DateTime.fromisoformat(self.datetime)
            if self.datetime
            else None
        )
        date = timestamp.strftime("%d/%m/%Y") if timestamp else ""
        time_utc = timestamp.strftime("%H:%M:%S") if timestamp else ""

        with Path(file_path).open("w", encoding=ENCODING) as file:
            file.write(f"#!NAME: {self.name}\n")
            file.write(f"#!UNIT: {self.unit}\n")
            if self.quantity:
                file.write(f'#!QUANTITY: {self.quantity}\n')
            file.write(f"#!DATE: {date}\n")
            file.write(f"#!TIME_UTC: {time_utc}\n")
            file.write(f"#!TEMP: {self.temperature}\n")
            file.write(f"#!OPERATOR: {self.operator}\n")
            if self.reference_dbm is not None:
                file.write(f"#!REFERENCE_DBM: {self.reference_dbm}\n")
            for key,value in (('DWELL_SEC',self.dwell_sec),('BANDWIDTH_HZ',self.bandwidth_hz)):
                if value is not None:
                    file.write(f"#!{key}: {value}\n")
            file.write('freq[Hz];Noise density[dB/Hz];\n' if self.quantity == 'noise_density' else
                'freq[Hz];NF[dB];\n' if self.quantity == 'noise_figure' else
                "freq[Hz];Power[dBm];\n" if self.unit == "dBm" else "freq[Hz];Limit[dB];\n")

            for index, frequency in enumerate(self.freq_hz):
                limit = (
                    self.limit_dB[index]
                    if self.limit_dB is not None
                    else ""
                )
                file.write(f"{frequency};{limit};\n")

        self.available = True




@dataclass
class NoiseDensityMeasurement:
    """One carrier, shared acquisition, paired Test5/Test6 spectra in dBc/Hz."""
    name: str = ''
    carrier_hz: float = 0.0
    offset_hz: np.ndarray = field(default_factory=lambda: np.array([]))
    phase_noise: np.ndarray = field(default_factory=lambda: np.array([]))
    amplitude_noise: np.ndarray = field(default_factory=lambda: np.array([]))
    available: bool = False
    datetime: str = ''
    operator: str = ''
    temperature: str = ''
    unit: str = 'dBc/Hz'
    sample_rate_hz: float = 0.0
    window_samples: int = 0
    overlap: float = 0.5
    ffts: int = 0
    reference_dbm: float | None = None

    def has_data(self):
        f=np.asarray(self.offset_hz)
        p=np.asarray(self.phase_noise)
        a=np.asarray(self.amplitude_noise)
        return bool(self.available and f.ndim==p.ndim==a.ndim==1 and f.size>0
                    and f.size==p.size==a.size and np.all(np.isfinite(f)&(f>0))
                    and np.all(np.diff(f)>0) and not np.any(np.isnan(p)|np.isnan(a))
                    and not np.any(np.isposinf(p)|np.isposinf(a)))

    @classmethod
    def from_file(cls,file_path):
        path=Path(file_path)
        result=cls(name=path.stem,available=path.is_file())
        if not result.available:
            return result
        comments={}
        data=[]
        with path.open(encoding=ENCODING) as file:
            for line in file:
                if line.startswith('#!'):
                    key,value=line[2:].split(':',1)
                    comments[key.strip()]=value.strip()
                elif line.strip() and not line.startswith('f[Hz]'):
                    data.append([float(value) for value in line.strip().split(';')[:3]])
        for key,attr in (('NAME','name'),('UNIT','unit'),('OPERATOR','operator'),('TEMP','temperature')):
            if key in comments:
                setattr(result,attr,comments[key])
        for key,attr in (('CARRIER_HZ','carrier_hz'),('SAMPLE_RATE_HZ','sample_rate_hz'),('OVERLAP','overlap')):
            if comments.get(key):
                setattr(result,attr,float(comments[key]))
        for key,attr in (('WINDOW_SAMPLES','window_samples'),('FFTS','ffts')):
            if comments.get(key):
                setattr(result,attr,int(comments[key]))
        if comments.get('REFERENCE_DBM'):
            result.reference_dbm=float(comments['REFERENCE_DBM'])
        if comments.get('DATE') and comments.get('TIME_UTC'):
            result.datetime=DateTime.strptime(comments['DATE']+' '+comments['TIME_UTC'],
                                              '%d/%m/%Y %H:%M:%S').isoformat()
        if data:
            result.offset_hz,result.phase_noise,result.amplitude_noise=np.asarray(data).T
        return result

    def save_to_file(self,file_path):
        timestamp=DateTime.fromisoformat(self.datetime) if self.datetime else None
        comments={'NAME':self.name,'UNIT':self.unit,
            'DATE':timestamp.strftime('%d/%m/%Y') if timestamp else '',
            'TIME_UTC':timestamp.strftime('%H:%M:%S') if timestamp else '',
            'TEMP':self.temperature,'OPERATOR':self.operator,
            'CARRIER_HZ':self.carrier_hz,'SAMPLE_RATE_HZ':self.sample_rate_hz,
            'WINDOW_SAMPLES':self.window_samples,'OVERLAP':self.overlap,'FFTS':self.ffts,
            'REFERENCE_DBM':self.reference_dbm if self.reference_dbm is not None else '',
            'AVERAGING':'linear density; periodic Hann; SSB'}
        with Path(file_path).open('w',encoding=ENCODING) as file:
            for key,value in comments.items():
                file.write(f'#!{key}: {value}\n')
            file.write('f[Hz];phase_noise[dBc/Hz];amplitude_noise[dBc/Hz];\n')
            np.savetxt(file,np.column_stack((self.offset_hz,self.phase_noise,self.amplitude_noise)),
                       delimiter=';',fmt='%.12g')
        self.available=True

    def snapshot(self,max_points=None):
        indices=slice(None) if max_points is None else np.unique(
            np.geomspace(1,max(1,len(self.offset_hz)),min(max_points,len(self.offset_hz))).astype(int)-1)
        return NoiseDensityMeasurement(**{**self.__dict__,
            'offset_hz':self.offset_hz[indices].copy(),
            'phase_noise':self.phase_noise[indices].copy(),
            'amplitude_noise':self.amplitude_noise[indices].copy()})
