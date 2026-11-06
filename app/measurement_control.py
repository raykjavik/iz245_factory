"""Qt-free cancellation shared by measurements and transfers."""
class Aborted(RuntimeError):
    pass


def check_abort(cancel):
    if cancel is not None and cancel.is_set():
        raise Aborted('Aborted by operator')


