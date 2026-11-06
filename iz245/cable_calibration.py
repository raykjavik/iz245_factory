"""Read frequency/dB cable characteristics without GUI dependencies."""
from pathlib import Path
import numpy as np


def read_cable_calibration(path: Path) -> tuple[np.ndarray, np.ndarray]:
    raw = Path(path).read_bytes()
    try:
        text = raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        text = raw.decode('cp1252')
    rows = []
    for number, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = [part.strip() for part in line.split(';')]
        if not rows and parts[0].lower().startswith(('freq', 'frequency')):
            continue
        try:
            frequency, value = float(parts[0]), float(parts[1])
        except (ValueError, IndexError) as exc:
            raise ValueError(f'{path}: invalid frequency/dB pair on line {number}.') from exc
        rows.append((frequency, value))
    if len(rows) < 2:
        raise ValueError('Cable calibration requires at least two frequency/dB pairs.')
    data = np.asarray(rows, dtype=float)
    if not np.all(np.isfinite(data)) or np.any(data[:, 0] <= 0):
        raise ValueError('Cable calibration must contain finite values and positive frequencies.')
    data = data[np.argsort(data[:, 0])]
    frequencies, values = data[:, 0].copy(), data[:, 1].copy()
    if np.any(np.diff(frequencies) <= 0):
        raise ValueError('Cable calibration contains duplicate frequencies.')
    frequencies.setflags(write=False)
    values.setflags(write=False)
    return frequencies, values
