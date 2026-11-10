"""Configuration needed to run, save and display each measurement."""

from measurement import SweepMeasurement
from measurement import NoiseDensityMeasurement
from measurement import IP3Measurement
from measurement import IFSpectrumMeasurement
from dataclasses import dataclass
import numpy as np

CALIB_POWER = -40.0
VERIFICATION_POW = -50.0
NOISE_UNIT = 'dB'  # Raw acquisition values; presentation is configured in cfg_*.


@dataclass(frozen=True)
class SweepSpec:
    frequencies: np.ndarray
    commands: tuple[str, ...]
    kind: str = 'receiver_sweep'
    storage: str = 'tests'
    unit: str = NOISE_UNIT
    power_dbm: float | None = None
    power_setting: str | None = None
    display_unit: str = 'dB'
    display_offset_db: float = 0.0

    @property
    def measurement_class(self):
        return SweepMeasurement

    def work_units_for(self,settings):
        return self.work_units

    @property
    def needs_generator(self):
        return self.kind in ('generator_sweep', 'calibration', 'test1', 'test3')

    @property
    def generator_frequencies(self):
        return (float(self.frequencies[0]),float(self.frequencies[-1]))

    @property
    def work_units(self):
        return len(self.frequencies)


@dataclass(frozen=True)
class NoiseDensitySpec:
    carrier_hz: float
    commands: tuple[str, ...]
    window_samples: int = 2**21
    overlap: float = 0.5
    headroom_db: float = 1.0
    display_skip_bins: int = 16
    storage: str = 'tests'
    kind: str = 'noise_density'
    needs_generator: bool = True
    power_dbm: float | None = None  # chosen from DUT full range at acquisition

    @property
    def measurement_class(self):
        return NoiseDensityMeasurement

    def work_units_for(self,settings):
        return settings.noise_ffts

    @property
    def generator_frequencies(self):
        return (self.carrier_hz,)


@dataclass(frozen=True)
class IP3Spec:
    frequencies: np.ndarray
    commands: tuple[str, ...]
    tone_spacing_hz: float = 100e3
    noise_bandwidth_db: float = 34.8
    storage: str = 'tests'
    kind: str = 'ip3'
    needs_generator: bool = True
    generator_role: str = 'ip3'
    power_dbm: float | None = None

    @property
    def measurement_class(self):
        return IP3Measurement

    def work_units_for(self, settings):
        return len(self.frequencies)

    @property
    def generator_frequencies(self):
        return (float(self.frequencies[0]), float(self.frequencies[-1] + self.tone_spacing_hz))


@dataclass(frozen=True)
class IFSpectrumSpec:
    if_bandwidth_hz: float
    commands: tuple[str, ...]
    filter_label: str = ''
    reciver_bandwidth: float = 90e6  # receiver BAND in Hz, matching cfg
    ffts: int = 100
    carrier_hz: float = 500e6
    window_samples: int = 2**14
    overlap: float = .5
    storage: str = 'tests'
    kind: str = 'if_spectrum'
    needs_generator: bool = False
    power_dbm: float | None = None

    @property
    def measurement_class(self):
        return IFSpectrumMeasurement

    def work_units_for(self, settings):
        return settings.test8_ffts.get(self.filter_label,self.ffts)
