"""Receiver detector acquisition shared by noise sweeps and Test7."""
import time

def read_detector(device, dwell_sec, *, wait=time.sleep, check_cancel=lambda:None):
    """Set the actual receiver dwell and wait once, after clearing the detector.

    Do not use the current driver's measure_point_rms here: it skips waiting
    for dwell <= 1 second. The application supplies an abortable wait callback.
    """
    device._main_scpi_commands([f'SWEEP:DWELL {dwell_sec:g}', 'DETector:CLEar'])
    wait(dwell_sec)
    check_cancel()
    return [float(value) for value in device._main_scpi_query('sense:data?').split(',')]

