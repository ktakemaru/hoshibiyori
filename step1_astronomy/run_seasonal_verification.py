"""石廊崎を例に、カタログの全対象について月別の南中時刻・最大高度、
および毎晩22:00時点での高度を計算し、季節性が理論通りに再現されるか検証する。
"""
from __future__ import annotations

from skyfield.api import load

from catalog import load_targets
from sky_engine import is_circumpolar, monthly_fixed_hour_altitude, monthly_transit_report

SITE_NAME = "石廊崎"
SITE_LAT = 34.602778
SITE_LON = 138.845278
SITE_ELEV = 60.0
YEAR = 2026
FIXED_HOUR = 22  # 毎晩22:00時点の高度を「見頃」の実用指標として使う

if __name__ == "__main__":
    ts = load.timescale()
    eph = load("de421.bsp")

    targets = load_targets()

    for target in targets:
        circumpolar = is_circumpolar(SITE_LAT, target.dec_deg)
        print(f"\n{'='*70}")
        print(f"■ {target.name} ({target.name_en})  Dec={target.dec_deg:+.2f}°"
              f"  {'[周極星]' if circumpolar else ''}")
        print(f"  カタログ記載の見頃季節: {target.best_season}")
        print(f"{'='*70}")

        transit_rows = monthly_transit_report(ts, eph, SITE_LAT, SITE_LON, SITE_ELEV, target, YEAR)
        fixed_rows = monthly_fixed_hour_altitude(ts, eph, SITE_LAT, SITE_LON, SITE_ELEV, target, YEAR, hour=FIXED_HOUR)

        print(f"{'月':>4} {'南中時刻(現地)':>18} {'南中高度':>9} | {FIXED_HOUR}:00時点の高度")
        for tr, fr in zip(transit_rows, fixed_rows):
            transit_str = tr["transit_local"].strftime("%m/%d %H:%M")
            fixed_alt = fr["altitude_deg"]
            visible_mark = "" if fixed_alt > 0 else "(地平線下)"
            print(f"{tr['month']:>3}月 {transit_str:>18} {tr['max_altitude_deg']:>8.1f}° | "
                  f"{fixed_alt:>6.1f}° {visible_mark}")
