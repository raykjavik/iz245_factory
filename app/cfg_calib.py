"""Domain configuration, measurement procedure and report content."""

# Presentation only: acquired/stored values are never converted here.
DISPLAY_UNIT = 'dB'
DISPLAY_OFFSET_DB = 0.0

import numpy as np
from cfg_common import (FREQ_AXIS_FULL_RANGE_HZ, FREQ_AXIS_CH2_HZ, FREQ_AXIS_PRES_10M_HZ, _RSOC_OUT,
                        FREQ_AXIS_PRES_20M_HZ, FREQ_AXIS_PRES_30M_HZ, FREQ_AXIS_PRES_LOW_HZ, FREQ_AXIS_PRES_HIGH_HZ, FREQ_AXIS_BASEBAND_HZ, _BAND_5K, _CAL_ON, _CAL_OFF, _IFBAND_AUTO, _BASE_BAND, _RF1, _RF2, _GAIN_ON, _GAIN_OFF, _GAIN_10DB, _GAIN_20DB, _IFBAND_MANUAL, _PRESELECTOR_OFF, _PG_ON, _PG_OFF, _PRES_PATH, _RST)
from iz245.device import Device, RSGenerator

_CALIB_RF1 = [_RST,_RSOC_OUT,_CAL_OFF,_BAND_5K,_RF1,_PRESELECTOR_OFF]
_CALIB_BASE_BAND= [_RST,_RSOC_OUT,_CAL_OFF,_BAND_5K,_RF1,_BASE_BAND]

CFG_CALIB_RF1 = {
    "CALIBRATION_GAIN_10dB_IFBAND_10M.txt"  : (FREQ_AXIS_FULL_RANGE_HZ, _CALIB_RF1 + [ _GAIN_10DB, _IFBAND_MANUAL + "10M" ]),
    "CALIBRATION_GAIN_10dB_IFBAND_470k.txt" : (FREQ_AXIS_FULL_RANGE_HZ, _CALIB_RF1 + [ _GAIN_10DB, _IFBAND_MANUAL + "470k"]),
    "CALIBRATION_GAIN_10dB_IFBAND_50M.txt"  : (FREQ_AXIS_FULL_RANGE_HZ, _CALIB_RF1 + [ _GAIN_10DB, _IFBAND_MANUAL + "50M" ]),
    "CALIBRATION_GAIN_10dB_IFBAND_80M.txt"  : (FREQ_AXIS_FULL_RANGE_HZ, _CALIB_RF1 + [ _GAIN_10DB, _IFBAND_MANUAL + "80M" ]),
    "CALIBRATION_GAIN_20dB_IFBAND_10M.txt"  : (FREQ_AXIS_FULL_RANGE_HZ, _CALIB_RF1 + [ _GAIN_20DB, _IFBAND_MANUAL + "10M" ]),
    "CALIBRATION_GAIN_20dB_IFBAND_470k.txt" : (FREQ_AXIS_FULL_RANGE_HZ, _CALIB_RF1 + [ _GAIN_20DB, _IFBAND_MANUAL + "470K"]),
    "CALIBRATION_GAIN_20dB_IFBAND_50M.txt"  : (FREQ_AXIS_FULL_RANGE_HZ, _CALIB_RF1 + [ _GAIN_20DB, _IFBAND_MANUAL + "50M" ]),
    "CALIBRATION_GAIN_20dB_IFBAND_80M.txt"  : (FREQ_AXIS_FULL_RANGE_HZ, _CALIB_RF1 + [ _GAIN_20DB, _IFBAND_MANUAL + "80M" ]),
    "CALIBRATION_GAIN_OFF_IFBAND_10M.txt"   : (FREQ_AXIS_FULL_RANGE_HZ, _CALIB_RF1 + [ _GAIN_OFF,  _IFBAND_MANUAL + "10M" ]),
    "CALIBRATION_GAIN_OFF_IFBAND_470k.txt"  : (FREQ_AXIS_FULL_RANGE_HZ, _CALIB_RF1 + [ _GAIN_OFF,  _IFBAND_MANUAL + "470K"]),
    "CALIBRATION_GAIN_OFF_IFBAND_50M.txt"   : (FREQ_AXIS_FULL_RANGE_HZ, _CALIB_RF1 + [ _GAIN_OFF,  _IFBAND_MANUAL + "50M" ]),
    "CALIBRATION_GAIN_OFF_IFBAND_80M.txt"   : (FREQ_AXIS_FULL_RANGE_HZ, _CALIB_RF1 + [ _GAIN_OFF,  _IFBAND_MANUAL + "80M" ]),
    "CALIBRATION_GAIN_ON_IFBAND_10M.txt"    : (FREQ_AXIS_FULL_RANGE_HZ, _CALIB_RF1 + [ _GAIN_ON,   _IFBAND_MANUAL + "10M" ]),
    "CALIBRATION_GAIN_ON_IFBAND_470k.txt"   : (FREQ_AXIS_FULL_RANGE_HZ, _CALIB_RF1 + [ _GAIN_ON,   _IFBAND_MANUAL + "470K"]),
    "CALIBRATION_GAIN_ON_IFBAND_50M.txt"    : (FREQ_AXIS_FULL_RANGE_HZ, _CALIB_RF1 + [ _GAIN_ON,   _IFBAND_MANUAL + "50M" ]),
    "CALIBRATION_GAIN_ON_IFBAND_80M.txt"    : (FREQ_AXIS_FULL_RANGE_HZ, _CALIB_RF1 + [ _GAIN_ON,   _IFBAND_MANUAL + "80M" ]),
    "CALIBRATION_BASEBAND_GAIN_10dB.txt"    : (FREQ_AXIS_BASEBAND_HZ,   _CALIB_BASE_BAND + [ _GAIN_10DB, _IFBAND_AUTO            ]),
    "CALIBRATION_BASEBAND_GAIN_20dB.txt"    : (FREQ_AXIS_BASEBAND_HZ,   _CALIB_BASE_BAND + [ _GAIN_20DB, _IFBAND_AUTO            ]),
    "CALIBRATION_BASEBAND_GAIN_OFF.txt"     : (FREQ_AXIS_BASEBAND_HZ,   _CALIB_BASE_BAND + [ _GAIN_OFF,  _IFBAND_AUTO            ]),
    "CALIBRATION_BASEBAND_GAIN_ON.txt"      : (FREQ_AXIS_BASEBAND_HZ,   _CALIB_BASE_BAND + [ _GAIN_ON,   _IFBAND_AUTO            ]),
}   



_PCALIB = [_RST,_CAL_ON,_BAND_5K,_IFBAND_AUTO,"FREQ:PLAN:BAND1:THR 80MHz",]

CFG_PCALIB = {
    "CALIBRATION_10MHZ_PRESELECTOR.txt"     : (FREQ_AXIS_PRES_10M_HZ,  _PCALIB + [_GAIN_OFF,_PRES_PATH + "10"  ]),
    "CALIBRATION_20MHZ_PRESELECTOR.txt"     : (FREQ_AXIS_PRES_20M_HZ,  _PCALIB + [_GAIN_OFF,_PRES_PATH + "20"  ]),
    "CALIBRATION_30MHZ_PRESELECTOR.txt"     : (FREQ_AXIS_PRES_30M_HZ,  _PCALIB + [_GAIN_OFF,_PRES_PATH + "30"  ]),
    "CALIBRATION_LOW_PRESELECTOR.txt"       : (FREQ_AXIS_PRES_LOW_HZ,  _PCALIB + [_GAIN_OFF,_PRES_PATH + "520" ]),
    "CALIBRATION_HIGH_PRESELECTOR.txt"      : (FREQ_AXIS_PRES_HIGH_HZ, _PCALIB + [_GAIN_OFF, _PG_OFF,_PRES_PATH + "8000"]),
    "CALIBRATION_HIGH_GAIN_PRESELECTOR.txt" : (FREQ_AXIS_PRES_HIGH_HZ, _PCALIB + [_GAIN_OFF, _PG_ON,_PRES_PATH + "8000"]),
}


CFG_CALIB_RF2 = {
    "CH2_CALIBRATION_GAIN_OFF.txt":(FREQ_AXIS_CH2_HZ,[_RF2,_GAIN_OFF]),
    "CH2_CALIBRATION_GAIN_ON.txt" :(FREQ_AXIS_CH2_HZ,[_RF2,_GAIN_ON ]),
}


from datetime import datetime, timezone
from pathlib import Path
import time
from measurement import SweepMeasurement
from cfg_common import sweep_bandwidth_hz

def measure_calibration(
    device:Device,
    generator:RSGenerator,
    frequencies,
    commands,
    *,
    name="",
    target_power_dbm=-50.0,
    attenuator_db=0.0,
    dwell_sec=0.1,
    generator_settle_sec=0.1,
    operator="",
    temperature="",
    checkpoint=None,
    wait=time.sleep,
    on_row=None,
):
    """Return deviations from target DUT input power, in dB.

    Positive attenuator_db is added once to generator POW. Only the existing
    frequency-dependent cable correction goes to SOURCE:POWER:OFFSET.
    This function owns RF output state, but never opens/closes connections.
    """
    values = []
    frequencies = np.asarray(frequencies)
    try:
        generator.cmd('OUTP:STAT 0')
        if checkpoint is not None:
            checkpoint()
        device._main_scpi_commands(list(commands)+[f"SWEEP:DWELL {dwell_sec}"])
        cable_enabled = getattr(generator, 'cable_calib', None) is not None

        generator.cmds(
            [
                'SOURCE:ROSC:SOUR EXT',
                f'POW {target_power_dbm + attenuator_db}',
                'SOURCE:POWER:OFFSET 0',
                'OUTP:STAT 1',
            ]
        )

        for frequency in frequencies:
            if checkpoint is not None:
                checkpoint()
            frequency = float(frequency)
            if cable_enabled:
                correction = generator.get_cable_offset(frequency)
                generator.cmd(f'SOURCE:POWER:OFFSET {correction}')
            # Use explicit tuning to avoid any driver fixed-loss fallback.
            generator.cmd(f'FREQ {frequency:.2f}Hz')
            device.tune_awaited(frequency)
            generator.opc()
            reading_dbm = float(device.measure_point_rms(dwell_sec))
            if checkpoint is not None:
                checkpoint()
            deviation_db = reading_dbm - target_power_dbm
            values.append(deviation_db)
            if on_row is not None:
                on_row(frequency, deviation_db)

        return SweepMeasurement(
            name=Path(name).stem, freq_hz=frequencies.copy(), limit_dB=np.asarray(values),
            available=True, datetime=datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
            operator=operator, temperature=temperature, unit='dB', reference_dbm=target_power_dbm,
            dwell_sec=dwell_sec,bandwidth_hz=sweep_bandwidth_hz(commands),
        )
    finally:
        generator.cmd('OUTP:STAT 0')




# Edit these values and the function below to define this test's Word section.
REPORT_TITLE = 'Calibration'
REPORT_DESCRIPTION = 'Receiver calibration deviations from the applied DUT input level.'
REPORT_CHART = False
REPORT_TABLE = False


def add_report(document, measurements):
    """Calibration acquisition tables are working data, not report content."""
    return None
