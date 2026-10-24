"""新指数(ALR)の仮の閾値を、現行LPI閾値と「同じ件数が通る」条件で求める(段階LP2)。

現行の方向フィルタは `LPI <= LPI_THRESHOLD`(explore_hoshibiyori.py、5.0)で足切りする。主軸146件のうち通過する件数Nを数え、
ALRが小さい順にN件が通るALRの境界を仮の閾値とする(N番目と(N+1)番目のALRの中点)。
論文のTable 3(ALR>10)は日本に較正されていないので使わない。

    py -X utf8 step3_light_pollution/bm_threshold.py [--json-out ...]

通信しない(LPIは`stargazing_spots.json`に事前計算された値を使い、`--live`で光害タイルのキャッシュから再計算して突き合わせる)。
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

LPI_THRESHOLD_FALLBACK = 5.0  # explore_hoshibiyori.LPI_THRESHOLD(実物は ex.LPI_THRESHOLD)


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
    ap.add_argument("--json-out", type=Path)
    args = ap.parse_args()

    sys.path.insert(0, str(HERE.parent))
    import explore_hoshibiyori as ex  # LPI_THRESHOLD の実物

    thr_lpi = ex.LPI_THRESHOLD
    spots, alr = load_pairs()
    import legacy_ref  # LPIは事前計算値が無いので、光害タイルから計算する(キャッシュに無ければ通信)
    lpi = legacy_ref.legacy_lpi(spots)
    n_pass = int((lpi <= thr_lpi).sum())
    res = {"lpi_threshold": thr_lpi, "n_spots": len(spots), "n_pass_legacy": n_pass}
    thr_alr = threshold_for_count(alr, n_pass)
    s_alr = np.sort(alr)
    res.update({
        "alr_threshold": round(thr_alr, 4),
        "alr_nth": round(float(s_alr[n_pass - 1]), 4), "alr_next": round(float(s_alr[n_pass]), 4),
        "n_pass_bm": int((alr <= thr_alr).sum()),
        "paper_table3_alr_10_for_reference": {"n_pass": int((alr <= 10.0).sum())},
    })
    txt = json.dumps(res, ensure_ascii=False, indent=2)
    if args.json_out:
        args.json_out.write_text(txt + "\n", encoding="utf-8")
    sys.stdout.buffer.write((txt + "\n").encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
