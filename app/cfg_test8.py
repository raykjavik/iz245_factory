"""Test8 IF filter spectra: RF1 terminated in 50 ohms, no generator."""

# Absolute RMS power is saved in dBm; dBµV is a presentation conversion into 50 Ω.
DISPLAY_UNIT = 'dBµV'
DISPLAY_OFFSET_DB = 106.98970

from datetime import datetime, timezone
from pathlib import Path
import time
import numpy as np
from cfg_common import _RF1, _CAL_ON, _GAIN_OFF, _PRESELECTOR_OFF, _IFBAND_MANUAL
from measurement_specs import IFSpectrumSpec
from measurement import IFSpectrumMeasurement
from fft_processor import FFTProcessor, power_spectrum
import report_tools

TEST8 = {'carrier_hz':500e6, 'overlap':.5}
_TEST8_CMDS = ["*RST", _RF1, _CAL_ON, _GAIN_OFF, _PRESELECTOR_OFF]
PLOT_INTERVAL_SEC = 0.5

# Filter label, IF width (Hz), receiver BAND (Hz), FFT window samples, default averages.
IF_FILTERS_TEST8 = (
    ('407k', 407e3, 20e6, 16384,2048),
    ('10M', 10e6, 20e6, 16384,2048),
    ('50M', 50e6, 70e6, 65536,1024),
    ('80M', 80e6, 90e6, 65536,1024),
)
CFG_TEST8 = {
    f'TEST8_RF1_IFBAND_{label}.txt': IFSpectrumSpec(
        if_bandwidth_hz=bandwidth, filter_label=label,
        commands=tuple(_TEST8_CMDS+['BAND '+ str(int(reciver_bandwidth)), _IFBAND_MANUAL+label]),
        reciver_bandwidth = reciver_bandwidth,
        ffts = ffts,
        carrier_hz=TEST8['carrier_hz'], window_samples=samples, overlap=TEST8['overlap'])
    for label,bandwidth,reciver_bandwidth,samples,ffts in IF_FILTERS_TEST8
}


def measure_test8(device, spec, *, name='', dwell_sec=.1,
                  operator='', temperature='', checkpoint=lambda:False, wait=time.sleep,
                  check_cancel=lambda:None,
                  on_spectrum=lambda result:None, on_progress=lambda:None,
                  on_status=lambda text:None, iq_bits='Auto', fft_debug=True):
    """Average calibrated linear power in each Hann resolution bandwidth."""
    checkpoint()
    if spec.commands:
        device._main_scpi_commands(list(spec.commands))
    device.tune_awaited(spec.carrier_hz)
    bits=(16 if spec.reciver_bandwidth>40e6 else 32) if iq_bits=='Auto' else int(iq_bits)
    if bits == 16:
        device.set_16b_iq_format()
    elif bits == 32:
        device.set_32b_iq_format()
    else:
        raise ValueError('IQ format must be Auto, 16 or 32.')
    if dwell_sec > 1.0:
        wait(dwell_sec)
    check_cancel()
    fs = float(device.get_sampling_rate_hz())

    def transform(iq, sample_rate_hz):
        frequency, power = power_spectrum(iq, sample_rate_hz)
        # get_gain_dBuV includes this receiver's peak-to-RMS convention and
        # sample-format/full-scale corrections. Do not apply another /2.
        gain_dbm = float(device.header.get_gain_dBuV()) - DISPLAY_OFFSET_DB
        return frequency, power * 10**(gain_dbm/10)

    def measurement(average):
        with np.errstate(divide='ignore'):
            power_db = 10*np.log10(average.values[0])
        return IFSpectrumMeasurement(name=Path(name).stem,
            offset_hz=average.frequency_hz.copy(), power_db=power_db,
            carrier_hz=spec.carrier_hz, if_bandwidth_hz=spec.if_bandwidth_hz,
            sample_rate_hz=fs, window_samples=spec.window_samples, overlap=spec.overlap,
            ffts=average.completed, operator=operator, temperature=temperature,
            available=True)

    def publish(average):
        # Keep all bins; the existing GUI uses maximum aggregation for display.
        on_spectrum(measurement(average))
        on_status(f'IF {spec.if_bandwidth_hz/1e6:g} MHz · FFT {average.completed}/{spec.ffts}')

    processor = FFTProcessor(device, window_samples=spec.window_samples,
        fft_count=spec.ffts, overlap=spec.overlap, sample_rate_hz=fs,
        transform=transform, update_interval=PLOT_INTERVAL_SEC,debug=fft_debug)
    on_status(f'Waiting for IQ data · {spec.window_samples} samples / FFT · {spec.ffts} windows')
    average = processor.run(checkpoint=checkpoint, check_cancel=check_cancel,
        on_average=publish, on_progress=on_progress)
    checkpoint()
    result = measurement(average)
    result.datetime = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
    return result


def evaluate_test8(measurement):
    """Presence-only test: available is populated from file existence on load."""
    return bool(measurement.available)


FILTER_VIEW_WIDTH_FACTOR = 1.5


def filter_edges_hz(width_hz):
    return (-width_hz/2,width_hz/2)


def filter_view_hz(width_hz):
    half_span = FILTER_VIEW_WIDTH_FACTOR*width_hz/2
    return (-half_span,half_span)


REPORT_CHART = True
REPORT_TABLE = False
REPORT_OFFSETS_HZ = (-40e6,-20e6,0.,20e6,40e6)


def display_values(measurement):
    return np.asarray(measurement.power_db)+DISPLAY_OFFSET_DB,DISPLAY_UNIT


def add_report(document, measurements):
    report_tools.add_test_heading(document,'Test8 IF filter spectra',
        'Two sided power spectra with RF1 terminated in 50 ohms, receiver tuned to 500 MHz; receiver BAND and FFT size are selected per filter.')
    if not measurements:
        report_tools.no_measurements(document)
    for measurement in measurements:
        title = f'IF filter {measurement.if_bandwidth_hz/1e6:g} MHz' if measurement.if_bandwidth_hz>1e6 else f'IF filter {measurement.if_bandwidth_hz/1e3:g} kHz' 
        report_tools.add_measurement_heading(document,measurement,
            title=title,passed=evaluate_test8(measurement))
        document.add_paragraph(f'{measurement.ffts} windows of {measurement.window_samples} samples. '
            f'Overlap {measurement.overlap:g}. Sample rate {measurement.sample_rate_hz/1e6:.3f} MHz. '
            'RMS level in each Hann resolution bandwidth, calibrated from the receiver header.')
        if not measurement.has_data():
            document.add_paragraph('The saved spectrum contains no complete data.')
            continue
        values, unit = display_values(measurement)
        if REPORT_TABLE:
            indices = sorted({int(np.argmin(np.abs(measurement.offset_hz-offset)))
                for offset in REPORT_OFFSETS_HZ if measurement.offset_hz[0] <= offset <= measurement.offset_hz[-1]})
            report_tools.add_table(document,['Offset (Hz)',f'Level ({unit})'],
                [(measurement.offset_hz[i],values[i]) for i in indices])
        if REPORT_CHART:
            report_tools.add_chart(document,measurement.offset_hz,{'Measured':values},
                ylabel=f'RMS level ({unit})',xlabel='Offset from 500 MHz (Hz)',log_x=False,
                passed=evaluate_test8(measurement),
                vertical_limits=filter_edges_hz(measurement.if_bandwidth_hz),
                x_limits=filter_view_hz(measurement.if_bandwidth_hz))
