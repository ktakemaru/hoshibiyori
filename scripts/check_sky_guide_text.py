"""解説JSONの文章中の時刻の言い回し(「N時すぎ」「N時前」など)を、数値JSONの events と機械照合する。通信しない。

使い方:
    py -X utf8 scripts/check_sky_guide_text.py --data out/xxx_data.json --commentary out/xxx_commentary.json

--numbers を付けると、数値(天体の高度・方位、方位表の稜線の仰角、曖昧な時間語、月の形容。skyguide/check_numbers.py)も照合する。
月の形容(警告)は終了コードに影響しない。

終了コード: 0=食い違いなし、1=食い違いあり(または入力エラー)。規則と対象外の範囲は skyguide/check_text.py の冒頭を参照。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from skyguide.check_numbers import check_numeric  # noqa: E402
from skyguide.check_text import check_text  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True)
    ap.add_argument("--commentary", required=True)
    ap.add_argument("--numbers", action="store_true", help="時刻の言い回しに加えて、数値(高度・稜線の仰角・曖昧な時間語・月の形容)も照合する")
    a = ap.parse_args()
    try:
        data = json.loads(Path(a.data).read_text(encoding="utf-8"))
        comm = json.loads(Path(a.commentary).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"[エラー] {e}", file=sys.stderr)
        return 1
    findings = check_text(data, comm)
    warnings = []
    if a.numbers:
        extra = check_numeric(data, comm)
        findings += [f for f in extra if f.severity == "error"]
        warnings = [f for f in extra if f.severity != "error"]
    for f in findings:
        print(f)
    for f in warnings:
        print(f"[警告] {f}")
    what = "時刻の言い回しと数値" if a.numbers else "時刻の言い回し"
    print(f"食い違い {len(findings)} 件" if findings else f"{what}は数値と合っています(照合できる範囲)")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
