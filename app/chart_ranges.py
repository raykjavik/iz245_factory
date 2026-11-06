"""Curve-only bounds shared by the live charts and report charts."""
import numpy as np

Y_MARGIN = .03


def clipped_curve(x, y, bounds, *, log_x=False, max_points=None):
    """Clip a displayed curve, interpolating bracketed edges without extrapolation."""
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    indices = np.flatnonzero((x >= bounds[0]) & (x <= bounds[1]))
    if max_points is not None and indices.size > max_points:
        indices = indices[np.unique(np.geomspace(1, indices.size, max_points).astype(int)-1)]
    xs, ys = x[indices], y[indices]
    for edge in bounds:
        index = int(np.searchsorted(x, edge))
        if not 0 < index < x.size or x[index] == edge:
            continue
        pair_x, pair_y = x[index-1:index+1], y[index-1:index+1]
        if not np.isfinite(pair_y).all():
            continue
        coordinate = np.log10(pair_x) if log_x else pair_x
        point = np.log10(edge) if log_x else edge
        value = np.interp(point, coordinate, pair_y)
        position = int(np.searchsorted(xs, edge))
        xs, ys = np.insert(xs, position, edge), np.insert(ys, position, value)
    return xs, ys


def data_x_range(curves, *, log_x=False):
    bounds = []
    for x, y in curves:
        x, y = np.asarray(x), np.asarray(y)
        valid = np.isfinite(x) & np.isfinite(y)
        if log_x:
            valid &= x > 0
        if valid.any():
            bounds.extend((float(x[valid].min()), float(x[valid].max())))
    return (min(bounds), max(bounds)) if bounds else None


def clipped_x_range(data_range, requested=None):
    if data_range is None:
        return None
    if requested is None:
        return data_range
    low, high = max(data_range[0], requested[0]), min(data_range[1], requested[1])
    return (low, high) if low < high else data_range


def visible_y_range(curves, low, high, *, log_x=False, limits=()):
    """Fit ordered curve slices and interpolated edges; ignore non-finite data.

    Limit lines stay visible. Cursor/legend graphics never affect these bounds.
    """
    levels = []
    for x, y in curves:
        x, y = np.asarray(x), np.asarray(y)
        if not x.size:
            continue
        start = int(np.searchsorted(x, low, side='left'))
        stop = int(np.searchsorted(x, high, side='right'))
        visible = y[start:stop]
        finite = visible[np.isfinite(visible)]
        if finite.size:
            levels.extend((float(finite.min()), float(finite.max())))
        for edge in (low, high):
            index = int(np.searchsorted(x, edge))
            if not 0 < index < x.size:
                continue
            xs, ys = x[index-1:index+1], y[index-1:index+1]
            if not np.isfinite(xs).all() or not np.isfinite(ys).all():
                continue
            if log_x:
                if (xs <= 0).any() or edge <= 0:
                    continue
                xs, edge = np.log10(xs), np.log10(edge)
            levels.append(float(np.interp(edge, xs, ys)))
    if not levels:
        return None
    levels.extend(float(value) for value in limits if np.isfinite(value))
    low, high = min(levels), max(levels)
    # A constant curve still needs a readable, nonzero vertical span.
    if low == high:
        low, high = low - .5, high + .5
    return low, high
