"""指定地点・日時における月の高度と位相角をSkyfieldで計算する。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from skyfield.api import load, wgs84

JST = timezone(timedelta(hours=9))


@dataclass
class MoonPosition:
    alt_deg: float
    az_deg: float
    phase_angle_deg: float  # 0=満月, 180=新月


def compute_moon_position(ts, eph, lat_deg: float, lon_deg: float, elevation_m: float, dt_local: datetime) -> MoonPosition:
    t = ts.from_datetime(dt_local.astimezone(timezone.utc))
    observer = eph["earth"] + wgs84.latlon(lat_deg, lon_deg, elevation_m=elevation_m)

    astrometric_moon = observer.at(t).observe(eph["moon"]).apparent()
    alt, az, _ = astrometric_moon.altaz()

    astrometric_sun = observer.at(t).observe(eph["sun"]).apparent()
    elongation_deg = astrometric_moon.separation_from(astrometric_sun).degrees
    phase_angle_deg = 180.0 - elongation_deg

    return MoonPosition(alt_deg=alt.degrees, az_deg=az.degrees, phase_angle_deg=phase_angle_deg)
