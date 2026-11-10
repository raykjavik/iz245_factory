"""Compatibility index. Edit test procedures and report content in cfg_* modules."""
import numpy as np
from cfg_common import (
    FREQ_AXIS_FULL_RANGE_HZ,
    FREQ_AXIS_CH2_HZ,
    FREQ_AXIS_PRES_10M_HZ,
    FREQ_AXIS_PRES_20M_HZ,
    FREQ_AXIS_PRES_30M_HZ,
    FREQ_AXIS_PRES_LOW_HZ,
    FREQ_AXIS_PRES_HIGH_HZ,
    FREQ_AXIS_BASEBAND_HZ,
    _BAND_5K,
    _CAL_ON,
    _CAL_OFF,
    _IFBAND_AUTO,
    _BASE_BAND,
    _RF1,
    _RF2,
    _GAIN_ON,
    _GAIN_OFF,
    _GAIN_10DB,
    _GAIN_20DB,
    _IFBAND_MANUAL,
    _PRESELECTOR_OFF,
    _PRESELECTOR_ON,
    _PG_ON,
    _PG_OFF,
    _PRES_PATH,
    _RST
)


from cfg_calib import CFG_CALIB_RF1, CFG_PCALIB, CFG_CALIB_RF2
from cfg_test1 import CFG_TEST1_RF1, CFG_TEST1_RF2
from cfg_test2 import CFG_TEST2, CFG_TEST2_RF2
from cfg_test3 import (CFG_TEST3, manual_pfileter, FREQ_TEST3_1M_100M, FREQ_TEST3_10M_100M, FREQ_TEST3_50M_240M, FREQ_TEST3_150M_520M, FREQ_TEST3_300M_960M, FREQ_TEST3_300M_1500M, FREQ_TEST3_700M_2500M, FREQ_TEST3_2000M_4500M, FREQ_TEST3_4000M_7500M)
from cfg_test4 import CFG_TEST4, FREQ_TEST4_50M_8G
from cfg_test_5_6 import TEST_5_6, CFG_NOISE_DENSITY
from cfg_test8 import CFG_TEST8, TEST8
from cfg_test_7 import (CFG_TEST7_RF1, CFG_TEST7_RF2, FREQ_TEST7_RF1, FREQ_TEST7_RF2,
                        TEST7_TWO_TONE_COMMANDS)
# New controller-facing format. Existing sweep dictionaries remain compatible.
from measurement_specs import SweepSpec, CALIB_POWER, VERIFICATION_POW


import cfg_calib, cfg_test1, cfg_test2, cfg_test3, cfg_test4

def _sweep_specs(group, *, generator=False, storage='tests', power=None, kind=None, display=None):
    return {name: SweepSpec(frequencies=frequencies, commands=tuple(commands),
                kind=kind or ('generator_sweep' if generator else 'receiver_sweep'),
                storage=storage, unit='dB/Hz' if kind == 'test2' else 'dBm' if kind in ('test1','test3','test4') else 'dB', power_dbm=power,
                display_unit=display.DISPLAY_UNIT if display else 'dB',
                display_offset_db=display.DISPLAY_OFFSET_DB if display else 0.0,
                power_setting=('preselector_power_dbm' if kind == 'test3' else 'calibration_power_dbm' if storage == 'calib' else 'verification_power_dbm')
                              if generator else None)
            for name, (frequencies, commands) in group.items()}


MEASUREMENT_SPECS = {
    **_sweep_specs({**CFG_CALIB_RF1, **CFG_PCALIB, **CFG_CALIB_RF2},
                  generator=True, storage='calib', power=CALIB_POWER, kind='calibration',display=cfg_calib),
    **_sweep_specs({**CFG_TEST1_RF1, **CFG_TEST1_RF2}, generator=True, power=VERIFICATION_POW, kind='test1',display=cfg_test1),
    **_sweep_specs({**CFG_TEST2, **CFG_TEST2_RF2}, kind='test2',display=cfg_test2),
    **_sweep_specs(CFG_TEST3,generator=True,power=cfg_test3.PRESELECTOR_POWER_DBM,kind='test3',display=cfg_test3),
    **_sweep_specs(CFG_TEST4, kind='test4',display=cfg_test4),
}

# To add a measurement: define its cfg_* procedure and descriptor, then add
# a named MeasurementController method and an explicit case in measure().



MEASUREMENT_SPECS.update(CFG_NOISE_DENSITY)
from measurement_specs import IP3Spec
MEASUREMENT_SPECS.update({
    name: IP3Spec(frequencies=frequencies, commands=tuple(commands))
    for name, (frequencies, commands) in {**CFG_TEST7_RF1, **CFG_TEST7_RF2}.items()
})

MEASUREMENT_SPECS.update(CFG_TEST8)
