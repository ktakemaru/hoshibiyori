"""各地点にスカイグロー指数(別フィールド)を付けて `stargazing_spots.bm.json` に出す(段階LP1)。

`stargazing_spots.json` は変更しない。numpyのみ・通信なし。出力には突き合わせのため id/name/prefecture/lat/lon/site_type を写す。

    py -X utf8 step3_light_pollution/annotate_spots_bm.py [--grid ...npz] [--out stargazing_spots.bm.json]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import skyglow_bm as sg  # noqa: E402

DEFAULT_GRID = sg.DATA_DIR / "skyglow_bm_2025.npz"
DEFAULT_OUT = sg.REPO_ROOT / "stargazing_spots.bm.json"
KEEP = ("id", "name", "prefecture", "lat", "lon", "site_type")


def build_payload(grid_path: Path, spots_path: Path = sg.SPOTS_PATH) -> dict:
    grid = sg.DerivedGrid.load(grid_path)
    spots = json.loads(Path(spots_path).read_text(encoding="utf-8"))["spots"]
    ann = sg.annotate_spots(spots, grid)
    rows = [{**{k: s.get(k) for k in KEEP},
             "skyglow_bm_index": s["skyglow_bm_index"], "skyglow_bm_rank_pct": s["skyglow_bm_rank_pct"]}
            for s in ann]
    return {
        "schema": "hoshibiyori-spots-skyglow-bm/1",
        "note": "ALRは日本では未較正の相対指数。小さいほど暗い。rank_pctは0=最も暗い・100=最も明るい"
                "(この146地点の中での位置)。",
        "grid": {"file": grid_path.name, "sha256": hashlib.sha256(grid_path.read_bytes()).hexdigest(),
                 "product": grid.meta["product"], "year": grid.meta["year"], "built": grid.meta["built"]},
        "spots": rows,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--grid", type=Path, default=DEFAULT_GRID)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()
    payload = build_payload(args.grid)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    n_none = sum(1 for r in payload["spots"] if r["skyglow_bm_index"] is None)
    print(f"{args.out.name}: {len(payload['spots'])}地点 (範囲外 {n_none}件) {args.out.stat().st_size/1e3:.0f}KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
