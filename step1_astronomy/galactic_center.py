"""
星の日和(hoshibiyori) ステップ1: 天文計算エンジンの検証。

指定した緯度・経度・日時における撮影対象(既定: 天の川銀河中心)の
方位角・高度と、その夜の月齢・月の出没時刻を計算する。

対象天体はハードコードではなく targets.json のカタログから選択する
(catalog.py / sky_engine.py の一般化されたエンジンを使用)。

使用ライブラリ: Skyfield + JPL暦(de421.bsp)
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from skyfield import almanac
from skyfield.api import load, wgs84

from catalog import get_target
from sky_engine import altaz_at_datetime

SYNODIC_MONTH_DAYS = 29.530589

JST = timezone(timedelta(hours=9))


@dataclass
class Location:
    name: str
    lat_deg: float
    lon_deg: float
    elevation_m: float


def moon_age_days(ts, eph, dt_local: datetime) -> float:
    """指定日時における月齢(日)を返す。"""
    t = ts.from_datetime(dt_local.astimezone(timezone.utc))
    phase_angle = almanac.moon_phase(eph, t).degrees
    return phase_angle / 360.0 * SYNODIC_MONTH_DAYS


def moon_rise_set(ts, eph, location: Location, date_local: datetime):
    """指定日(現地時間の0時〜24時)における月の出・月の入り時刻(JST)を返す。

    出没が無い日はそれぞれ None を返す。
    """
    topos = wgs84.latlon(location.lat_deg, location.lon_deg, elevation_m=location.elevation_m)

    start_local = datetime(date_local.year, date_local.month, date_local.day, 0, 0, tzinfo=JST)
    end_local = start_local + timedelta(days=1)
    t0 = ts.from_datetime(start_local.astimezone(timezone.utc))
    t1 = ts.from_datetime(end_local.astimezone(timezone.utc))

    f = almanac.risings_and_settings(eph, eph["moon"], topos)
    times, events = almanac.find_discrete(t0, t1, f)

    rise = None
    set_ = None
    for t, is_rise in zip(times, events):
        local_dt = t.utc_datetime().astimezone(JST)
        if is_rise and rise is None:
            rise = local_dt
        elif not is_rise and set_ is None:
            set_ = local_dt
    return rise, set_


def main() -> None:
    parser = argparse.ArgumentParser(
        description="撮影対象(既定:天の川銀河中心)の方位角・高度、月齢・月の出没時刻を計算する"
    )
    parser.add_argument("--lat", type=float, required=True, help="緯度(度、北緯正)")
    parser.add_argument("--lon", type=float, required=True, help="経度(度、東経正)")
    parser.add_argument("--elevation", type=float, default=0.0, help="標高(m)")
    parser.add_argument("--name", type=str, default="観測地点", help="地点名")
    parser.add_argument(
        "--target", type=str, default="galactic_center",
        help="targets.json内の対象ID(例: galactic_center, orion, pleiades, summer_triangle, big_dipper, cassiopeia)",
    )
    parser.add_argument(
        "--datetime",
        type=str,
        required=True,
        help="観測日時(JST、ISO形式) 例: 2026-06-13T23:00:00",
    )
    args = parser.parse_args()

    location = Location(args.name, args.lat, args.lon, args.elevation)
    dt_local = datetime.fromisoformat(args.datetime).replace(tzinfo=JST)
    target = get_target(args.target)

    ts = load.timescale()
    eph = load("de421.bsp")

    az, alt = altaz_at_datetime(ts, eph, location.lat_deg, location.lon_deg, location.elevation_m, target, dt_local)
    age = moon_age_days(ts, eph, dt_local)
    rise, set_ = moon_rise_set(ts, eph, location, dt_local)

    print(f"=== {location.name} "
          f"(緯度{location.lat_deg:.4f}, 経度{location.lon_deg:.4f}, 標高{location.elevation_m:.0f}m) ===")
    print(f"日時: {dt_local.strftime('%Y-%m-%d %H:%M')} JST\n")

    print(f"--- {target.name}({target.name_en}) ---")
    print(f"方位角: {az:.1f}° (北から時計回り)")
    print(f"高度  : {alt:.1f}°")
    if alt < 0:
        print("※ 地平線下のため見えません")
    print()

    print("--- 月 ---")
    print(f"月齢: {age:.1f}")
    print(f"月の出: {rise.strftime('%Y-%m-%d %H:%M') if rise else 'なし(この日は出ない)'}")
    print(f"月の入: {set_.strftime('%Y-%m-%d %H:%M') if set_ else 'なし(この日は入らない)'}")


if __name__ == "__main__":
    main()
