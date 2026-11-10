"""Domain configuration, measurement procedure and report content."""
import report_tools
# Presentation for each selectable metric: label, attribute, unit, display offset.
DISPLAY_METRICS = (
    ('IP3','ip3_dbm','dBm',0.0),
    ('SFDR','sfdr_db','dB',0.0),
    ('NF','nf_db','dB/Hz',0.0),
    ('P signal','signal_dbm','dBm',0.0),
    ('P IM3','im3_dbm','dBm',0.0),
)

import numpy as np
from iz245.device import Device
from cfg_common import (_CAL_ON, _RF1, _RF2, _GAIN_ON, _GAIN_OFF, _IFBAND_MANUAL, _PRESELECTOR_OFF, _PRESELECTOR_ON, _PG_OFF, _RST, _RSOC_OUT)

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

# R&S SMATE200A Operating Manual 1401.0940.32-14, printed pages 770/772.
# DUT reference output -> SMATE200A REF IN. One reference serves both RF paths.
SMATE200A_REFERENCE_COMMANDS = (
    'SOUR:ROSC:EXT:FREQ 10MHZ',
    'SOUR:ROSC:SOUR EXT',
)
TEST7_NOISE_BANDWIDTH_HZ = 100e3
TEST7_SIGNAL_BANDWIDTH_HZ = 3e3


from detector import read_detector


def configure_two_tones(generator, f1_hz, f2_hz, target_dbm, attenuator_db):
    """Two SMATE200A RF paths; compensate each tone as in Test1.

    Static path loss is added to POW. Only frequency-dependent cable correction
    uses POW:OFFS. R&S level offset is display level minus RF output level.
    """
    power_dbm = target_dbm + attenuator_db
    for channel, frequency in ((1, f1_hz), (2, f2_hz)):
        correction = (generator.get_cable_offset(frequency)
                      if getattr(generator, 'cable_calib', None) is not None else 0.)
        generator.cmds([
            f'SOUR{channel}:FREQ:MODE CW', f'SOUR{channel}:POW:MODE CW',
            f'SOUR{channel}:MOD:ALL:STAT OFF',
            f'SOUR{channel}:FREQ {frequency:.2f}Hz',
            f'SOUR{channel}:POW:OFFS {correction:g}',
            f'SOUR{channel}:POW {power_dbm:g}',
        ])


def measure_test7(device:Device, generator, spec, *, name='', noise_dwell_sec=1.0, signal_dwell_sec=0.1,
                  headroom_db=3.01, attenuator_db=0., operator='', temperature='',
                  checkpoint=lambda:None, check_cancel=lambda:None,
                  wait=time.sleep, on_row=lambda result:None, on_progress=lambda:None):
    result=IP3Measurement(name=Path(name).stem,operator=operator,temperature=temperature,
        tone_spacing_hz=spec.tone_spacing_hz,noise_bandwidth_db=spec.noise_bandwidth_db,
        per_tone_headroom_db=headroom_db)
    rows=[]
    try:
        generator.cmds(['OUTP1:STAT 0','OUTP2:STAT 0'])
        checkpoint()
        check_cancel()
        # Reference output must be enabled after any reset in spec.commands.
        device._main_scpi_commands(list(spec.commands)+[_RSOC_OUT])
        device._main_scpi_query('*OPC?')
        check_cancel()
        generator.cmds(list(SMATE200A_REFERENCE_COMMANDS))
        generator.opc()
        for frequency in spec.frequencies:
            checkpoint()
            check_cancel()

            f1=float(frequency)
            f2=f1+spec.tone_spacing_hz

            generator.cmds(['OUTP1:STAT 0','OUTP2:STAT 0'])
            generator.opc()
            device._main_scpi_command(f'BAND {TEST7_NOISE_BANDWIDTH_HZ:g}')
            device.tune_awaited(f1)
            vals = read_detector(device,noise_dwell_sec,wait=wait,check_cancel=check_cancel)
            full_range=vals[-3]
            noise_hz = vals[-4]  # Receiver-provided normalized NF density, dB/Hz.
            target_dbm=full_range-headroom_db
            checkpoint()
            device._main_scpi_command(f'BAND {TEST7_SIGNAL_BANDWIDTH_HZ:g}')
            device._main_scpi_query('*OPC?')
            configure_two_tones(generator,f1,f2,target_dbm,attenuator_db)
            check_cancel()
            generator.cmds(['OUTP1:STAT 1','OUTP2:STAT 1'])
            generator.opc()
            signal_dbm=read_detector(device,signal_dwell_sec,wait=wait,check_cancel=check_cancel)[3]
            
            checkpoint()
            device.tune_awaited(f2+spec.tone_spacing_hz)
            im3_dbm=read_detector(device,signal_dwell_sec,wait=wait,check_cancel=check_cancel)[3]
            
            nf_db=noise_hz  # Already normalized by the receiver; do not add 174.
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
        generator.cmds(['OUTP1:STAT 0','OUTP2:STAT 0'])


def evaluate_test7(measurement):
    return None


REPORT_CHART = False
REPORT_TABLE = True


def add_report(document, measurements):
    report_tools.add_test_heading(document, 'Test7 IP3 and SFDR',
        'Two tone measurements of signal and intermodulation levels, with calculated IP3 and SFDR, and receiver-provided NF density (dB/Hz).')
    if not measurements:
        report_tools.no_measurements(document)
    for measurement in measurements:
        report_tools.add_measurement_heading(document, measurement, passed=evaluate_test7(measurement))
        document.add_paragraph(f'Tone spacing {measurement.tone_spacing_hz:g} Hz. '
            f'Per tone headroom {measurement.per_tone_headroom_db:g} dB below full range.')
        if measurement.noise_unit != 'dB/Hz':
            document.add_paragraph('Legacy Test7 noise conversion: remeasure to obtain receiver-provided NF density and corrected SFDR.')
            continue
        if not measurement.has_data():
            document.add_paragraph('The saved measurement contains no complete data.')
            continue
        if REPORT_TABLE:
            report_tools.add_table(document, ['Frequency (MHz)', 'P signal (dBm)', 'P IM3 (dBm)',
                                 'IP3 (dBm)', 'NF density (dB/Hz)', 'SFDR (dB)'],
                      zip(*(getattr(measurement, field) for field in IP3_ARRAY_FIELDS)))
        if REPORT_CHART:
            report_tools.add_chart(document, measurement.freq_mhz*1e6, {'IP3':measurement.ip3_dbm}, ylabel='IP3 (dBm)',passed=evaluate_test7(measurement))
            report_tools.add_chart(document, measurement.freq_mhz*1e6, {'SFDR':measurement.sfdr_db}, ylabel='SFDR (dB)',passed=evaluate_test7(measurement))
