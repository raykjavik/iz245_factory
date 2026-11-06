"""Domain configuration, measurement procedure and report content."""

# Presentation only: acquired/stored values are never converted here.
from cfg_common import DBM_TO_DBUV_50_OHM
DISPLAY_UNIT = 'dBµV'
DISPLAY_OFFSET_DB = DBM_TO_DBUV_50_OHM

import numpy as np
from cfg_common import (_CAL_ON, _RF1, _RST)

FREQ_TEST4_50M_8G = np.concat([
    np.arange(50e6,1e8,1000000),
    np.arange(1e8,8e9,10000000),
    np.array([7999999900,8000000000])
]).astype(int)

_BAND_10K =  "BAND 10k" 
_INT_SYNT = "SOURce:TRACking:pow -13"
_TEST4 = [_RST,_INT_SYNT,_RF1,_CAL_ON,_BAND_10K]


CFG_TEST4 = {
    "TEST4.TXT" : (FREQ_TEST4_50M_8G,_TEST4)
}





from datetime import datetime, timezone
from pathlib import Path
from measurement import SweepMeasurement
from cfg_common import sweep_bandwidth_hz


def measure_test4(device, frequencies, commands, *, name='', dwell_sec=.1,
                  operator='', temperature='', checkpoint=None, on_row=None):
    """Receiver-only acquisition. This function has no generator reference."""
    device._main_scpi_commands(list(commands)+[f"SWEEP:DWELL {dwell_sec}"])
    values = []
    for frequency in frequencies:
        if checkpoint is not None:
            checkpoint()
        device.tune_awaited(frequency)
        value = float(device.measure_point_rms(dwell_sec))
        if checkpoint is not None:
            checkpoint()
        values.append(value)
        if on_row is not None:
            on_row(float(frequency), value)
    return SweepMeasurement(name=Path(name).stem, freq_hz=np.asarray(frequencies).copy(),
        limit_dB=np.asarray(values), available=True, unit='dBm',
        datetime=datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
        operator=operator, temperature=temperature,
        dwell_sec=dwell_sec,bandwidth_hz=sweep_bandwidth_hz(commands))


def evaluate_test4(measurement):
    """Presence-only result; no numerical level limits are specified."""
    return bool(measurement.available)


# Edit these values and the function below to define this test's Word section.
REPORT_TITLE = 'Test4 Internal verification'
REPORT_DESCRIPTION = 'Receiver measurements using the internal tracking source.'
REPORT_CHART = True
REPORT_TABLE = False


def add_report(document, measurements):
    """Append Heading 2, description, then Heading 3 and content per measurement."""
    from report_tools import (add_test_heading, add_measurement_heading, add_chart,
                              add_table, no_measurements)
    add_test_heading(document, REPORT_TITLE, REPORT_DESCRIPTION)
    if not measurements:
        no_measurements(document)
    for measurement in measurements:
        add_measurement_heading(document, measurement, passed=evaluate_test4(measurement))
        if not measurement.has_data():
            document.add_paragraph('The saved measurement contains no complete data.')
            continue
        display_values = np.asarray(measurement.limit_dB) + DISPLAY_OFFSET_DB
        if REPORT_TABLE:
            add_table(document, ['Frequency (Hz)', f'Value ({DISPLAY_UNIT})'],
                      zip(measurement.freq_hz, display_values))
        if REPORT_CHART:
            add_chart(document, measurement.freq_hz, {'Measured': display_values},
                      ylabel=f'Level ({DISPLAY_UNIT})',passed=evaluate_test4(measurement))
