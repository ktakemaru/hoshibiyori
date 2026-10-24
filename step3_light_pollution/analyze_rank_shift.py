"""LPI(Lorenz氏のAtlas由来)とALR(Black Marble由来)の順位差を、標高・距離・都市別の寄与で調べる(段階LP2の追加調査)。

HDF5の読み込みに h5py が必要(Python 3.13等。UPDATE.md 参照)。通信しない。
各地点のALRを、(1)距離帯(0-20, 20-50, 50-100, 100-200, 200-300 km)ごと、(2)主要都市の中心から25km以内の光源ごと
に分解し、「順位差(ALR順位 − LPI順位。負=新指数で暗い)」との関係を見る。

    py -3.13 step3_light_pollution/analyze_rank_shift.py --json-out <path> [--year 2025]

都市の緯度経度は一般的な市街地中心のおおよその値(出所は公開されている一般的な地名の座標。厳密な値ではない)。
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_skyglow_bm as bsb  # noqa: E402
import skyglow_bm as sg  # noqa: E402

BANDS = [(0, 20), (20, 50), (50, 100), (100, 200), (200, 300.0001)]
CITY_RADIUS_KM = 25.0
CITIES = {  # おおよその市街地中心
    "東京": (35.681, 139.767), "横浜": (35.466, 139.623), "さいたま": (35.861, 139.646), "千葉": (35.607, 140.106),
    "宇都宮": (36.555, 139.883), "前橋": (36.391, 139.061), "水戸": (36.342, 140.447), "甲府": (35.664, 138.568),
    "長野": (36.649, 138.181), "松本": (36.238, 137.972), "新潟": (37.916, 139.036), "富山": (36.696, 137.211),
    "金沢": (36.561, 136.657), "福井": (36.065, 136.222), "岐阜": (35.423, 136.761), "名古屋": (35.181, 136.906),
    "静岡": (34.977, 138.383), "浜松": (34.711, 137.726), "福島": (37.760, 140.474), "仙台": (38.268, 140.870),
}
# 論文Table 2(p.139)の「Distance from Las Vegas (km)」と「ALR/ZLR」。3km未満は3km、300kmを超える分は300kmの値で近似する。
ALR_ZLR_D = [3, 5, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120, 130, 140, 150, 160, 170, 180, 300]
ALR_ZLR_RATIO = [1.87, 2.15, 2.66, 2.96, 3.07, 3.08, 3.07, 3.02, 3.15, 3.07, 2.99, 2.91, 2.82, 2.75, 2.67, 2.59, 2.51, 2.41, 2.33, 2.23, 1.66]
FOCUS = ["白山", "奥只見ダム", "黒部峡谷", "上高地", "柳田星の観察館満天星", "見附島", "能登・ヤセの断崖"]


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(a))


def spearman(a, b) -> float:
    return float(np.corrcoef(sg.rank_pct(a), sg.rank_pct(b))[0, 1])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=2025)
    ap.add_argument("--json-out", type=Path, required=True)
    args = ap.parse_args()

    ext_in = sg.input_extent()
    arr, lat_top, lon_left, _ = bsb.mosaic(HERE / "blackmarble_cache" / "VNP46A4" / str(args.year), ext_in)
    geom = sg.plane_geometry_for_extent(ext_in)
    src = sg.to_plane(arr, lat_top, lon_left, bsb.CELL_DEG, bsb.CELL_DEG, geom)
    iy, ix = np.nonzero(src)
    vals = src[iy, ix]
    sx = geom.x_min + ix * geom.pixel_km
    sy = geom.y_max - iy * geom.pixel_km
    print(f"光源画素 {len(vals)}個", flush=True)

    spots = json.loads(sg.SPOTS_PATH.read_text(encoding="utf-8"))["spots"]
    grid = sg.DerivedGrid.load(sg.DATA_DIR / f"skyglow_bm_{args.year}.npz")
    alr_grid = grid.at([s["lat"] for s in spots], [s["lon"] for s in spots])
    lpi = np.array([s["lpi"] for s in spots], float)
    r_lpi, r_alr = sg.rank_pct(lpi), sg.rank_pct(alr_grid)

    city_xy = {k: sg.project(v[0], v[1], geom.lat0, geom.lon0) for k, v in CITIES.items()}
    rows = []
    for i, s in enumerate(spots):
        px, py = sg.project(s["lat"], s["lon"], geom.lat0, geom.lon0)
        d = np.hypot(sx - float(px), sy - float(py))
        within = d <= sg.RADIUS_KM
        contrib = np.where(within, vals * sg.weight(d), 0.0)
        total = float(contrib.sum())
        # 診断: 論文Table 2(Las VegasのGarstangモデル実験)の距離別 ALR/ZLR 比で割り、天頂(ZLR)に換算した近似
        zlr_equiv = float((contrib / np.interp(d, ALR_ZLR_D, ALR_ZLR_RATIO)).sum() / sg.ALR_CALIBRATION_C)
        bands = {f"{lo}-{int(hi)}km": float(contrib[(d >= lo) & (d < hi)].sum() / total) if total > 0 else 0.0 for lo, hi in BANDS}
        cities = {}
        for name, (cx, cy) in city_xy.items():
            near_city = np.hypot(sx - float(cx), sy - float(cy)) <= CITY_RADIUS_KM
            cities[name] = float(contrib[near_city].sum() / total) if total > 0 else 0.0
        top = sorted(cities.items(), key=lambda kv: -kv[1])[:3]
        dists = {n: haversine_km(s["lat"], s["lon"], *c) for n, c in CITIES.items()}
        near = min(dists.items(), key=lambda kv: kv[1])
        rows.append({
            "name": s["name"], "pref": s.get("prefecture"), "elev_m": s.get("elevation_m"), "lat": s["lat"], "lon": s["lon"],
            "lpi": float(lpi[i]), "alr": float(alr_grid[i]), "alr_recomputed": total / sg.ALR_CALIBRATION_C,
            "zlr_equiv": zlr_equiv,
            "rank_lpi": float(r_lpi[i]), "rank_alr": float(r_alr[i]), "diff_pt": float(r_alr[i] - r_lpi[i]),
            "bands": bands, "top_cities": [(n, round(v, 3)) for n, v in top], "city_km": {n: round(v) for n, v in dists.items()},
            "nearest_city": near[0], "nearest_city_km": round(near[1]),
            "tokyo_km": round(dists["東京"]),
        })
    diff = np.array([r["diff_pt"] for r in rows])
    elev = np.array([r["elev_m"] or 0.0 for r in rows], float)
    far = np.array([r["bands"]["100-200km"] + r["bands"]["200-300km"] for r in rows])
    near20 = np.array([r["bands"]["0-20km"] for r in rows])
    tokyo = np.array([r["tokyo_km"] for r in rows], float)
    nearest = np.array([r["nearest_city_km"] for r in rows], float)
    summary = {
        "n_spots": len(rows),
        "max_abs_alr_recompute_vs_grid_pct": float(np.max(np.abs((np.array([r["alr_recomputed"] for r in rows]) - alr_grid) / alr_grid)) * 100),
        "spearman_diff_vs": {
            "elevation": spearman(diff, elev), "far_share_100km_plus": spearman(diff, far), "near_share_0_20km": spearman(diff, near20),
            "distance_to_tokyo": spearman(diff, tokyo), "distance_to_nearest_city": spearman(diff, nearest),
        },
        "spearman_abs_diff_vs": {
            "elevation": spearman(np.abs(diff), elev), "far_share_100km_plus": spearman(np.abs(diff), far),
            "near_share_0_20km": spearman(np.abs(diff), near20), "distance_to_tokyo": spearman(np.abs(diff), tokyo),
            "distance_to_nearest_city": spearman(np.abs(diff), nearest),
        },
        "n_abs_diff_ge_15": int((np.abs(diff) >= 15).sum()),
        "spearman_lpi_vs_alr": spearman(lpi, np.array([r["alr"] for r in rows])),
        "spearman_lpi_vs_zlr_equiv": spearman(lpi, np.array([r["zlr_equiv"] for r in rows])),
        "n_abs_diff_ge_15_zlr_equiv": int((np.abs(sg.rank_pct([r["zlr_equiv"] for r in rows]) - r_lpi) >= 15).sum()),
        "max_abs_rank_diff_alr": float(np.max(np.abs(diff))),
        "max_abs_rank_diff_zlr_equiv": float(np.max(np.abs(sg.rank_pct([r["zlr_equiv"] for r in rows]) - r_lpi))),
        "median_far_share": float(np.median(far)), "median_near20_share": float(np.median(near20)),
    }
    focus = []
    for key in FOCUS:
        m = [r for r in rows if r["name"].startswith(key)]
        focus += m
    out = {"summary": summary, "focus": focus, "all": rows}
    args.json_out.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
