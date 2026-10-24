"""同じ日付・同じ条件で legacy(LPI)と bm(ALR)の探索を並べて比較する(段階LP2)。

天文計算と雲量取得(第1・2段階)は1回だけ行い、第3段階(方角フィルタ+光害)と見込み(ECMWF圏内)を
2つの光害入力で実行する。天候と日付が完全に揃う。雲量はOpen-Meteoへ通信する(格子セルキャッシュを使う)。
結果は標準出力(UTF-8)と、指定すれば JSON にも出す。

    py -X utf8 step3_light_pollution/compare_lp_sources.py --json-out <path>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
import explore_hoshibiyori as ex  # noqa: E402  (step1〜5のsys.pathもここで通る)
from grid_cache import GridCloudCache  # noqa: E402
from hb_paths import DATA_ROOT, ephemeris_load as load  # noqa: E402

TOP = 10


def key(c) -> tuple:
    return (str(c.night_date), c.site_name)


def brief(c, rank: int | None = None) -> dict:
    return {"rank": rank, "night": str(c.night_date), "site": c.site_name, "muni": c.municipality,
            "score": round(c.score, 1), "alr": None if c.alr is None else round(c.alr, 2),
            "lpi": round(c.lpi, 2) if c.effective_mpsas is not None else None,
            "obstruction": round(getattr(c, "mean_obstruction", float("nan")), 0)
            if hasattr(c, "mean_obstruction") else None}


def top_primary(items, n=TOP):
    p = sorted((c for c in items if ex.is_primary_origin(c.origin)), key=lambda c: c.score, reverse=True)
    return p[:n], p


def compare(label: str, legacy_items, bm_items) -> dict:
    lt, lall = top_primary(legacy_items)
    bt, ball = top_primary(bm_items)
    lkeys, bkeys = {key(c) for c in lall}, {key(c) for c in ball}
    lrank = {key(c): i for i, c in enumerate(lall, 1)}
    brank = {key(c): i for i, c in enumerate(ball, 1)}
    top_l, top_b = {key(c) for c in lt}, {key(c) for c in bt}
    return {
        "label": label,
        "n_legacy": len(lall), "n_bm": len(ball), "n_both": len(lkeys & bkeys),
        "only_legacy": sorted(f"{k[0]} {k[1]}" for k in lkeys - bkeys),
        "only_bm": sorted(f"{k[0]} {k[1]}" for k in bkeys - lkeys),
        "top10_legacy": [{**brief(c, i), "rank_in_bm": brank.get(key(c))} for i, c in enumerate(lt, 1)],
        "top10_bm": [{**brief(c, i), "rank_in_legacy": lrank.get(key(c))} for i, c in enumerate(bt, 1)],
        "top10_overlap": len(top_l & top_b),
        "top10_only_legacy": sorted(f"{k[0]} {k[1]}" for k in top_l - top_b),
        "top10_only_bm": sorted(f"{k[0]} {k[1]}" for k in top_b - top_l),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json-out", type=Path)
    ap.add_argument("--include-reference", action="store_true",
                    help="参考候補(OSM展望データ751件)も対象にする。既定は generate_report.py と同じ主軸のみ")
    ap.add_argument("--sites-limit", type=int, help="主軸の先頭N件だけにする(メモリ・時間の測定用)")
    ap.add_argument("--nights-limit", type=int, help="MSM圏内・ECMWF圏内の夜をそれぞれ先頭N夜だけにする(同上)")
    args = ap.parse_args()

    cache = GridCloudCache()
    ts = load.timescale()
    eph = load(str(DATA_ROOT / "step1_astronomy" / "de421.bsp"))
    all_sites = ex.load_candidate_sites()
    ref_site = next(s for s in all_sites if s["name"] == "石廊崎")
    sites = all_sites if args.include_reference else [s for s in all_sites if ex.is_primary_origin(s["origin"])]
    if args.sites_limit:
        sites = sites[:args.sites_limit]
    print(f"対象地点 {len(sites)}件(参考候補を{'含む' if args.include_reference else '含まない'})", flush=True)
    nights = ex.stage1_moon_filter(ts, eph, ref_site["lat"], ref_site["lon"])
    msm_nights = [n for n in nights if ex.forecast_regime_for_night(cache, ref_site, n) == "MSM"]
    ecmwf_nights = [n for n in nights if n not in msm_nights]
    if args.nights_limit:
        msm_nights, ecmwf_nights = msm_nights[:args.nights_limit], ecmwf_nights[:args.nights_limit]

    legacy_store, bm_store = ex.make_lp_store("legacy"), ex.make_lp_store("bm")
    out = {"nights_msm": [str(n.night_date) for n in msm_nights], "nights_ecmwf": [str(n.night_date) for n in ecmwf_nights]}
    survivors = ex.stage2_cloud_filter(ts, eph, msm_nights, sites, cache) if msm_nights else []
    out["n_survivors"] = len(survivors)
    f_legacy = ex.stage3_direction_filter(ts, eph, survivors, legacy_store)
    f_bm = ex.stage3_direction_filter(ts, eph, survivors, bm_store)
    out["near_term"] = compare("近日中(MSM圏内)", f_legacy, f_bm)
    if ecmwf_nights:
        o_legacy = ex.stage_outlook(ts, eph, ecmwf_nights, sites, legacy_store, cache)
        o_bm = ex.stage_outlook(ts, eph, ecmwf_nights, sites, bm_store, cache)
        out["outlook"] = compare("見込み(ECMWF圏内)", o_legacy, o_bm)

    # 方向フィルタ(光害)で落ちた地点: 雲の足切りを通った(night, site)のうち光害で落ちたもの
    surv_keys = {(str(s["night"].night_date), s["site"]["name"]) for s in survivors}
    out["lp_dropped"] = {
        "legacy": sorted(f"{k[0]} {k[1]}" for k in surv_keys - {key(c) for c in f_legacy}),
        "bm": sorted(f"{k[0]} {k[1]}" for k in surv_keys - {key(c) for c in f_bm}),
    }
    out["cache"] = {"api_calls": cache.call_count, "cache_hits": cache.cache_hit_count, "summary": cache.summary().console_line()}
    txt = json.dumps(out, ensure_ascii=False, indent=2)
    if args.json_out:
        args.json_out.write_text(txt + "\n", encoding="utf-8")
    sys.stdout.buffer.write(("\n" + txt + "\n").encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
