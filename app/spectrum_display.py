"""Display-only maximum envelope; measurement and CSV arrays remain at full resolution."""
import numpy as np

DISPLAY_BUCKETS = 2048  # one maximum value per frequency bucket


def max_envelope(x, y, buckets=DISPLAY_BUCKETS):
    """Maximum of contiguous frequency buckets, including the final partial bucket.

    FFT frequencies have uniform spacing. Each bucket is drawn at the midpoint
    of its frequency interval. No averaging/subsampling can hide a narrow peak.
    """
    count = min(len(x), int(buckets))
    if count == 0:
        return np.array([]), np.array([])
    edges = np.linspace(0, len(x), count+1, dtype=np.intp)
    centers = (x[edges[:-1]]+x[edges[1:]-1])/2
    return centers, np.fmax.reduceat(y, edges[:-1])
