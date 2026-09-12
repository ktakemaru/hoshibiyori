"""撮影対象カタログ(catalog.Target)を受け取る一般化された天体位置計算エンジン。

これまで天の川銀河中心専用だった方位角・高度計算を一般化し、
targets.json に登録された任意の対象(恒星として扱う、固定RA/Dec)に対応する。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from skyfield.api import Star, wgs84

from catalog import Target

JST = timezone(timedelta(hours=9))

# 恒星時は太陽時よりわずかに速く進む(1恒星日 = 23h56m4.09s)。
# 1太陽時あたりの恒星時の進み量:
SIDEREAL_RATE = 1.00273790935


def altaz_at_time(t, eph, lat_deg: float, lon_deg: float, elevation_m: float, target: Target) -> tuple[float, float]:
    """指定したSkyfieldのTime tにおける対象の(方位角, 高度)を度単位で返す。"""
    observer = eph["earth"] + wgs84.latlon(lat_deg, lon_deg, elevation_m=elevation_m)
    star = Star(ra_hours=target.ra_hours, dec_degrees=target.dec_deg)
    apparent = observer.at(t).observe(star).apparent()
    alt, az, _ = apparent.altaz()
    return az.degrees, alt.degrees


def altaz_at_datetime(ts, eph, lat_deg: float, lon_deg: float, elevation_m: float, target: Target, dt_local: datetime) -> tuple[float, float]:
    """指定したローカル日時(tzinfo付き)における対象の(方位角, 高度)を度単位で返す。"""
    t = ts.from_datetime(dt_local.astimezone(timezone.utc))
    return altaz_at_time(t, eph, lat_deg, lon_deg, elevation_m, target)


def is_circumpolar(lat_deg: float, dec_deg: float) -> bool:
    """観測地の緯度と対象の赤緯から、周極星(一年中沈まない)かどうかを判定する。

    北半球の観測地を想定: dec >= 90 - lat であれば常に地平線上にある。
    """
    if lat_deg >= 0:
        return dec_deg >= 90.0 - lat_deg
    return dec_deg <= -90.0 - lat_deg


def never_rises(lat_deg: float, dec_deg: float) -> bool:
    """観測地からは一年中地平線上に昇らない対象かどうかを判定する。"""
    if lat_deg >= 0:
        return dec_deg <= -(90.0 - lat_deg)
    return dec_deg >= 90.0 + lat_deg


def find_transit_time(ts, lon_deg: float, ra_hours: float, reference_local_midnight_t):
    """reference_local_midnight_t(その日のローカル0時に対応するTime)付近で、
    対象が南中する(地方恒星時 = RA となる)瞬間のTimeを返す。

    固定した赤経・赤緯の恒星が対象であるため、探索ではなく地方恒星時から
    直接解析的に計算する。
    """
    lst_at_midnight = (reference_local_midnight_t.gast + lon_deg / 15.0) % 24.0
    hour_angle = (lst_at_midnight - ra_hours) % 24.0
    if hour_angle > 12.0:
        hour_angle -= 24.0
    # 南中(時角=0)までの太陽時での経過時間
    offset_hours = -hour_angle / SIDEREAL_RATE
    return ts.tt_jd(reference_local_midnight_t.tt + offset_hours / 24.0)


def monthly_transit_report(
    ts, eph, lat_deg: float, lon_deg: float, elevation_m: float, target: Target,
    year: int, day_of_month: int = 15,
) -> list[dict]:
    """各月day_of_month日の南中時刻(現地時間)と、その時の高度を計算する。"""
    results = []
    for month in range(1, 13):
        local_midnight = datetime(year, month, day_of_month, 0, 0, 0, tzinfo=JST)
        t_midnight = ts.from_datetime(local_midnight.astimezone(timezone.utc))
        t_transit = find_transit_time(ts, lon_deg, target.ra_hours, t_midnight)
        _, alt_deg = altaz_at_time(t_transit, eph, lat_deg, lon_deg, elevation_m, target)
        transit_local = t_transit.utc_datetime().astimezone(JST)
        results.append({
            "month": month,
            "transit_local": transit_local,
            "max_altitude_deg": alt_deg,
        })
    return results


def monthly_fixed_hour_altitude(
    ts, eph, lat_deg: float, lon_deg: float, elevation_m: float, target: Target,
    year: int, hour: int = 22, day_of_month: int = 15,
) -> list[dict]:
    """各月day_of_month日hour時(現地時間)時点での対象の方位角・高度を計算する。

    「その時刻に空に見えるか・どれだけ高いか」という実用的な季節性の指標として使う
    (南中高度そのものは季節によらず一定のため、季節性の確認には不向き)。
    """
    results = []
    for month in range(1, 13):
        dt_local = datetime(year, month, day_of_month, hour, 0, 0, tzinfo=JST)
        az_deg, alt_deg = altaz_at_datetime(ts, eph, lat_deg, lon_deg, elevation_m, target, dt_local)
        results.append({
            "month": month,
            "azimuth_deg": az_deg,
            "altitude_deg": alt_deg,
        })
    return results
