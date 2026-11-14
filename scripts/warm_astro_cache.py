"""薄明・月の時刻の保存(astro_grid_cache.py)を、先に計算しておく(通信しない)。

登録済みの全地点(stargazing_spots.json の spots と viewpoint_reference)が属する0.25度格子のセルと、
基準地点(石廊崎)について、今日から N 夜分を計算して保存する。1夜ごとに書き出すので、途中で止めても
そこまでの分は保存されている。探索(explore_hoshibiyori.py / generate_report.py の既定 `--astro-grid ecmwf`)は
次の実行から、保存済みの夜を読むだけになる。

    py -X utf8 scripts/warm_astro_cache.py --days 30
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import explore_hoshibiyori as ex  # noqa: E402


def warm(days: int, start: date | None = None, cache_dir: Path | None = None, ts=None, eph=None,
         sites: list[dict] | None = None, out=print) -> tuple[int, int]:
    """戻り値: (計算した件数, 保存済みだった件数)。"""
    if ts is None:
        ts = ex.load.timescale()
    if eph is None:
        eph = ex.load(str(ex.DATA_ROOT / "step1_astronomy" / ex.EPHEMERIS_FILE))
    if sites is None:
        sites = ex.load_candidate_sites()
    ref = next((s for s in sites if s["name"] == "石廊崎"), None)
    astro = ex.make_astro_cache("ecmwf", cache_dir=cache_dir)
    cells = sorted({astro.cell_of(s["lat"], s["lon"]) for s in sites})
    start = start or datetime.now(ex.JST).date()
    out(f"[天文計算の先行計算] {len(sites)}地点 → {len(cells)}セル × {days}夜(保存先: {astro.dir})")
    computed = reused = 0
    t0 = time.perf_counter()
    for i in range(days):
        d = start + timedelta(days=i)
        before_c, before_d = astro.computed, astro.from_disk
        for lat, lon in cells:
            astro.cell_night(ts, eph, lat, lon, d)
        if ref is not None:
            astro.reference_night(ts, eph, ref["lat"], ref["lon"], datetime(d.year, d.month, d.day, tzinfo=ex.JST))
        astro.flush()  # 1夜ごとに書き出す(メモリを抱え込まない)
        c, r = astro.computed - before_c, astro.from_disk - before_d
        computed += c
        reused += r
        astro.forget(d)  # 書き出した夜はメモリから外す
        out(f"  {d} ({i + 1}/{days}夜): 計算 {c} 件 / 保存済み {r} 件  経過 {time.perf_counter() - t0:.0f} 秒")
    out(f"完了: 計算 {computed} 件 / 保存済み {reused} 件")
    return computed, reused


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="薄明・月の時刻(0.25度格子×夜)を先に計算して保存する(通信しない)")
    ap.add_argument("--days", type=int, default=30, help="今日から何夜分を計算するか(既定30)")
    ap.add_argument("--cache-dir", default=None,
                    help="保存先(既定は探索と同じ <データ領域>/step1_astronomy/astro_cache。試すとき用)")
    a = ap.parse_args(argv)
    if a.days < 1:
        ap.error("--days は1以上")
    warm(a.days, cache_dir=Path(a.cache_dir) if a.cache_dir else None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
