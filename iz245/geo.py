import numpy as np
from dataclasses import dataclass

# ---------- WGS84 constants ----------
_A = 6378137.0
_F = 1 / 298.257223563
_E2 = _F * (2 - _F)


def _geodetic_to_ecef(lon_deg, lat_deg, h_m):
    lon = np.radians(lon_deg)
    lat = np.radians(lat_deg)
    sφ, cφ = np.sin(lat), np.cos(lat)
    sλ, cλ = np.sin(lon), np.cos(lon)
    N = _A / np.sqrt(1.0 - _E2 * sφ**2)
    x = (N + h_m) * cφ * cλ
    y = (N + h_m) * cφ * sλ
    z = (N * (1.0 - _E2) + h_m) * sφ
    return np.stack([x, y, z], axis=-1)


def _ecef_to_geodetic_closed_form(x, y, z):
    """
    Fast Bowring-style closed form. Returns (lon_deg, lat_deg, h_m).
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    z = np.asarray(z, dtype=float)
    p = np.hypot(x, y)

    # Semi-minor axis, second eccentricity^2
    b = _A * (1 - _F)
    ep2 = (_A**2 - b**2) / b**2

    beta = np.arctan2(b * z, _A * p)
    sb, cb = np.sin(beta), np.cos(beta)

    lat = np.arctan2(z + ep2 * b * sb**3, p - _E2 * _A * cb**3)
    lon = np.arctan2(y, x)

    sφ, cφ = np.sin(lat), np.cos(lat)
    N = _A / np.sqrt(1.0 - _E2 * sφ**2)
    h = p / np.maximum(cφ, np.finfo(float).tiny) - N

    lon_deg = (np.degrees(lon) + 180.0) % 360.0 - 180.0
    lat_deg = np.degrees(lat)
    return lon_deg, lat_deg, h


@dataclass(frozen=True)
class LocalTangentPlane:
    """
    Local tangent ENU frame at WGS84 reference (lon0, lat0, h0).
    Methods:
      - wgs84_to_ltp(lon, lat, h) -> ENU ndarray
      - ltp_to_wgs84(enu) -> (lon, lat, h) with optional bias compensation
    """

    lon0_deg: float
    lat0_deg: float
    h0_m: float
    compensate: bool = True  # apply reference-point drift compensation?

    def __post_init__(self):
        # Origin ECEF
        r0 = _geodetic_to_ecef(self.lon0_deg, self.lat0_deg, self.h0_m).reshape(3)
        object.__setattr__(self, "_r0_ecef", r0)

        # Rotation ECEF -> ENU
        lat0 = np.radians(self.lat0_deg)
        lon0 = np.radians(self.lon0_deg)
        sφ, cφ = np.sin(lat0), np.cos(lat0)
        sλ, cλ = np.sin(lon0), np.cos(lon0)

        R = np.array(
            [
                [-sλ, cλ, 0.0],
                [-sφ * cλ, -sφ * sλ, cφ],
                [cφ * cλ, cφ * sλ, sφ],
            ],
            dtype=float,
        )
        object.__setattr__(self, "_R_ecef_to_enu", R)
        object.__setattr__(self, "_R_enu_to_ecef", R.T)

        # --- measure closed-form inverse drift at the reference point ---
        lon_raw, lat_raw, h_raw = self._ltp_to_wgs84_raw(np.array([0.0, 0.0, 0.0]))
        bias = np.array(
            [lon_raw - self.lon0_deg, lat_raw - self.lat0_deg, h_raw - self.h0_m],
            dtype=float,
        )
        object.__setattr__(self, "_bias_geodetic", bias)

    # ---------- core transforms ----------
    def wgs84_to_ltp(self, lon_deg, lat_deg, h_m):
        xyz = _geodetic_to_ecef(lon_deg, lat_deg, h_m)
        xyz = np.atleast_2d(xyz)
        enu = (self._R_ecef_to_enu @ (xyz - self._r0_ecef).T).T
        return enu[0] if enu.shape[0] == 1 else enu

    def _ltp_to_wgs84_raw(self, enu):
        """ENU -> geodetic using the closed-form inverse, no compensation."""
        enu = np.atleast_2d(enu)
        xyz = (self._R_enu_to_ecef @ enu.T).T + self._r0_ecef
        lon, lat, h = _ecef_to_geodetic_closed_form(xyz[:, 0], xyz[:, 1], xyz[:, 2])
        out = np.stack([lon, lat, h], axis=-1)
        return out[0] if out.shape[0] == 1 else out

    def ltp_to_wgs84(self, enu):
        """
        ENU -> WGS84 geodetic, optionally subtracting the reference-point bias.
        Accepts shape (3,) or (N,3). Returns same shape with columns (lon, lat, h).
        """
        raw = self._ltp_to_wgs84_raw(enu)
        if not self.compensate:
            return raw
        bias = self._bias_geodetic
        arr = np.atleast_2d(raw) - bias  # subtract bias
        # Normalize lon back to [-180,180)
        arr[:, 0] = (arr[:, 0] + 180.0) % 360.0 - 180.0
        return arr[0] if raw.ndim == 1 else arr


    def polygon_to_xyz_m(self,arr_wgs84: np.array):
        return np.apply_along_axis(
            lambda x:self.wgs84_to_ltp(lon_deg=x[0],lat_deg=x[1],h_m=350),
            axis=1,arr=arr_wgs84
        )