"""数値JSON + 解説JSON → 星空ガイドのHTML(1ファイル完結)。通信しない。

使い方:
    py -X utf8 scripts/render_sky_guide.py --data out/xxx_data.json --commentary out/xxx_commentary.json --out out/xxx.html
必須要素の欠落・範囲外の値・basisの無い山名はエラー(終了コード1)。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from skyguide.render import SkyGuideError, render_html  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True)
    ap.add_argument("--commentary", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    try:
        data = json.loads(Path(a.data).read_text(encoding="utf-8"))
        comm = json.loads(Path(a.commentary).read_text(encoding="utf-8"))
        doc = render_html(data, comm)
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
