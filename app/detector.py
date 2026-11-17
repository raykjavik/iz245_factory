"""Read the detector after the test has configured SWEEP:DWELL."""
import time


def read_detector(device, dwell_sec, *, wait=time.sleep, check_cancel=lambda:None):
    """Clear and read; never reconfigure dwell here.

    For dwell <= 1 second the receiver's read blocks until the result is ready.
    Longer dwells need an explicit wait; the controller supplies an abortable one.
    """
    check_cancel()
    device._main_scpi_command('DETector:CLEar')
    if dwell_sec > 1.0:
        wait(dwell_sec)
    check_cancel()
    val_str = device._main_scpi_query('sense:data?').split(',')
    ovf = int(val_str[-1])
    if ovf>0:
        raise RuntimeError("overrange")
    return [float(value) for value in val_str]
