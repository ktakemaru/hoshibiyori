"""現行(LPI)と新指数(ALR)で、方向フィルタの通過/非通過が食い違う地点を出す(段階LP2)。numpyのみ・通信なし。

    py -X utf8 step3_light_pollution/bm_disagreements.py [--md-out ...]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import bm_threshold as bt  # noqa: E402
import skyglow_bm as sg  # noqa: E402


def compute(lpi_threshold: float, alr_threshold: float):
    spots, alr = bt.load_pairs()
    import legacy_ref  # 事前計算のlpiは外したので、光害タイルから計算する
    lpi = legacy_ref.legacy_lpi(spots)
    r_lpi, r_alr = sg.rank_pct(lpi), sg.rank_pct(alr)
    pass_l, pass_b = lpi <= lpi_threshold, alr <= alr_threshold
    rows = []
    for i in np.where(pass_l != pass_b)[0]:
        s = spots[i]
        rows.append({"name": s["name"], "pref": s.get("prefecture"), "elev": s.get("elevation_m"),
                     "site_type": s.get("site_type"), "lpi": float(lpi[i]), "alr": float(alr[i]),
                     "rank_lpi": float(r_lpi[i]), "rank_alr": float(r_alr[i]),
                     "legacy": "通過" if pass_l[i] else "不通過", "bm": "通過" if pass_b[i] else "不通過"})
    rows.sort(key=lambda r: (r["legacy"], r["rank_alr"]))
    return rows, int(pass_l.sum()), int(pass_b.sum()), len(spots)


def to_markdown(rows) -> str:
    out = ["| 地点 | 県 | 標高m | site_type | LPI | ALR | LPI順位% | ALR順位% | 現行(LPI≦5.0) | 新(ALR≦閾値) |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        out.append(f"| {r['name']} | {r['pref']} | {r['elev']:.0f} | {r['site_type']} | {r['lpi']:.2f} | {r['alr']:.2f} | "
                   f"{r['rank_lpi']:.1f} | {r['rank_alr']:.1f} | {r['legacy']} | {r['bm']} |")
    return "\n".join(out) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--md-out", type=Path)
    args = ap.parse_args()
    sys.path.insert(0, str(HERE.parent))
    import explore_hoshibiyori as ex
    from lp_source import BM_ALR_THRESHOLD
    rows, nl, nb, n = compute(ex.LPI_THRESHOLD, BM_ALR_THRESHOLD)
    md = f"現行の通過 {nl}件 / 新指数の通過 {nb}件 / {n}件中。食い違い {len(rows)}件\n\n" + to_markdown(rows)
    if args.md_out:
        args.md_out.write_text(md, encoding="utf-8")
    sys.stdout.buffer.write(md.encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
