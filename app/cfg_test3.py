"""Domain configuration, measurement procedure and report content."""

# Presentation only: acquired/stored values are never converted here.
from cfg_common import DBM_TO_DBUV_50_OHM
DISPLAY_UNIT = 'dBµV'
DISPLAY_OFFSET_DB = DBM_TO_DBUV_50_OHM

import numpy as np
from cfg_common import (_BAND_5K, _CAL_OFF, _RF1, _GAIN_OFF, _IFBAND_MANUAL, _PRES_PATH, _RST, _RSOC_OUT)

_PRES_FRQ = "INPUT:PRES:FREQUENCY "
_PRES_HP = "INPUT:PRES:HP  "
_PRES_LP = "INPUT:PRES:LP  "

_TEST3 = [_RST,_RSOC_OUT,_RF1,_CAL_OFF,_BAND_5K,_IFBAND_MANUAL + "10M"]


FREQ_TEST3_1M_100M = np.concat([
    np.arange(1_000_000,100_000_000,1000000),
    np.array([100_000_000-100,100_000_000])
]).astype(int)


FREQ_TEST3_10M_100M = np.concat([
    np.arange(10_000_000,100_000_000,1000000),
    np.array([100_000_000-100,100_000_000])
]).astype(int)


FREQ_TEST3_50M_240M = np.concat([
    np.arange(50_000_000,240_000_000,1000000),
    np.array([240_000_000-100,240_000_000])
]).astype(int)

FREQ_TEST3_150M_520M = np.concat([
    np.arange(150_000_000,520_000_000,2000000),
    np.array([520_000_000-100,520_000_000])
]).astype(int)

FREQ_TEST3_300M_960M = np.concat([
    np.arange(300_000_000,960_000_000,2000000),
    np.array([960_000_000-100,960_000_000])
]).astype(int)

FREQ_TEST3_300M_1500M = np.concat([
    np.arange(300_000_000,1_500_000_000,2500000),
    np.array([1_500_000_000-100,1_500_000_000])
]).astype(int)

FREQ_TEST3_700M_2500M = np.concat([
    np.arange(700_000_000,2_500_000_000,2500000),
    np.array([2_500_000_000-100,2_500_000_000])
]).astype(int)

FREQ_TEST3_2000M_4500M = np.concat([
    np.arange(2_000_000_000,4_500_000_000,2500000),
    np.array([4_500_000_000-100,4_500_000_000])
]).astype(int)

FREQ_TEST3_4000M_7500M = np.concat([
    np.arange(4_000_000_000,7_500_000_000,2500000),
    np.array([7_500_000_000-100,7_500_000_000])
]).astype(int)


def manual_pfileter(c,hp,lp):
    return [_PRES_FRQ + str(int(c)),  _PRES_HP + str(int(hp)), _PRES_LP + str(int(lp)) ]


TEST3_1435_CENTER_HZ = 1_435_000_000  # Word title: Preselector 1435 MHz

CFG_TEST3 = {
    "TEST3_10M.txt"    : (FREQ_TEST3_1M_100M,     _TEST3 + [_GAIN_OFF,_PRES_PATH + "10"  ]),
    "TEST3_20M.txt"    : (FREQ_TEST3_1M_100M,     _TEST3 + [_GAIN_OFF,_PRES_PATH + "20"  ]),
    "TEST3_30M.txt"    : (FREQ_TEST3_1M_100M,     _TEST3 + [_GAIN_OFF,_PRES_PATH + "30"  ]),
    "TEST3_50M.txt"    : (FREQ_TEST3_10M_100M,    _TEST3 + [_GAIN_OFF,_PRES_PATH + "520", _PRES_FRQ + str(int(50e6))  ]),
    "TEST3_120M.txt"   : (FREQ_TEST3_50M_240M,    _TEST3 + [_GAIN_OFF,_PRES_PATH + "520", _PRES_FRQ + str(int(120e6)) ]),
    "TEST3_260M.txt"   : (FREQ_TEST3_150M_520M,   _TEST3 + [_GAIN_OFF,_PRES_PATH + "520", _PRES_FRQ + str(int(260e6)) ]),
    "TEST3_480M.txt"   : (FREQ_TEST3_300M_960M,   _TEST3 + [_GAIN_OFF,_PRES_PATH + "520", _PRES_FRQ + str(int(480e6)) ]),
    "TEST3_735M.txt"   : (FREQ_TEST3_300M_1500M,  _TEST3 + [_GAIN_OFF,_PRES_PATH + "8000"] + manual_pfileter(735e6,690e6,750e6)),
    "TEST3_1435M.txt"  : (FREQ_TEST3_700M_2500M,  _TEST3 + [_GAIN_OFF,_PRES_PATH + "8000"] + manual_pfileter(TEST3_1435_CENTER_HZ,1400e6,1450e6)),
    "TEST3_2850M.txt"  : (FREQ_TEST3_2000M_4500M, _TEST3 + [_GAIN_OFF,_PRES_PATH + "8000"] + manual_pfileter(2850e6,2770e6,3000e6)),
    "TEST3_5400M.txt" : (FREQ_TEST3_4000M_7500M,  _TEST3 + [_GAIN_OFF,_PRES_PATH + "8000"] + manual_pfileter(5400e6,5190e6,5470e6)),
}





from datetime import datetime, timezone
from pathlib import Path
from measurement import SweepMeasurement


# Source: IC26-245013-02 Word Test3 titles/captions. These are acceptance
# ranges, NOT the wider sweep extents. A title giving only a center is checked
# at that center point; no undocumented passband width is assumed.
TEST3_LIMIT_OFFSET_DB = -3.0
PRESELECTOR_POWER_DBM = -30.0
TEST3_RANGES_HZ = {
    'TEST3_10M': (1e6, 10e6),
    'TEST3_20M': (10e6, 20e6),
    'TEST3_30M': (20e6, 30e6),
    'TEST3_50M': (50e6, 50e6),
    'TEST3_120M': (120e6, 120e6),
    'TEST3_260M': (260e6, 260e6),
    'TEST3_480M': (480e6, 480e6),
    'TEST3_735M': (690e6, 750e6),
    'TEST3_1435M': (1400e6, 1450e6),
    'TEST3_2850M': (2770e6, 3000e6),
    'TEST3_5400M': (5190e6, 5470e6),
}
TEST3_TITLES = {
    'TEST3_10M': 'Preselector 1 MHz to 10 MHz',
    'TEST3_20M': 'Preselector 10 MHz to 20 MHz',
    'TEST3_30M': 'Preselector 20 MHz to 30 MHz',
    'TEST3_50M': 'Preselector 50 MHz',
    'TEST3_120M': 'Preselector 120 MHz',
    'TEST3_260M': 'Preselector 260 MHz',
    'TEST3_480M': 'Preselector 480 MHz',
    'TEST3_735M': 'Preselector 735 MHz, HP 690 MHz, LP 750 MHz',
    'TEST3_1435M': 'Preselector 1435 MHz, HP 1400 MHz, LP 1450 MHz',
    'TEST3_2850M': 'Preselector 2850 MHz, HP 2770 MHz, LP 3000 MHz',
    'TEST3_5400M': 'Preselector 5400 MHz, HP 5190 MHz, LP 5470 MHz',
}


def measure_test3(device, generator, frequencies, commands, *, name='',
                  target_power_dbm=PRESELECTOR_POWER_DBM, attenuator_db=0.,
                  dwell_sec=.1, operator='', temperature='', checkpoint=None,
                  wait=None, on_row=None):
    """External-generator sweep, absolute RMS dBm, same dwell setup as Test1."""
    from cfg_test1 import measure_test1
    import time
    return measure_test1(device,generator,frequencies,commands,name=name,
        target_power_dbm=target_power_dbm,attenuator_db=attenuator_db,
        dwell_sec=dwell_sec,operator=operator,temperature=temperature,
        checkpoint=checkpoint,wait=wait or time.sleep,on_row=on_row)


def limit_dbm(reference_dbm):
    return float(reference_dbm)+TEST3_LIMIT_OFFSET_DB


def evaluate_test3(measurement):
    """All measured in-band levels must be at least reference minus 3 dB."""
    if not measurement.has_data() or measurement.reference_dbm is None:
        return False
    band = TEST3_RANGES_HZ.get(Path(measurement.name).stem)
    if band is None:
        return False
    low,high = band
    frequencies = np.asarray(measurement.freq_hz)
    inside = (frequencies >= low) & (frequencies <= high)
    if not np.any(inside) or frequencies[0] > low or frequencies[-1] < high:
        return False
    return bool(np.all(np.asarray(measurement.limit_dB)[inside] >= limit_dbm(measurement.reference_dbm)))


# Edit these values and the function below to define this test's Word section.
REPORT_TITLE = 'Test3 Preselector verification'
REPORT_DESCRIPTION = ('External-generator measurements of the configured preselector paths. '
    'In-range RMS levels must be at least the saved reference power minus 3 dB.')
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
        add_measurement_heading(document, measurement,
            title=TEST3_TITLES.get(Path(measurement.name).stem,measurement.name),
            passed=evaluate_test3(measurement))
        if not measurement.has_data():
            document.add_paragraph('The saved measurement contains no complete data.')
            continue
        display_values = np.asarray(measurement.limit_dB) + DISPLAY_OFFSET_DB
        bounds = None
        if measurement.reference_dbm is not None:
            bounds = (limit_dbm(measurement.reference_dbm)+DISPLAY_OFFSET_DB,)
        band = TEST3_RANGES_HZ.get(Path(measurement.name).stem)
        if band is not None:
            low,high = band
            scope = f'{low/1e6:g} MHz' if low == high else f'{low/1e6:g} to {high/1e6:g} MHz'
            details = f'Evaluated frequencies: {scope}.'
            if measurement.reference_dbm is not None:
                details += (f' Reference {measurement.reference_dbm:g} dBm '
                    f'({measurement.reference_dbm+DISPLAY_OFFSET_DB:.2f} dBµV); '
                    f'lower limit {bounds[0]:.2f} dBµV (−3 dB).')
            document.add_paragraph(details)
        if REPORT_CHART:
            add_chart(document, measurement.freq_hz, {'Measured': display_values},
                      ylabel=f'Level ({DISPLAY_UNIT})',limits=bounds,passed=evaluate_test3(measurement))
