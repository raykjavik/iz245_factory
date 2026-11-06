"""Domain configuration, measurement procedure and report content."""

# Presentation only: acquired/stored values are never converted here.
DISPLAY_UNIT = 'dBc/Hz'
DISPLAY_OFFSET_DB = 0.0

import numpy as np
from cfg_common import (_GAIN_OFF, _IFBAND_MANUAL, _RST)

PLOT_INTERVAL_SEC = 0.5
PLOT_MIN_HZ = 100.0
PLOT_MAX_HZ = 10_000_000.0
PLOT_FREQUENCY_LIMITS_HZ = (PLOT_MIN_HZ, PLOT_MAX_HZ)

TEST_5_6 = {
    'freq_hz': np.array([32e6, 550e6, 1550e6, 3550e6, 7450e6]),
    'cmds': [_RST, _GAIN_OFF, 'BAND 20M', _IFBAND_MANUAL + '50M'],
    'window_samples': 2**22,
    'overlap': 0.5,
    'ffts': 50,  # default; actual run count is project.settings.noise_ffts
}

from measurement_specs import NoiseDensitySpec
CFG_NOISE_DENSITY = {
    f'NOISE_DENSITY_{frequency/1e6:g}MHz.txt': NoiseDensitySpec(
        carrier_hz=float(frequency), commands=tuple(TEST_5_6['cmds']),
        window_samples=TEST_5_6['window_samples'], overlap=TEST_5_6['overlap'])
    for frequency in TEST_5_6['freq_hz']
}

from datetime import datetime, timezone
from pathlib import Path
import time
from measurement import NoiseDensityMeasurement
from iz245.device import Device
from fft_processor import (FFTProcessor, NoiseDensityEstimator, to_dbc_hz,
                           phase_amplitude_noise_iq)


def _configure_carrier(dev:Device, gen, spec, dwell, attenuator_db, wait):
    dev.tune_awaited(spec.carrier_hz)
    
    dev._main_scpi_commands([
        f"SWEEP:DWELL {dwell}",
        'DETector:CLEar'
        ])
    dev.set_32b_iq_format()
    response=dev._main_scpi_query('sense:data?').split(',')
    full_range=float(response[-3])
    target=full_range-spec.headroom_db
    gen.cmd(f'POW {target+attenuator_db}')
    gen.cmd('SOURCE:POWER:OFFSET 0')
    if getattr(gen,'cable_calib',None) is not None:
        gen.cmd(f'SOURCE:POWER:OFFSET {gen.get_cable_offset(spec.carrier_hz)}')
    gen.cmd(f'FREQ {spec.carrier_hz:.2f}Hz')
    gen.cmd('OUTP:STAT 1')
    gen.opc()
    wait(dwell)
    return target


def measure_tests5_6(device, generator, spec, *, name='', dwell_sec=.1,
                     fft_count=50, attenuator_db=0., operator='',
                     temperature='', checkpoint=lambda:False, wait=time.sleep,
                     check_cancel=lambda:None,
                     on_spectrum=lambda result:None, on_progress=lambda:None,
                     on_status=lambda text:None):
    """Finite captures; FFTProcessor owns capture/FFT threads and linear means."""
    try:
        checkpoint()
        device._main_scpi_commands(list(spec.commands))
        device.set_32b_iq_format()
        target = _configure_carrier(device, generator, spec, dwell_sec, attenuator_db, wait)
        fs = float(device.get_sampling_rate_hz())
        estimator = NoiseDensityEstimator(spec.window_samples, fs)

        def transform(iq, sample_rate_hz):
            phase, amplitude = estimator.densities(iq)
            return estimator.frequency, phase, amplitude

        def measurement(average, preview=False):
            result = NoiseDensityMeasurement(name=Path(name).stem,
                carrier_hz=spec.carrier_hz, offset_hz=average.frequency_hz.copy(),
                phase_noise=to_dbc_hz(average.values[0]),
                amplitude_noise=to_dbc_hz(average.values[1]),
                available=True, operator=operator, temperature=temperature,
                sample_rate_hz=fs, window_samples=spec.window_samples,
                overlap=spec.overlap, ffts=average.completed, reference_dbm=target)
            return result.snapshot(max_points=4096) if preview else result

        def publish(average):
            on_spectrum(measurement(average, preview=True))
            on_status(f'{spec.carrier_hz/1e6:g} MHz · FFT {average.completed}/{fft_count}')

        processor = FFTProcessor(device, window_samples=spec.window_samples,
            fft_count=fft_count, overlap=spec.overlap, sample_rate_hz=fs,
            transform=transform, update_interval=PLOT_INTERVAL_SEC)
        average = processor.run(checkpoint=checkpoint, check_cancel=check_cancel,
            on_average=publish, on_progress=on_progress)
        checkpoint()
        result = measurement(average)
        result.datetime = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
        return result
    finally:
        if generator is not None:
            generator.cmd('OUTP:STAT 0')


def evaluate_test5(measurement):
    return measurement.has_data()

def evaluate_test6(measurement):
    return measurement.has_data()


REPORT_CHART = True
REPORT_TABLE = False
# Optional table: nearest measured bins at selected offsets, not a million-row FFT table.
REPORT_OFFSETS_HZ = (1e3, 1e4, 1e5, 1e6)


def add_report(document, measurements):
    from report_tools import (add_test_heading, add_measurement_heading, add_chart,
                              add_table, no_measurements)
    for title, attribute, evaluate in (
        ('Test5 Phase noise density', 'phase_noise', evaluate_test5),
        ('Test6 Amplitude noise density', 'amplitude_noise', evaluate_test6),
    ):
        add_test_heading(document, title,
            'Single sideband noise density from overlapping IQ windows, averaged in linear density.')
        if not measurements:
            no_measurements(document)
        for measurement in measurements:
            add_measurement_heading(document, measurement,
                title=f'Carrier {measurement.carrier_hz/1e6:g} MHz', passed=evaluate(measurement))
            document.add_paragraph(f'{measurement.ffts} FFT windows. '
                f'Sample rate {measurement.sample_rate_hz:g} Hz. Overlap {measurement.overlap:g}.')
            if not measurement.has_data():
                document.add_paragraph('The saved spectrum contains no complete data.')
                continue
            values = getattr(measurement, attribute)+DISPLAY_OFFSET_DB
            if REPORT_TABLE:
                indices = sorted({int(np.argmin(np.abs(measurement.offset_hz-f)))
                    for f in REPORT_OFFSETS_HZ if measurement.offset_hz[0] <= f <= measurement.offset_hz[-1]})
                add_table(document, ['Measured offset (Hz)', f'Density ({DISPLAY_UNIT})'],
                    [(measurement.offset_hz[i],values[i]) for i in indices])
            if REPORT_CHART:
                from chart_ranges import clipped_curve
                x, y = clipped_curve(measurement.offset_hz, values, PLOT_FREQUENCY_LIMITS_HZ, log_x=True)
                add_chart(document, x, {'Measured': y},
                          ylabel=f'Density ({DISPLAY_UNIT})', xlabel='Offset frequency (Hz)',
                          passed=evaluate(measurement),x_limits=PLOT_FREQUENCY_LIMITS_HZ)
