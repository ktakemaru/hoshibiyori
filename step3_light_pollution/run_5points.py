"""これまで検証してきた5地点の光害値・ボートルスケール近似値を取得する。"""
from light_pollution import ATTRIBUTION, LightPollutionTileStore

POINTS = [
    ("富士山頂", 35.3606, 138.7274),
    ("須走口五合目", 35.364942, 138.777077),
    ("精進湖 他手合浜", 35.490824, 138.605076),
    ("八ヶ岳南麓天文台", 35.882707, 138.36435),
    ("石廊崎", 34.602778, 138.845278),
]

if __name__ == "__main__":
    store = LightPollutionTileStore(cache_dir="tile_cache", year=2025)
    print(ATTRIBUTION)
    print()
    print(f"{'地点':18s} {'緯度':>9s} {'経度':>10s} {'LPI(明るさ比)':>12s} {'mag/arcsec2':>11s} {'Bortle(近似)':>10s}")
    for name, lat, lon in POINTS:
        r = store.get(lat, lon)
        print(f"{name:18s} {lat:9.4f} {lon:10.4f} {r.brightness_ratio:12.3f} {r.mpsas:11.2f} {r.bortle_approx:10d}")
