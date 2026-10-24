"""地形地平線(step2_terrain/horizon_*.csv)と ALR の関係を調べる(段階LP2の追加診断。読み取り専用)。

仮説: 山に囲まれた地点では、ALR が遮蔽された灯りまで数えて明るく出ている。
既存の地平線プロファイルだけを読み、新しい地形計算・通信はしない。HDF5 の読み込みに h5py が必要(Python 3.13等)。

    py -3.13 step3_light_pollution/analyze_horizon_alr.py --json-out <path> [--year 2025]

地平線プロファイルが無い地点(主軸146件のうち curated_external の62件など)は対象外。
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import analyze_rank_shift as ars  # noqa: E402
import build_skyglow_bm as bsb  # noqa: E402
import skyglow_bm as sg  # noqa: E402

SECTOR_DEG = 10  # 「寄与が最大の方位」を求める扇形の幅
BLOCK_DEG = 3.0  # 「遮蔽されている方位」とみなす地平線仰角の目安(恣意的な値。診断のみ)
# stargazing_spots.json に紐付いていないが、地点を座標で特定できる既存プロファイル
UNLINKED = {"curated_ext:044": "step2_terrain/horizon_curated_ext044_50km.csv"}
FOCUS = ["白山", "奥只見ダム", "黒部峡谷", "上高地", "柳田星の観察館満天星", "見附島", "能登・ヤセの断崖"]


def load_horizon(path: Path) -> np.ndarray:
    """方位0..359°(1°刻み)の地平線仰角[度]。"""
    alt = np.full(360, np.nan)
    with path.open(encoding="utf-8") as f:
        for row in csv.reader(line for line in f if not line.startswith("#")):
            if row and row[0] != "azimuth_deg":
                alt[int(float(row[0])) % 360] = float(row[1])
    if np.isnan(alt).any():
        raise ValueError(f"{path}: 欠けた方位がある")
    return alt


def bearing_deg(lat1: float, lon1: float, lat2, lon2) -> np.ndarray:
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dl = np.radians(lon2) - np.radians(lon1)
    y = np.sin(dl) * np.cos(p2)
    x = np.cos(p1) * np.sin(p2) - np.sin(p1) * np.cos(p2) * np.cos(dl)
    return np.degrees(np.arctan2(y, x)) % 360


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
    slat, slon = sg.unproject(sx, sy, geom.lat0, geom.lon0)

    spots = json.loads(sg.SPOTS_PATH.read_text(encoding="utf-8"))["spots"]
    grid = sg.DerivedGrid.load(sg.DATA_DIR / f"skyglow_bm_{args.year}.npz")
    alr_grid = grid.at([s["lat"] for s in spots], [s["lon"] for s in spots])
    import legacy_ref  # 事前計算のlpiは外したので、光害タイルから計算する
    lpi = legacy_ref.legacy_lpi(spots)
    r_lpi, r_alr = sg.rank_pct(lpi), sg.rank_pct(alr_grid)

    rows = []
    for i, s in enumerate(spots):
        rel = s.get("horizon_profile") or UNLINKED.get(s["id"])
        linked = bool(s.get("horizon_profile"))
        base = {"name": s["name"], "id": s["id"], "pref": s.get("prefecture"), "elev_m": s.get("elevation_m"),
                "lpi": float(lpi[i]), "alr": float(alr_grid[i]), "rank_lpi": float(r_lpi[i]), "rank_alr": float(r_alr[i]),
                "diff_pt": float(r_alr[i] - r_lpi[i]), "has_profile": rel is not None, "profile_linked": linked}
        if rel is None:
            rows.append(base)
            continue
        h = load_horizon(ROOT / rel)
        px, py = sg.project(s["lat"], s["lon"], geom.lat0, geom.lon0)
        d = np.hypot(sx - float(px), sy - float(py))
        contrib = np.where(d <= sg.RADIUS_KM, vals * sg.weight(d), 0.0)
        total = float(contrib.sum())
        az = bearing_deg(s["lat"], s["lon"], slat, slon)
        azi = np.floor(az).astype(int) % 360
        h_src = h[azi]  # 各光源の方位の地平線仰角
        sec = np.floor(az / SECTOR_DEG).astype(int) % (360 // SECTOR_DEG)
        sec_sum = np.bincount(sec, weights=contrib, minlength=360 // SECTOR_DEG)
        k = int(np.argmax(sec_sum))
        lo, hi = k * SECTOR_DEG, (k + 1) * SECTOR_DEG
        sector_h = h[lo:hi]
        top_pix = int(np.argmax(contrib))
        # 最大の扇形の中で寄与が最大の距離帯
        in_k = sec == k
        d_k = float((d[in_k] * contrib[in_k]).sum() / contrib[in_k].sum()) if contrib[in_k].sum() > 0 else float("nan")
        base.update({
            "mean_h": float(h.mean()), "mean_h_pos": float(np.clip(h, 0, None).mean()), "max_h": float(h.max()),
            "top_sector": f"{lo}-{hi}°", "top_sector_share": float(sec_sum[k] / total),
            "top_sector_h_mean": float(sector_h.mean()), "top_sector_h_max": float(sector_h.max()),
            "top_sector_mean_dist_km": d_k,
            "top_pixel_az": float(az[top_pix]), "top_pixel_dist_km": float(d[top_pix]),
            "top_pixel_h": float(h_src[top_pix]), "top_pixel_share": float(contrib[top_pix] / total),
            "weighted_h": float((contrib * h_src).sum() / total),
            "blocked_share": float(contrib[h_src >= BLOCK_DEG].sum() / total),
            "near20_share": float(contrib[d < 20].sum() / total),
        })
        rows.append(base)

    prof = [r for r in rows if r["has_profile"]]
    linked_prof = [r for r in prof if r["profile_linked"]]

    def col(rs, k):
        return np.array([(r[k] if r[k] is not None else 0.0) for r in rs], float)

    def corr_table(rs):
        out = {}
        targets = {"diff_pt": col(rs, "diff_pt"), "rank_alr": col(rs, "rank_alr"), "rank_lpi": col(rs, "rank_lpi")}
        feats = ["mean_h", "mean_h_pos", "top_sector_h_mean", "top_pixel_h", "weighted_h", "blocked_share", "elev_m", "near20_share"]
        for t, tv in targets.items():
            out[t] = {f: ars.spearman(tv, col(rs, f)) for f in feats}
        out["mean_h_vs_elev"] = ars.spearman(col(rs, "mean_h"), col(rs, "elev_m"))
        return out

    def ols_r2(y, xs):
        X = np.column_stack([np.ones(len(y))] + list(xs))
        beta, *_ = np.linalg.lstsq(X, y, rcond=None)
        res = y - X @ beta
        return float(1 - (res @ res) / ((y - y.mean()) @ (y - y.mean())))

    y = sg.rank_pct(col(prof, "diff_pt"))  # 順位尺度で回帰(外れ値に強くする)
    rk = lambda k: sg.rank_pct(col(prof, k))  # noqa: E731
    summary = {
        "n_spots": len(rows), "n_with_profile": len(prof), "n_linked_profile": len(linked_prof),
        "n_without_profile": len(rows) - len(prof),
        "block_deg": BLOCK_DEG, "sector_deg": SECTOR_DEG,
        "corr_all_profile": corr_table(prof),
        "r2_diff": {
            "elev+near20": ols_r2(y, [rk("elev_m"), rk("near20_share")]),
            "elev+near20+mean_h": ols_r2(y, [rk("elev_m"), rk("near20_share"), rk("mean_h")]),
            "elev+near20+weighted_h": ols_r2(y, [rk("elev_m"), rk("near20_share"), rk("weighted_h")]),
            "mean_h": ols_r2(y, [rk("mean_h")]), "weighted_h": ols_r2(y, [rk("weighted_h")]),
            "blocked_share": ols_r2(y, [rk("blocked_share")]),
        },
        "mean_h_quartiles": [float(v) for v in np.percentile(col(prof, "mean_h"), [0, 25, 50, 75, 100])],
    }
    sel = [r for r in rows if r["name"] in FOCUS]
    # 平均地平線仰角の高い側/低い側4分位での順位差
    q = np.percentile(col(prof, "mean_h"), [25, 75])
    hi_g = [r["diff_pt"] for r in prof if r["mean_h"] >= q[1]]
    lo_g = [r["diff_pt"] for r in prof if r["mean_h"] <= q[0]]
    summary["diff_by_mean_h_quartile"] = {"top": [len(hi_g), float(np.mean(hi_g))], "bottom": [len(lo_g), float(np.mean(lo_g))]}
    args.json_out.write_text(json.dumps({"summary": summary, "focus": sel, "all": rows}, ensure_ascii=False, indent=1) + "\n",
                             encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
