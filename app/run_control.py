"""Cooperative pause checkpoints shared by the calibration worker/backend."""
from measurement_control import Aborted, check_abort


def pause_checkpoint(cancel, pause_event, pause_changed):
    check_abort(cancel)
    was_paused = pause_event is not None and pause_event.is_set()
    if was_paused:
        pause_changed(True)
        try:
            while pause_event.is_set():
                if cancel.wait(0.05):
                    raise Aborted('Aborted while paused')
        finally:
            pause_changed(False)
    check_abort(cancel)

    return was_paused
