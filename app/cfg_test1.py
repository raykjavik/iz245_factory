"""Test1 calibration verification: configuration, acquisition and acceptance.

No Qt, controller, project, SSH or file-writing dependency. Connections are
already open. on_row(frequency_hz, reading_dbm) reports each completed point.
checkpoint() handles pause/abort; wait(seconds) is an abortable settling wait
when called by the application. Plain scripts can omit both callbacks.
"""

from docx.oxml import OxmlElement
import report_tools

# Presentation only: acquired/stored values are never converted here.
DISPLAY_UNIT = 'dBµV'
DISPLAY_OFFSET_DB = 107.0  # Rounded 50-ohm display convention; native dBm/acceptance unchanged.
TEST1_LIMITS_DB = (-2.0, 2.0)
CHART_LOG_X = False
REPORT_GHZ_TICKS_HZ = tuple(value*1e9 for value in range(1,8))

from datetime import datetime, timezone
from pathlib import Path
import time
import numpy as np
from measurement import SweepMeasurement
from cfg_common import sweep_bandwidth_hz
from cfg_common import (
    _RST, _RF1, _RF2, _CAL_ON, _BAND_5K,
    _GAIN_OFF, _GAIN_ON, _PRESELECTOR_OFF, _PRESELECTOR_ON,
    _PG_ON, _IFBAND_MANUAL,_RSOC_OUT,
)
from iz245.device import Device, RSGenerator



# IC26-245013-02 Test1 result tables: RF1 has 436 points; RF2 has 46.
FREQ_TEST1_RF1 = np.concatenate([
    np.arange(1, 11), np.arange(12, 71, 2), np.arange(90, 7991, 20),
]).astype(np.int64) * 1_000_000

# The Word RF2 table contains Hz values, although its header says MHz.
FREQ_TEST1_RF2 = np.concatenate([
    np.arange(1, 11)*1_000_000,
    np.arange(12, 79, 2)*1_000_000,
    np.array([79_999_900, 80_000_000]),
]).astype(np.int64)


_TEST1_RF1 = [_RST,_RSOC_OUT,_RF1,_CAL_ON,_BAND_5K]
CFG_TEST1_RF1 = {
    "TEST1_RF1_GAIN_OFF_PRESESLECTOR_OFF_IFBAND_470k.txt"        : (FREQ_TEST1_RF1,_TEST1_RF1+[_GAIN_OFF,_PRESELECTOR_OFF,_IFBAND_MANUAL + "470k"]),
    "TEST1_RF1_GAIN_OFF_PRESESLECTOR_OFF_IFBAND_10M.txt"         : (FREQ_TEST1_RF1,_TEST1_RF1+[_GAIN_OFF,_PRESELECTOR_OFF,_IFBAND_MANUAL + "10M"]),
    "TEST1_RF1_GAIN_OFF_PRESESLECTOR_OFF_IFBAND_50M.txt"         : (FREQ_TEST1_RF1,_TEST1_RF1+[_GAIN_OFF,_PRESELECTOR_OFF,_IFBAND_MANUAL + "50M"]),
    "TEST1_RF1_GAIN_OFF_PRESESLECTOR_OFF_IFBAND_80M.txt"         : (FREQ_TEST1_RF1,_TEST1_RF1+[_GAIN_OFF,_PRESELECTOR_OFF,_IFBAND_MANUAL + "80M"]),
    "TEST1_RF1_GAIN_ON_PRESESLECTOR_OFF_IFBAND_10M.txt"          : (FREQ_TEST1_RF1,_TEST1_RF1+[_GAIN_ON ,_PRESELECTOR_OFF,_IFBAND_MANUAL + "10M"]),
    "TEST1_RF1_GAIN_OFF_PRESESLECTOR_ON_IFBAND_10M.txt"          : (FREQ_TEST1_RF1,_TEST1_RF1+[_GAIN_OFF ,_PRESELECTOR_ON,_IFBAND_MANUAL + "10M"]),
    "TEST1_RF1_GAIN_OFF_PRESESLECTOR_GAIN_IFBAND_10M.txt"        : (FREQ_TEST1_RF1,_TEST1_RF1+[_GAIN_OFF,_PG_ON,_PRESELECTOR_ON,_IFBAND_MANUAL + "10M"]),
}

_TEST1_RF2 = [_RF2,_RSOC_OUT,_CAL_ON,_BAND_5K]
CFG_TEST1_RF2 = {
    "TEST1_RF2_GAIN_OFF.txt":(FREQ_TEST1_RF2,_TEST1_RF2+[_GAIN_OFF]),
    "TEST1_RF2_GAIN_ON.txt" :(FREQ_TEST1_RF2,_TEST1_RF2+[_GAIN_ON ]),
}



def measure_test1(
    device,
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
    """Return absolute RMS received power, in dBm.

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
            values.append(reading_dbm)
            if on_row is not None:
                on_row(frequency, reading_dbm)

        return SweepMeasurement(
            name=Path(name).stem, freq_hz=frequencies.copy(), limit_dB=np.asarray(values),
            available=True, datetime=datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
            operator=operator, temperature=temperature, unit='dBm', reference_dbm=target_power_dbm,
            dwell_sec=dwell_sec,bandwidth_hz=sweep_bandwidth_hz(commands),
        )
    finally:
        generator.cmd('OUTP:STAT 0')


def absolute_dbm(measurement):
    """New files store dBm. Old dB deviation files need their saved reference."""
    values = np.asarray(measurement.limit_dB, dtype=float)
    if measurement.unit == 'dBm':
        return values
    if measurement.unit == 'dB' and measurement.reference_dbm is not None:
        return values + measurement.reference_dbm
    raise ValueError('Test1 data needs dBm units, or a saved reference for legacy deviations.')


def limits_dbm(reference_dbm):
    return tuple(float(reference_dbm) + bound for bound in TEST1_LIMITS_DB)


def evaluate_test1(measurement: SweepMeasurement):
    """Inclusive +/-2 dB about this measurement's saved DUT input reference."""
    if not measurement.has_data() or measurement.reference_dbm is None:
        return False
    try:
        values = absolute_dbm(measurement)
        lower, upper = limits_dbm(measurement.reference_dbm)
    except (ValueError, TypeError):
        return False
    return bool(np.all((values >= lower) & (values <= upper)))


def configuration_label(name):
    name = Path(name).stem
    lna = 'ON' if '_GAIN_ON' in name else 'OFF'
    if '_RF2_' in name:
        return f'LNA {lna}'
    bandwidth = name.split('IFBAND_')[-1]
    bandwidth = bandwidth.replace('470k', '470 kHz').replace('10M','10 MHz').replace('50M','50 MHz').replace('80M','80 MHz')
    pres = 'ON + gain' if '_PRESESLECTOR_GAIN_' in name else 'ON' if '_PRESESLECTOR_ON_' in name else 'OFF'
    return f'IF {bandwidth}\nLNA {lna}\nPRES {pres}'


def result_table(measurements, rf):
    """Manual-style matrix, shared by GUI/report. Never interpolate missing data."""
    configs = CFG_TEST1_RF1 if rf == 'RF1' else CFG_TEST1_RF2
    by_name = {Path(m.name).stem:m for m in measurements if m.has_data()}
    columns = []
    for name in configs:
        measurement = by_name.get(Path(name).stem)
        if measurement is None:
            continue
        try:
            values = absolute_dbm(measurement) + DISPLAY_OFFSET_DB
        except ValueError:
            continue
        columns.append((configuration_label(name), dict(zip(measurement.freq_hz,values))))
    frequencies = sorted({f for _,values in columns for f in values})
    headers = ['Freq.\n(MHz)'] + [label + '\n(dBµV)' for label,_ in columns]
    rows = [[f/1e6]+[values.get(f) for _,values in columns] for f in frequencies]
    return headers, rows


REPORT_TITLE = 'Test1 Calibration verification'
REPORT_DESCRIPTION = ('Verification of receiver level accuracy using the calibrated generator setup. '
    'RMS received levels are shown in dBµV into 50 ohms. Limits are ±2 dB from each saved reference power.')
REPORT_CHART = True
REPORT_TABLE = True


def add_report(document, measurements):
    """RF1/RF2 charts followed by their frequency-by-configuration result table."""
    report_tools.add_test_heading(document, REPORT_TITLE, REPORT_DESCRIPTION)
    if not measurements:
        report_tools.no_measurements(document)
    for rf, configs in (('RF1',CFG_TEST1_RF1),('RF2',CFG_TEST1_RF2)):
        stems = {Path(name).stem for name in configs}
        group = [m for m in measurements if Path(m.name).stem in stems]
        for measurement in group:
            report_tools.add_measurement_heading(document, measurement,
                title=f'{rf} · '+configuration_label(measurement.name).replace('\n', ', '),
                passed=evaluate_test1(measurement))
            if not measurement.has_data():
                document.add_paragraph('The saved measurement contains no complete data.')
                continue
            try:
                values = absolute_dbm(measurement)+DISPLAY_OFFSET_DB
            except ValueError as exc:
                document.add_paragraph(str(exc))
                continue
            bounds = None
            if measurement.reference_dbm is not None:
                bounds = tuple(value+DISPLAY_OFFSET_DB for value in limits_dbm(measurement.reference_dbm))
                reference = measurement.reference_dbm+DISPLAY_OFFSET_DB
                document.add_paragraph(f'Reference {reference:.0f} dBµV '
                    f'({measurement.reference_dbm:g} dBm). Inclusive limits '
                    f'{bounds[0]:.0f} to {bounds[1]:.0f} dBµV.')
            else:
                document.add_paragraph('Saved reference missing; acceptance cannot be established.')
            if REPORT_CHART:
                report_tools.add_chart(document, measurement.freq_hz, {'Measured':values},
                    ylabel='RMS received level (dBµV)',log_x=CHART_LOG_X,
                    limits=bounds,passed=evaluate_test1(measurement),
                    x_ticks=REPORT_GHZ_TICKS_HZ if rf == 'RF1' else None)
        if REPORT_TABLE and group:
            headers, rows = result_table(group,rf)
            if rows:
                document.add_heading(f'{rf} measured levels',level=3)
                table = report_tools.add_table(document,headers,
                    [['—' if v is None else f'{v:.2f}' if i else f'{v:g}'
                      for i,v in enumerate(row)] for row in rows],
                    style='Test1 Results',text_style='Test1 Table Text',
                    header_style='Test1 Table Header')
                if table is not None:
                    for row in table.rows:
                        row._tr.get_or_add_trPr().append(OxmlElement('w:cantSplit'))
