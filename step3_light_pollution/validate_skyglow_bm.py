"""skyglow_bm の検証材料を出す(段階LP1)。採用判断はしない。numpyのみ。

    py -X utf8 step3_light_pollution/validate_skyglow_bm.py \
        [--other VJ=path.npz --other 2024=path.npz] [--json-out out.json]
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
import skyglow_bm as sg  # noqa: E402

DEFAULT_GRID = HERE / "data" / "skyglow_bm_2025.npz"

# 常識的な確認に使う地点(名前は stargazing_spots.json に無いので座標で持つ。出所は一般的な地名の緯度経度)
CITIES = {"東京駅": (35.6812, 139.7671), "横浜": (35.4437, 139.6380), "さいたま": (35.8617, 139.6455),
          "名古屋": (35.1815, 136.9066), "新潟": (37.9162, 139.0364), "宇都宮": (36.5551, 139.8828)}
DARK_REFERENCE = {"八ヶ岳(赤岳山麓・清里付近)": (35.9, 138.42), "山中湖": (35.41, 138.86),
                  "阿智村": (35.45, 137.69), "能登外浦(輪島付近)": (37.39, 136.90),
                  "富士山頂": (35.3606, 138.7274)}


def spearman(a, b) -> float:
    ra, rb = sg.rank_pct(a), sg.rank_pct(b)
    return float(np.corrcoef(ra, rb)[0, 1])


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(a))


def nearest_city(lat, lon):
    best = min(CITIES.items(), key=lambda kv: haversine_km(lat, lon, *kv[1]))
    return best[0], haversine_km(lat, lon, *best[1])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--grid", type=Path, default=DEFAULT_GRID)
    ap.add_argument("--other", action="append", default=[], metavar="LABEL=PATH")
    ap.add_argument("--json-out", type=Path)
    args = ap.parse_args()

    grid = sg.DerivedGrid.load(args.grid)
    spots = json.loads(sg.SPOTS_PATH.read_text(encoding="utf-8"))["spots"]
    import legacy_ref  # 事前計算のlpiは外したので、光害タイルから計算する
    for s, v in zip(spots, legacy_ref.legacy_lpi(spots)):
        s["lpi"] = float(v)
    ann = sg.annotate_spots(spots, grid)
    res = {"grid": str(args.grid.name), "n_spots": len(spots)}

    # 1. 既存LPIとの順位相関
    ok = [i for i, s in enumerate(ann) if s["skyglow_bm_index"] is not None and s.get("lpi") is not None]
    bm = np.array([ann[i]["skyglow_bm_index"] for i in ok])
    lpi = np.array([ann[i]["lpi"] for i in ok])
    res["n_compared"] = len(ok)
    res["spearman_lpi"] = spearman(bm, lpi)
    res["spearman_log"] = float(np.corrcoef(np.log10(np.maximum(bm, 1e-4)), np.log10(np.maximum(lpi, 1e-4)))[0, 1])
    pb, pl = sg.rank_pct(bm), sg.rank_pct(lpi)
    diff = pb - pl
    order = np.argsort(-np.abs(diff))[:15]
    top = []
    for j in order:
        s = ann[ok[j]]
        city, dkm = nearest_city(s["lat"], s["lon"])
        top.append({"name": s["name"], "pref": s.get("prefecture"), "lat": s["lat"], "lon": s["lon"],
                    "elev_m": s.get("elevation_m"), "lpi": s["lpi"], "bm_alr": s["skyglow_bm_index"],
                    "rank_lpi": round(float(pl[j]), 1), "rank_bm": round(float(pb[j]), 1),
                    "diff_pt": round(float(diff[j]), 1), "nearest_city": city, "city_km": round(dkm)})
    res["top_disagreements"] = top

    # 2. 常識的な確認
    pts = {**CITIES, **DARK_REFERENCE}
    vals = grid.at([v[0] for v in pts.values()], [v[1] for v in pts.values()])
    res["landmarks"] = {k: (None if not np.isfinite(v) else round(float(v), 3)) for k, v in zip(pts, vals)}
    arr = grid.alr
    iy, ix = np.unravel_index(np.nanargmax(arr), arr.shape)
    res["brightest_cell"] = {"lat": round(grid.lat_top - iy * grid.step, 3), "lon": round(grid.lon_left + ix * grid.step, 3),
                             "alr": round(float(arr[iy, ix]), 2)}
    res["spot_alr_quantiles"] = {q: round(float(np.quantile(bm, q)), 3) for q in (0.0, 0.1, 0.25, 0.5, 0.75, 0.9, 1.0)}
    res["spots_darkest5"] = [(ann[ok[j]]["name"], ann[ok[j]]["skyglow_bm_index"]) for j in np.argsort(bm)[:5]]
    res["spots_brightest5"] = [(ann[ok[j]]["name"], ann[ok[j]]["skyglow_bm_index"]) for j in np.argsort(-bm)[:5]]

    # 3. 近接2地点(3km以内)の比
    pairs = []
    for a in range(len(ok)):
        for b in range(a + 1, len(ok)):
            sa, sb = ann[ok[a]], ann[ok[b]]
            d = haversine_km(sa["lat"], sa["lon"], sb["lat"], sb["lon"])
            if d <= 3.0:
                ra_, rb_ = sa["skyglow_bm_index"], sb["skyglow_bm_index"]
                pairs.append({"a": sa["name"], "b": sb["name"], "km": round(d, 2), "alr_a": ra_, "alr_b": rb_,
                              "ratio": round(max(ra_, rb_) / max(min(ra_, rb_), 1e-6), 3)})
    pairs.sort(key=lambda p: -p["ratio"])
    res["near_pairs"] = {"n": len(pairs), "max_ratio": pairs[0]["ratio"] if pairs else None, "worst5": pairs[:5]}

    # 4. 別入力(別年・別衛星)との比較
    res["others"] = {}
    for item in args.other:
        label, path = item.split("=", 1)
        other = sg.DerivedGrid.load(Path(path))
        o_ann = sg.annotate_spots(spots, other)
        ob = np.array([o_ann[i]["skyglow_bm_index"] for i in ok])
        ratio = ob / np.maximum(bm, 1e-6)
        res["others"][label] = {
            "spearman_vs_main": spearman(bm, ob),
            "median_ratio": round(float(np.median(ratio)), 3),
            "ratio_p5_p95": [round(float(np.quantile(ratio, 0.05)), 3), round(float(np.quantile(ratio, 0.95)), 3)],
            "max_rank_shift_pt": round(float(np.max(np.abs(sg.rank_pct(ob) - pb))), 1),
            "tokyo_station_alr": round(float(other.at([35.6812], [139.7671])[0]), 2),
        }
    txt = json.dumps(res, ensure_ascii=False, indent=2)
    if args.json_out:
        args.json_out.write_text(txt + "\n", encoding="utf-8")
    sys.stdout.buffer.write((txt + "\n").encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
