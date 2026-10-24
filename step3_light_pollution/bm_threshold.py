"""ALRの仮閾値を「主軸の地点のうちN件が通る」条件で求め直す(段階LP2、段階LP3bで光害タイル非依存に)。

Nは `lp_source.BM_THRESHOLD_N_PASS`(141。段階LP2で、以前の方式の閾値で通った件数として決めた固定値)。
ALRが小さい順にN件が通るALRの境界を仮の閾値とする(N番目と(N+1)番目のALRの中点)。
年次の更新(UPDATE.md)でALRが変わったときに、同じ件数での閾値がどう動くかを見るのに使う。
論文のTable 3(ALR>10)は日本に較正されていないので使わない(参考の件数だけ出す)。

    py -X utf8 step3_light_pollution/bm_threshold.py [--grid ...npz] [--json-out ...]

通信しない。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import skyglow_bm as sg  # noqa: E402
from lp_source import BM_ALR_THRESHOLD, BM_THRESHOLD_N_PASS  # noqa: E402


def load_pairs(grid_path: Path = sg.DATA_DIR / "skyglow_bm_2025.npz"):
    grid = sg.DerivedGrid.load(grid_path)
    spots = json.loads(sg.SPOTS_PATH.read_text(encoding="utf-8"))["spots"]
    alr = grid.at([s["lat"] for s in spots], [s["lon"] for s in spots])
    return spots, alr


def threshold_for_count(alr: np.ndarray, n_pass: int) -> float:
    """ALRが小さい順にn_pass件が `ALR <= 閾値` で通る閾値(n番目と次の中点)。"""
    s = np.sort(np.asarray(alr, float))
    if not 0 < n_pass < len(s):
        raise ValueError("n_passは1以上、件数未満")
    if s[n_pass - 1] == s[n_pass]:
        raise ValueError("境界に同値があり、同じ件数にできない")
    return float((s[n_pass - 1] + s[n_pass]) / 2.0)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--grid", type=Path, default=sg.DATA_DIR / "skyglow_bm_2025.npz")
    ap.add_argument("--json-out", type=Path)
    args = ap.parse_args()

    spots, alr = load_pairs(args.grid)
    n_pass = BM_THRESHOLD_N_PASS
    thr_alr = threshold_for_count(alr, n_pass)
    s_alr = np.sort(alr)
    res = {
        "n_spots": len(spots), "n_pass_target": n_pass,
        "alr_threshold": round(thr_alr, 4), "current_constant": BM_ALR_THRESHOLD,
        "alr_nth": round(float(s_alr[n_pass - 1]), 4), "alr_next": round(float(s_alr[n_pass]), 4),
        "n_pass_with_current_constant": int((alr <= BM_ALR_THRESHOLD).sum()),
        "paper_table3_alr_10_for_reference": {"n_pass": int((alr <= 10.0).sum())},
    }
    txt = json.dumps(res, ensure_ascii=False, indent=2)
    if args.json_out:
        args.json_out.write_text(txt + "\n", encoding="utf-8")
    sys.stdout.buffer.write((txt + "\n").encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
