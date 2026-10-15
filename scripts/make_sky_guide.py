"""星空ガイドの数値JSONを、hoshibiyoriの既存ロジックで作る(エージェントは数値を書かない)。

使い方:
    py -X utf8 scripts/make_sky_guide.py --spot 戦場ヶ原 --date 2026-10-09 --json-out out/senjogahara_data.json
    py -X utf8 scripts/make_sky_guide.py --name 地点名 --lat 36.7 --lon 139.4 --elevation 1400 --horizon-csv <csv> --date 2026-10-09 --json-out out/x.json
    py -X utf8 scripts/make_sky_guide.py --spot 戦場ヶ原 --estimate      # 通信が要る見込みだけを表示して終了(通信しない)

既定では通信しない: 雲量はディスクキャッシュ(有効期限内)だけを使い、無ければ理由つきで省略する。
通信が要る経路(--cloud fetch)は --allow-network が必要で、実行前に所要時間・リクエスト数の見込みを
ユーザーに伝えて承認を得ること(AGENTS.md)。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from skyguide.build import build_data, estimate_requests, load_spot  # noqa: E402
from skyguide.render import SkyGuideError  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--spot", help="stargazing_spots.json の地点名またはid")
    ap.add_argument("--name"); ap.add_argument("--lat", type=float); ap.add_argument("--lon", type=float)
    ap.add_argument("--elevation", type=float, help="観測者標高(m)。一覧にない地点では必須")
    ap.add_argument("--horizon-csv", help="一覧にない地点の稜線CSV(step2_terrainの出力。ルートからの相対パス)")
    ap.add_argument("--coordinate-source", default="ユーザー指定", help="一覧にない地点の座標・標高の出典")
    ap.add_argument("--date", help="夜の開始日 YYYY-MM-DD")
    ap.add_argument("--json-out")
    ap.add_argument("--cloud", choices=("cache", "fetch", "off"), default="cache", help="cache=通信せずキャッシュのみ(既定) / fetch=取得(通信) / off")
    ap.add_argument("--allow-network", action="store_true", help="通信を伴う処理を許可する(承認を得てから)")
    ap.add_argument("--estimate", action="store_true", help="通信の見込みだけ表示して終了")
    a = ap.parse_args()
    try:
        if a.spot:
            spot = load_spot(a.spot)
        else:
            if None in (a.name, a.lat, a.lon, a.elevation):
                raise SkyGuideError("--spot か、--name --lat --lon --elevation(+--horizon-csv)のどちらかを指定してください")
            spot = {"name": a.name, "lat": a.lat, "lon": a.lon, "elevation_m": a.elevation, "horizon_profile": a.horizon_csv,
                    "coordinate_source": a.coordinate_source, "elevation_source": a.coordinate_source}
        if a.estimate:
            print(json.dumps(estimate_requests(spot), ensure_ascii=False, indent=2))
            return 0
        if not a.date or not a.json_out:
            raise SkyGuideError("--date と --json-out が必要です")
        data = build_data(spot=spot, night_date=date.fromisoformat(a.date), allow_network=a.allow_network, cloud_mode=a.cloud)
    except (SkyGuideError, ValueError) as e:
        print(f"[エラー] {e}", file=sys.stderr)
        return 1
    out = Path(a.json_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    c = data["cloud"]
    print(f"出力: {out}  雲量: {'あり' if c else '省略(' + data['cloud_omitted_reason'][:40] + '…)'}  イベント{len(data['events'])}件  ピーク候補{len(data['peak_candidates'])}件")
    return 0


if __name__ == "__main__":
    sys.exit(main())
