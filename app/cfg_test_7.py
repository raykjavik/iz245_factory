"""Domain configuration, measurement procedure and report content."""
# Presentation for each selectable metric: label, attribute, unit, display offset.
DISPLAY_METRICS = (
    ('IP3','ip3_dbm','dBm',0.0),
    ('SFDR','sfdr_db','dB',0.0),
    ('NF','nf_db','dB',0.0),
    ('P signal','signal_dbm','dBm',0.0),
    ('P IM3','im3_dbm','dBm',0.0),
)

import numpy as np
from iz245.device import Device
from cfg_common import (_CAL_ON, _RF1, _RF2, _GAIN_ON, _GAIN_OFF, _IFBAND_MANUAL, _PRESELECTOR_OFF, _PRESELECTOR_ON, _PG_OFF, _RST)

FREQ_TEST7_RF1 = np.array([
    38e6, 118e6, 260e6, 520e6, 1080e6, 2600e6, 3860e6, 5650e6,
]).astype(int)
FREQ_TEST7_RF2 = np.array([3.5e6, 27e6, 55e6]).astype(int)


# FREQ_TEST7_RF1 = np.arange(10_000_000,6000_000_000,	10_000_000).astype(int)
# FREQ_TEST7_RF2 = np.array([3.5e6, 27e6, 55e6]).astype(int)



_TEST7_RF1 = [_RST, _RF1, _CAL_ON, _IFBAND_MANUAL + '10M', _PG_OFF]
_TEST7_RF2 = [_RST, _RF2, _CAL_ON, _IFBAND_MANUAL + '10M']

CFG_TEST7_RF1 = {
    'TEST7_RF1_PRESELECTOR_OFF_GAIN_OFF.txt': (FREQ_TEST7_RF1, _TEST7_RF1 + [_PRESELECTOR_OFF, _GAIN_OFF]),
    'TEST7_RF1_PRESELECTOR_OFF_GAIN_ON.txt': (FREQ_TEST7_RF1, _TEST7_RF1 + [_PRESELECTOR_OFF, _GAIN_ON]),
    'TEST7_RF1_PRESELECTOR_ON_GAIN_OFF.txt': (FREQ_TEST7_RF1, _TEST7_RF1 + [_PRESELECTOR_ON, _GAIN_OFF]),
    'TEST7_RF1_PRESELECTOR_ON_GAIN_ON.txt': (FREQ_TEST7_RF1, _TEST7_RF1 + [_PRESELECTOR_ON, _GAIN_ON,]),
}
CFG_TEST7_RF2 = {
    'TEST7_RF2_GAIN_OFF.txt': (FREQ_TEST7_RF2, _TEST7_RF2 + [_GAIN_OFF]),
    'TEST7_RF2_GAIN_ON_ATT1_6_dB_ATT2_16.txt': (FREQ_TEST7_RF2, _TEST7_RF2 + [_GAIN_ON,"INPut[:RF2]:ATTenuator:RF1 6","INPut[:RF2]:ATTenuator:RF2 16"]),
}

# Legacy compatibility only; this domain now sends explicit two-channel SCPI.
TEST7_TWO_TONE_COMMANDS = None


from datetime import datetime, timezone
from pathlib import Path
from measurement import IP3Measurement, IP3_ARRAY_FIELDS
import time


def measure_test7(device:Device, generator, spec, *, name='', noise_dwell_sec=1.0, signal_dwell_sec=0.1,
                  headroom_db=3.01, attenuator_db=0., operator='', temperature='',
                  checkpoint=lambda:None, check_cancel=lambda:None,
                  on_row=lambda result:None, on_progress=lambda:None):
    result=IP3Measurement(name=Path(name).stem,operator=operator,temperature=temperature,
        tone_spacing_hz=spec.tone_spacing_hz,noise_bandwidth_db=spec.noise_bandwidth_db,
        per_tone_headroom_db=headroom_db)
    rows=[]
    try:
        device._main_scpi_commands(list(spec.commands))
        for frequency in spec.frequencies:
            checkpoint()
            check_cancel()

            f1=float(frequency)
            f2=f1+spec.tone_spacing_hz

            generator.cmds([f'OUTP1:STAT 0',f'OUTP2:STAT 0'])
            device._main_scpi_command("BAND 100k")
            device.tune_awaited(f1)
            generator.opc()
            device._main_scpi_command("DETector:CLEar")
            time.sleep(noise_dwell_sec)
            vals =    [float(x) for x in device._main_scpi_query('sense:data?').split(',') ] 
            device._main_scpi_command("BAND 3k")
            device._main_scpi_query("*opc?")
            full_range=vals[-3]
            noise_hz = vals[-4]
            target_dbm=full_range-headroom_db
            offset=-attenuator_db
           
            check_cancel()

            if getattr(generator,'cable_calib',None) is not None:
                generator.get_cable_offset(f2)
                offset-=generator.get_cable_offset(f1)

            generator.cmds([
                f'SOURCE1:FREQ {f1}',f'SOURCE2:FREQ {f2}',
                f'SOURCE1:POW {target_dbm}',f'SOURCE2:POW {target_dbm}',
                f'SOURCE1:POWER:OFFSET {offset}',f'SOURCE2:POWER:OFFSET {offset}',
            ])

            check_cancel()
            generator.cmds([f'OUTP1:STAT 1',f'OUTP2:STAT 1'])
            generator.opc()
            time.sleep(signal_dwell_sec)
            signal_dbm=device.measure_point_rms(signal_dwell_sec)
            
            device.tune_awaited(f2+spec.tone_spacing_hz)
            im3_dbm=device.measure_point_rms(signal_dwell_sec)
            
            nf_db=noise_hz+174.0
            ip3_dbm=signal_dbm+(signal_dbm-im3_dbm)/2.0
            sfdr_db=(2.0/3.0)*(ip3_dbm-(-174.0+nf_db+spec.noise_bandwidth_db))
            
            rows.append((f1/1e6,signal_dbm,im3_dbm,ip3_dbm,nf_db,sfdr_db))
            for attr,values in zip(IP3_ARRAY_FIELDS,np.asarray(rows).T):
                setattr(result,attr,values.copy())
            result.available=True
            
            on_row(result.snapshot())
            on_progress()

        result.datetime=datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
        return result
    finally:
        generator.cmds([f'OUTP1:STAT 0',f'OUTP2:STAT 0'])


def evaluate_test7(measurement):
    return None


REPORT_CHART = False
REPORT_TABLE = True


def add_report(document, measurements):
    from report_tools import (add_test_heading, add_measurement_heading, add_chart,
                              add_table, no_measurements)
    add_test_heading(document, 'Test7 IP3 and SFDR',
        'Two tone measurements of signal and intermodulation levels, with calculated IP3, noise figure and SFDR.')
    if not measurements:
        no_measurements(document)
    for measurement in measurements:
        add_measurement_heading(document, measurement, passed=evaluate_test7(measurement))
        document.add_paragraph(f'Tone spacing {measurement.tone_spacing_hz:g} Hz. '
            f'Per tone headroom {measurement.per_tone_headroom_db:g} dB below full range.')
        if not measurement.has_data():
            document.add_paragraph('The saved measurement contains no complete data.')
            continue
        if REPORT_TABLE:
            add_table(document, ['Frequency (MHz)', 'P signal (dBm)', 'P IM3 (dBm)',
                                 'IP3 (dBm)', 'NF (dB)', 'SFDR (dB)'],
                      zip(*(getattr(measurement, field) for field in IP3_ARRAY_FIELDS)))
        if REPORT_CHART:
            add_chart(document, measurement.freq_mhz*1e6, {'IP3':measurement.ip3_dbm}, ylabel='IP3 (dBm)',passed=evaluate_test7(measurement))
            add_chart(document, measurement.freq_mhz*1e6, {'SFDR':measurement.sfdr_db}, ylabel='SFDR (dB)',passed=evaluate_test7(measurement))
