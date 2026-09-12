"""石廊崎を例に、新月時・満月時で実効的な空の明るさがどう変わるかを検証する。"""
from __future__ import annotations

from datetime import datetime

from skyfield.api import load

from moon_brightness import combine_sky_brightness
from moon_position import JST, compute_moon_position

# 石廊崎(既存ステップ3の結果: LPI=0.285 -> mag/arcsec^2=21.73)
SITE_NAME = "石廊崎"
SITE_LAT = 34.602778
SITE_LON = 138.845278
SITE_ELEV = 60.0
BACKGROUND_MPSAS = 21.73  # step3で計算済みの光害由来の空の明るさ(月を含まない)

TEST_CASES = [
    ("新月(2026-06-15)夜", datetime(2026, 6, 15, 23, 0, 0)),
    ("満月(2026-06-30)夜", datetime(2026, 6, 30, 23, 0, 0)),
]

if __name__ == "__main__":
    ts = load.timescale()
    eph = load("de421.bsp")

    print(f"=== {SITE_NAME} (緯度{SITE_LAT}, 経度{SITE_LON}) ===")
    print(f"光害由来の背景輝度(step3): {BACKGROUND_MPSAS} mag/arcsec^2\n")

    for label, dt_naive in TEST_CASES:
        dt_local = dt_naive.replace(tzinfo=JST)
        moon = compute_moon_position(ts, eph, SITE_LAT, SITE_LON, SITE_ELEV, dt_local)
        result = combine_sky_brightness(BACKGROUND_MPSAS, moon.alt_deg, moon.phase_angle_deg)

        print(f"--- {label} {dt_local.strftime('%Y-%m-%d %H:%M')} JST ---")
        print(f"  月の高度: {moon.alt_deg:.1f}°  月の位相角: {moon.phase_angle_deg:.1f}° (0=満月,180=新月)")
        print(f"  月明かり由来の輝度増加: {result['moon_nl']:.4f} nL")
        print(f"  背景輝度: {result['background_nl']:.4f} nL")
        print(f"  実効的な空の明るさ: {result['effective_mpsas']:.3f} mag/arcsec^2"
              f"  (背景のみ: {BACKGROUND_MPSAS} mag/arcsec^2, 悪化量: {result['delta_mag']:.3f} 等級)")
        print()
