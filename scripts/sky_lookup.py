"""星空ガイドの解説に書く数値を、数値JSON(hoshibiyori-skyguide-data/1)から引く。通信しない。

使い方:
    # 方位範囲の稜線の仰角(360°をまたぐ範囲も可)
    py -X utf8 scripts/sky_lookup.py --data out/xxx_data.json --az 345 15
    # ある時刻の天体の方位(16方位)と高度
    py -X utf8 scripts/sky_lookup.py --data out/xxx_data.json --time 21:40 --names アルタイル ベガ デネブ

--az と --time は同時に指定してもよい。方位表の elevation・カードの本文の高度は、ここで出した値を使う(覚えや推測で書かない)。
時刻は数値JSONの times にあるものだけ。解説の機械照合(skyguide/check_numbers.py)も同じ関数で同じ値を使う。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from skyguide.lookup import compass16, frame_index, known_object_names, position_in_frame, ridge_range  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True)
    ap.add_argument("--az", nargs=2, type=float, metavar=("FROM", "TO"), help="方位範囲(度)。例: 345 15")
    ap.add_argument("--time", help="時刻 HH:MM(数値JSONの times のどれか)")
    ap.add_argument("--names", nargs="+", default=[], help="天体名(--time と併用)。例: アルタイル ベガ 土星 月 天の川の中心部")
    a = ap.parse_args()
    if a.az is None and not a.time:
        ap.error("--az か --time のどちらかが必要です")
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
    return rc


if __name__ == "__main__":
    sys.exit(main())
