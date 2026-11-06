"""Domain configuration, measurement procedure and report content."""

# Presentation only: acquired/stored values are never converted here.
from cfg_common import DBM_TO_DBUV_50_OHM
DISPLAY_UNIT = 'dBµV'
DISPLAY_OFFSET_DB = DBM_TO_DBUV_50_OHM

import numpy as np
from cfg_common import (FREQ_AXIS_FULL_RANGE_HZ, FREQ_AXIS_CH2_HZ, _BAND_5K, _CAL_ON, _RF1, _RF2, _GAIN_ON, _GAIN_OFF, _IFBAND_MANUAL, _PRESELECTOR_OFF, _PRESELECTOR_ON, _PG_ON, _PG_OFF, _RST)

_TEST2_RF1 = [_RST,_RF1,_CAL_ON,_BAND_5K,_IFBAND_MANUAL + "10M"]
CFG_TEST2 = {
    "TEST2_GAIN_OFF_PRESESLECTOR_OFF_IFBAND_10M.txt" : (FREQ_AXIS_FULL_RANGE_HZ,_TEST2_RF1+[_GAIN_OFF,_PRESELECTOR_OFF]),
    "TEST2_GAIN_ON_PRESESLECTOR_OFF_IFBAND_10M.txt"  : (FREQ_AXIS_FULL_RANGE_HZ,_TEST2_RF1+[_GAIN_ON ,_PRESELECTOR_OFF]),
    "TEST2_GAIN_OFF_PRESESLECTOR_ON_IFBAND_10M.txt"  : (FREQ_AXIS_FULL_RANGE_HZ,_TEST2_RF1+[_GAIN_OFF,_PRESELECTOR_ON ,_PG_OFF]),
    "TEST2_GAIN_OFF_PRESESLECTOR_GAIN_IFBAND_10M.txt": (FREQ_AXIS_FULL_RANGE_HZ,_TEST2_RF1+[_GAIN_OFF,_PRESELECTOR_ON ,_PG_ON]),
    "TEST2_GAIN_ON_PRESESLECTOR_ON_IFBAND_10M.txt"   : (FREQ_AXIS_FULL_RANGE_HZ,_TEST2_RF1+[_GAIN_ON ,_PRESELECTOR_ON ,_PG_OFF]),
    "TEST2_GAIN_ON_PRESESLECTOR_GAIN_IFBAND_10M.txt" : (FREQ_AXIS_FULL_RANGE_HZ,_TEST2_RF1+[_GAIN_ON ,_PRESELECTOR_ON ,_PG_ON]),
}

_TEST2_RF2 = [_RST,_RF2,_CAL_ON,_BAND_5K,_IFBAND_MANUAL + "10M"]
CFG_TEST2_RF2 = {
    "TEST2_RF2_GAIN_OFF.txt":(FREQ_AXIS_CH2_HZ,_TEST2_RF2+[_GAIN_OFF]),
    "TEST2_RF2_GAIN_ON.txt" :(FREQ_AXIS_CH2_HZ,_TEST2_RF2+[_GAIN_ON ]),
}


from datetime import datetime, timezone
from pathlib import Path
from measurement import SweepMeasurement
from cfg_common import sweep_bandwidth_hz


def measure_test2(device, frequencies, commands, *, name='', dwell_sec=.1,
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


def evaluate_test2(measurement):
    """Presence-only policy: there is no noise-level acceptance threshold."""
    return bool(measurement.available)


# Edit these values and the function below to define this test's Word section.
REPORT_TITLE = 'Test2 Noise level'
REPORT_DESCRIPTION = ('Receiver RMS noise measurements with the selected RF input terminated. '
    'A recorded measurement is marked passed; no noise-level threshold is applied.')
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
        add_measurement_heading(document, measurement, passed=evaluate_test2(measurement))
        if not measurement.has_data():
            document.add_paragraph('The saved measurement contains no complete data.')
            continue
        display_values = np.asarray(measurement.limit_dB) + DISPLAY_OFFSET_DB
        if REPORT_CHART:
            add_chart(document, measurement.freq_hz, {'Measured': display_values},
                      ylabel=f'Level ({DISPLAY_UNIT})',passed=evaluate_test2(measurement))
