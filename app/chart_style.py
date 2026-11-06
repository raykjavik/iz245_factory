"""Report/LED status colors and an independent palette for GUI curve identities."""
PASS_COLOR = '#218c36'
FAIL_COLOR = '#ff4d4f'
LIMIT_COLOR = '#000000'

# GUI curves identify measurements, independently of pass/fail status.
APP_CURVE_COLORS = (
    '#218c36', '#1565c0', '#e07000', '#7b1fa2', '#00838f', '#c62828',
    '#5d4037', '#c2185b', '#455a64', '#827717', '#512da8', '#00695c',
    '#d84315', '#283593', '#9e457b', '#347e9c', '#8c5724', '#608b32',
    '#9756ba', '#258680',
)


def result_color(passed):
    return PASS_COLOR if passed is not None and bool(passed) else FAIL_COLOR
