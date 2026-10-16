"""星空ガイドの解説に書く数値を、数値JSON(hoshibiyori-skyguide-data/1)から引く。通信しない。

使い方:
    # 方位範囲の稜線の仰角(360°をまたぐ範囲も可)
    py -X utf8 scripts/sky_lookup.py --data out/xxx_data.json --az 345 15
    # ある時刻の天体の方位(16方位)と高度
    py -X utf8 scripts/sky_lookup.py --data out/xxx_data.json --time 21:40 --names アルタイル ベガ デネブ
    # 時間帯の天体の高度の最小〜最大(日付またぎ可。端は隣り合うフレーム間の直線補間、0°未満は0°で切る)
    py -X utf8 scripts/sky_lookup.py --data out/xxx_data.json --time-range 23:20 00:10 --names すばる 木星

--az・--time・--time-range は同時に指定してもよい。方位表の elevation・カードの本文の高度は、ここで出した値を使う(覚えや推測で書かない)。
時刻は数値JSONの times にあるものだけ。解説の機械照合(skyguide/check_numbers.py)も同じ関数で同じ値を使う。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from skyguide.lookup import (altitude_range_in_window, compass16, frame_index, known_object_names,  # noqa: E402
                             position_in_frame, ridge_range)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True)
    ap.add_argument("--az", nargs=2, type=float, metavar=("FROM", "TO"), help="方位範囲(度)。例: 345 15")
    ap.add_argument("--time", help="時刻 HH:MM(数値JSONの times のどれか)")
    ap.add_argument("--time-range", nargs=2, metavar=("START", "END"), help="時間帯 HH:MM HH:MM(日付またぎ可。例: 23:20 00:10)")
    ap.add_argument("--names", nargs="+", default=[], help="天体名(--time・--time-range と併用)。例: アルタイル ベガ 土星 月 天の川の中心部")
    a = ap.parse_args()
    if a.az is None and not a.time and not a.time_range:
        ap.error("--az・--time・--time-range のいずれかが必要です")
    try:
        data = json.loads(Path(a.data).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"[エラー] {e}", file=sys.stderr)
        return 1
    rc = 0
    if a.az is not None:
        hz = data.get("horizon_deg")
        if not isinstance(hz, list) or not hz:
            print("[エラー] 数値JSONに horizon_deg がありません", file=sys.stderr)
            return 1
        lo, hi = ridge_range(hz, a.az[0], a.az[1])
        shown = f"{lo}°" if lo == hi else f"{lo}〜{hi}°"
        print(f"方位 {int(a.az[0]) % 360}〜{int(a.az[1]) % 360}° の稜線の仰角: {shown}")
    if a.time:
        idx = frame_index(data, a.time)
        if idx is None:
            print(f"[エラー] 時刻 {a.time} は数値JSONの times にありません。使える時刻: {' '.join(data.get('times', []))}", file=sys.stderr)
            return 1
        if not a.names:
            known = sorted(known_object_names(data))
            print(f"{a.time} の天体を引くには --names を付けます。使える名前: {'、'.join(known)}")
            return 1
        frame = data["frames"][idx]
        for n in a.names:
            pos = position_in_frame(frame, n)
            if pos is None:
                print(f"[エラー] {n} は {a.time} のフレームにありません", file=sys.stderr)
                rc = 1
                continue
            az, alt = pos
            below = "(地平線の下)" if alt < 0 else ""
            print(f"{a.time} {n}: {compass16(az)}(方位角{az:.0f}°) 高度{alt:.0f}°{below}")
    if a.time_range:
        if not a.names:
            print("--time-range には --names が必要です", file=sys.stderr)
            return 1
        start, end = a.time_range
        for n in a.names:
            r = altitude_range_in_window(data, n, start, end)
            if r is None:
                print(f"[エラー] {n} の {start}〜{end} の高度範囲を出せません(時間帯が夜のフレームの範囲外、または {n} がフレームに無い)", file=sys.stderr)
                rc = 1
                continue
            lo, hi = r
            print(f"{start}〜{end} {n}: 高度{lo}°" if lo == hi else f"{start}〜{end} {n}: 高度{lo}〜{hi}°")
    return rc


if __name__ == "__main__":
    sys.exit(main())
