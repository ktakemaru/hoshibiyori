"""数値JSON + 解説JSON → 星空ガイドのHTML(1ファイル完結)。通信しない。

使い方:
    py -X utf8 scripts/render_sky_guide.py --data out/xxx_data.json --commentary out/xxx_commentary.json --out out/xxx.html
必須要素の欠落・範囲外の値・basisの無い山名・数値と合わない時刻の言い回しはエラー(終了コード1)。
解説の数値(天体の高度・方位、方位表の稜線の仰角、曖昧な時間語。skyguide/check_numbers.py)の食い違い(エラー扱いのもの)も、
既定で出力しない(終了コード1)。月の形容は警告で、表示するだけで止めない。
--warn-numbers を付けると、数値の食い違いも警告として表示するだけにする。--strict-numbers は互換のために受け付けるが何もしない
(既定が止める側のため。手順書が使っている)。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from skyguide.check_numbers import check_numbers  # noqa: E402
from skyguide.check_text import check_text  # noqa: E402
from skyguide.render import SkyGuideError, render_html  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True)
    ap.add_argument("--commentary", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--no-check-text", action="store_true", help="解説の時刻の言い回しの機械照合を省く(既定は照合し、食い違いがあれば出力しない)")
    ap.add_argument("--warn-numbers", action="store_true",
                    help="解説の数値(高度・方位・稜線の仰角・曖昧な時間語)の食い違いを警告として表示するだけにする(既定は出力しない)。--no-check-text のときは何も検査しない")
    ap.add_argument("--strict-numbers", action="store_true", help="互換のために受け付けるが何もしない(数値の食い違いは既定で出力しない)")
    a = ap.parse_args()
    try:
        data = json.loads(Path(a.data).read_text(encoding="utf-8"))
        comm = json.loads(Path(a.commentary).read_text(encoding="utf-8"))
        doc = render_html(data, comm)
        findings = [] if a.no_check_text else check_text(data, comm)
        if findings:
            for f in findings:
                print(f, file=sys.stderr)
            raise SkyGuideError(f"解説の時刻の言い回しが数値と合いません({len(findings)}件)。events を見て直してください")
        numeric = [] if a.no_check_text else check_numbers(data, comm)
        for f in numeric:
            print(f"[{'警告' if f.severity == 'warning' or a.warn_numbers else 'エラー'}] {f}", file=sys.stderr)
        blocking = [f for f in numeric if f.severity == "error"]
        if blocking and not a.warn_numbers:
            raise SkyGuideError(f"解説の数値が数値JSONと合いません({len(blocking)}件)。scripts/sky_lookup.py で数値を引いて直してください")
    except (SkyGuideError, OSError, json.JSONDecodeError) as e:
        print(f"[エラー] {e}", file=sys.stderr)
        return 1
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(doc.encode("utf-8"))
    print(f"出力: {out} ({len(doc.encode('utf-8')) / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
