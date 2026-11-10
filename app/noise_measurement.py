"""Receiver-only noise sweep. No generator, Qt, project or file-writing dependency."""
from datetime import datetime, timezone
from pathlib import Path
import time
import numpy as np
from measurement import SweepMeasurement
from cfg_common import sweep_bandwidth_hz
from detector import read_detector


def measure_noise_sweep(device, frequencies, commands, *, quantity, name='', dwell_sec=.1,
                        operator='', temperature='', checkpoint=None, on_row=None,
                        wait=time.sleep, check_cancel=lambda:None):
    """Use RMS for voltage noise, or the calibrated density field directly."""
    device._main_scpi_commands(list(commands)+[f'SWEEP:DWELL {dwell_sec:g}'])
    values=[]
    for frequency in frequencies:
        if checkpoint is not None:checkpoint()
        device.tune_awaited(frequency)
        response=read_detector(device,dwell_sec,wait=wait,check_cancel=check_cancel)
        value=response[3] if quantity == 'rms_power' else response[-4]
        if checkpoint is not None:checkpoint()
        values.append(value)
        if on_row is not None:on_row(float(frequency),value)
    return SweepMeasurement(name=Path(name).stem,freq_hz=np.asarray(frequencies).copy(),
        limit_dB=np.asarray(values),available=True,unit='dBm' if quantity == 'rms_power' else 'dB/Hz',
        quantity=quantity,datetime=datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
        operator=operator,temperature=temperature,dwell_sec=dwell_sec,
        bandwidth_hz=sweep_bandwidth_hz(commands))
