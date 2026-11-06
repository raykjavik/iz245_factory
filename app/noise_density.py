"""Compatibility exports. Domain implementation lives in cfg_test_5_6.py."""
from cfg_test_5_6 import NoiseDensityEstimator, to_dbc_hz, phase_amplitude_noise_iq

def measure_noise_density(controller, name, spec, dwell):
    from measurement_handlers import measure_noise_density as acquire
    return acquire(controller, name, spec, dwell)
