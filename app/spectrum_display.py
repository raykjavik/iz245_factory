"""Display-only min/max envelope; measurements and files stay full resolution."""
import numpy as np

DISPLAY_BUCKETS = 2048  # two vertices per frequency bucket


def min_max_envelope(x, y, buckets=DISPLAY_BUCKETS, *, log_x=False):
    """One polyline: each bucket contributes (center, min), (center, max).

    Buckets cover equal display-axis intervals, including logarithmic axes.
    Small curves retain their original points. Never modify the source arrays.
    """
    x, y = np.asarray(x), np.asarray(y)
    count = max(1, int(buckets))
    if len(x) <= count:
        return x.copy(), y.copy()
    coordinate = np.log10(x) if log_x else x
    edges = np.searchsorted(coordinate, np.linspace(coordinate[0], coordinate[-1], count+1))
    starts = np.unique(edges[:-1])
    stops = np.append(starts[1:], len(x))
    centers = (coordinate[starts]+coordinate[stops-1])/2
    if log_x:
        centers = 10**centers
    values = np.empty(2*len(starts))
    values[::2] = np.fmin.reduceat(y, starts)
    values[1::2] = np.fmax.reduceat(y, starts)
    return np.repeat(centers, 2), values
