"""Domain configuration, measurement procedure and report content."""

from detector import read_detector
import report_tools

DISPLAY_UNIT = 'dB'
DISPLAY_OFFSET_DB = 0.0
NOISE_BANDWIDTH_HZ = 100_000.0
_BAND_100K = 'BAND 100k'

import numpy as np
from cfg_common import (FREQ_AXIS_FULL_RANGE_HZ, FREQ_AXIS_CH2_HZ, _BAND_5K, _CAL_ON, _RF1, _RF2, _GAIN_ON, _GAIN_OFF, _IFBAND_MANUAL, _PRESELECTOR_OFF, _PRESELECTOR_ON, _PG_ON, _PG_OFF, _RST)

_TEST2_RF1 = [_RST,_RF1,_CAL_ON,_BAND_100K,_IFBAND_MANUAL + "10M"]
CFG_TEST2 = {
    "TEST2_GAIN_OFF_PRESESLECTOR_OFF_IFBAND_10M.txt" : (FREQ_AXIS_FULL_RANGE_HZ,_TEST2_RF1+[_GAIN_OFF,_PRESELECTOR_OFF]),
    "TEST2_GAIN_ON_PRESESLECTOR_OFF_IFBAND_10M.txt"  : (FREQ_AXIS_FULL_RANGE_HZ,_TEST2_RF1+[_GAIN_ON ,_PRESELECTOR_OFF]),
    "TEST2_GAIN_OFF_PRESESLECTOR_ON_IFBAND_10M.txt"  : (FREQ_AXIS_FULL_RANGE_HZ,_TEST2_RF1+[_GAIN_OFF,_PRESELECTOR_ON ,_PG_OFF]),
    "TEST2_GAIN_OFF_PRESESLECTOR_GAIN_IFBAND_10M.txt": (FREQ_AXIS_FULL_RANGE_HZ,_TEST2_RF1+[_GAIN_OFF,_PRESELECTOR_ON ,_PG_ON]),
    "TEST2_GAIN_ON_PRESESLECTOR_ON_IFBAND_10M.txt"   : (FREQ_AXIS_FULL_RANGE_HZ,_TEST2_RF1+[_GAIN_ON ,_PRESELECTOR_ON ,_PG_OFF]),
    "TEST2_GAIN_ON_PRESESLECTOR_GAIN_IFBAND_10M.txt" : (FREQ_AXIS_FULL_RANGE_HZ,_TEST2_RF1+[_GAIN_ON ,_PRESELECTOR_ON ,_PG_ON]),
}

_TEST2_RF2 = [_RST,_RF2,_CAL_ON,_BAND_100K,_IFBAND_MANUAL + "10M"]
CFG_TEST2_RF2 = {
    "TEST2_RF2_GAIN_OFF.txt":(FREQ_AXIS_CH2_HZ,_TEST2_RF2+[_GAIN_OFF]),
    "TEST2_RF2_GAIN_ON.txt" :(FREQ_AXIS_CH2_HZ,_TEST2_RF2+[_GAIN_ON ]),
}
THERMAL_NOISE_DENSITY_DBM_HZ = -174.0

from datetime import datetime, timezone
from pathlib import Path
from measurement import SweepMeasurement
from cfg_common import sweep_bandwidth_hz
import time


def measure_test2(device, frequencies, commands, *, name='', dwell_sec=.1,
                  operator='', temperature='', checkpoint=None, on_row=None,
                  wait=time.sleep, check_cancel=lambda:None):
    """Receiver NF in dB, referred to the thermal noise density."""
    device._main_scpi_commands(list(commands)+[f'SWEEP:DWELL {dwell_sec:g}'])
    values=[]
    for frequency in frequencies:
        if checkpoint is not None:checkpoint()
        device.tune_awaited(frequency)
        vals=read_detector(device,dwell_sec,wait=wait,check_cancel=check_cancel)
        value=vals[-4]-THERMAL_NOISE_DENSITY_DBM_HZ
        if checkpoint is not None:checkpoint()
        values.append(value)
        if on_row is not None:on_row(float(frequency),value)
    return SweepMeasurement(name=Path(name).stem,freq_hz=np.asarray(frequencies).copy(),
        vals=np.asarray(values),available=True,unit='dB',quantity='noise_figure',
        datetime=datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
        operator=operator,temperature=temperature,dwell_sec=dwell_sec,
        bandwidth_hz=sweep_bandwidth_hz(commands))


def evaluate_test2(measurement):
    """Presence-only policy: there is no noise-level acceptance threshold."""
    return bool(measurement.available)


# Edit these values and the function below to define this test's Word section.
REPORT_TITLE = 'Test2 Noise Figure'
REPORT_DESCRIPTION = ('Receiver noise figure relative to -174 dBm/Hz, with the selected RF input terminated in 50 ohms and a 100 kHz band. '
    'A recorded measurement passes; no numerical limit is applied.')
REPORT_CHART = True
REPORT_TABLE = False


def add_report(document, measurements):
    """Append Heading 2, description, then Heading 3 and content per measurement."""
    report_tools.add_test_heading(document, REPORT_TITLE, REPORT_DESCRIPTION)
    if not measurements:
        report_tools.no_measurements(document)
    for measurement in measurements:
        title = measurement.name.replace('_', ' ').replace("TEST2","Noise Figure")
        report_tools.add_measurement_heading(document, measurement,title=title, passed=evaluate_test2(measurement))
        if not measurement.has_data():
            document.add_paragraph('The saved measurement contains no complete data.')
            continue
        try:
            display_values = np.asarray(measurement.vals,dtype=float)
        except ValueError as exc:
            document.add_paragraph(str(exc))
            continue
        if REPORT_CHART:
            report_tools.add_chart(document, measurement.freq_hz, {'Measured': display_values},
                      ylabel=f'NF({DISPLAY_UNIT})',passed=evaluate_test2(measurement))
