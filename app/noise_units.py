"""Input-referred receiver noise units, using the same NF convention as Test7."""
import numpy as np
from cfg_common import DBM_TO_DBUV_50_OHM

NOISE_REFERENCE_DBM_HZ = -174.0  # Approximate thermal reference at 290 K.


def _noise_bandwidth(measurement):
    if measurement.bandwidth_hz is None or measurement.bandwidth_hz <= 0:
        raise ValueError('Saved noise data needs its original bandwidth for this conversion; remeasure if unavailable.')
    return float(measurement.bandwidth_hz)


def rms_power_dbm(measurement):
    """Integrated RMS power. Reversing legacy NF/density uses saved nominal BW."""
    values = np.asarray(measurement.limit_dB, dtype=float)
    if measurement.quantity == 'noise_figure':
        return values + NOISE_REFERENCE_DBM_HZ + 10*np.log10(_noise_bandwidth(measurement))
    if measurement.unit == 'dBm/Hz':
        return values + 10*np.log10(_noise_bandwidth(measurement))
    if measurement.unit in ('dBm','dB'):
        return values
    if measurement.unit in ('dBµV','dBμV'):
        return values - DBM_TO_DBUV_50_OHM
    raise ValueError(f'Unsupported saved noise unit: {measurement.unit}')


def noise_figure_db(measurement):
    """NF = input noise density [dBm/Hz] + 174. Not noise floor in dBm/Hz.

    At 50 ohms: NF = integrated_noise_dBuV + 67.0103 - 10*log10(B).
    The -67.0103 dBµV/sqrt(Hz) thermal reference is subtracted, hence +67.0103.
    """
    values = np.asarray(measurement.limit_dB, dtype=float)
    if measurement.quantity == 'noise_figure':
        return values
    if measurement.unit == 'dBm/Hz':
        return values - NOISE_REFERENCE_DBM_HZ
    return rms_power_dbm(measurement) - 10*np.log10(_noise_bandwidth(measurement)) - NOISE_REFERENCE_DBM_HZ
