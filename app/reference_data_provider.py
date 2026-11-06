"""Optional GUI reference measurements, matched by the project measurement filename.

Paths are relative to this module, independent of the project and working directory.
Reports, measurement procedures and file writers do not import this provider.
"""
import logging
from pathlib import Path

REFERENCE_DATA_DIR = Path(__file__).resolve().parent / 'reference_data'
CALIBRATION_DIR = REFERENCE_DATA_DIR / 'calibration'
TESTS_DIR = REFERENCE_DATA_DIR / 'tests'

_cache = {}
_log = logging.getLogger(__name__)


def reference_path(name, *, calibration=False):
    directory = CALIBRATION_DIR if calibration else TESTS_DIR
    return directory / Path(name).name


def load_reference(name, measurement_class, *, calibration=False):
    """Read a matching reference if present, caching until its file changes.

    Missing, empty or unreadable references are skipped. They never replace
    project measurements or change their availability/acceptance results.
    """
    path = reference_path(name, calibration=calibration)
    key = (path, measurement_class)
    try:
        stat = path.stat()
    except OSError:
        _cache.pop(key, None)
        return None
    version = (stat.st_mtime_ns, stat.st_size)
    if key not in _cache or _cache[key][0] != version:
        result = None
        try:
            candidate = measurement_class.from_file(path)
            if candidate.has_data():
                result = candidate
        except Exception as exc:
            _log.warning('Cannot read optional reference %s: %s', path, exc)
        _cache[key] = (version, result)
    return _cache[key][1]


def clear_cache():
    _cache.clear()
