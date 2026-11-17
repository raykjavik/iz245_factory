"""Measurement index; domain configuration and procedures live in cfg_* modules."""
from cfg_calib import CFG_CALIB_RF1, CFG_PCALIB, CFG_CALIB_RF2
from cfg_test1 import CFG_TEST1_RF1, CFG_TEST1_RF2
from cfg_test2 import CFG_TEST2, CFG_TEST2_RF2
from cfg_test3 import CFG_TEST3
from cfg_test4 import CFG_TEST4
from cfg_test_5_6 import CFG_NOISE_DENSITY
from cfg_test_7 import CFG_TEST7_RF1, CFG_TEST7_RF2
from cfg_test8 import CFG_TEST8
from measurement_specs import SweepSpec, IP3Spec, CALIB_POWER, VERIFICATION_POW
import cfg_calib, cfg_test1, cfg_test2, cfg_test3, cfg_test4

def _sweep_specs(group, *, generator=False, storage='tests', power=None, kind=None, display=None):
    return {name: SweepSpec(frequencies=frequencies, commands=tuple(commands),
                kind=kind,
                storage=storage, unit='dBm' if kind in ('test1','test3','test4') else 'dB',
                quantity='noise_figure' if kind=='test2' else 'calibration' if kind=='calibration' else 'power', power_dbm=power,
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
MEASUREMENT_SPECS.update({
    name: IP3Spec(frequencies=frequencies, commands=tuple(commands))
    for name, (frequencies, commands) in {**CFG_TEST7_RF1, **CFG_TEST7_RF2}.items()
})

MEASUREMENT_SPECS.update(CFG_TEST8)
