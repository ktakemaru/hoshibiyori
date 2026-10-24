"""stargazing_spots.json の spots 配列に、「暗い空(dark_sky)」「夜景系(night_view)」の分類タグ(site_type)を付ける。

背景: curated_spots.json(Web調査ベース)は光害データを見ずに「星空スポット」という紹介文だけを根拠に収集しているため、
夜景で有名な高台(菜の花台・大観山展望台等、光害が高い)が「星空スポット」として混入している。これらは天の川銀河中心のような
淡い対象には向かないので、光害の指標に基づいて機械的に見分けられるようにする(2026-09-07、ユーザー提案)。

分類の入力は Black Marble 由来の ALR(日本で未較正の相対指数。仮閾値 `lp_source.BM_ALR_THRESHOLD`)。
書き込むのは site_type と counts だけ(以前の光害データの経緯は README「光害データの変更」)。
実行前に stargazing_spots.json の .bak を取ること。numpy のみ・通信なし。

    py -X utf8 classify_site_darkness.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "step3_light_pollution"))

from lp_source import BM_ALR_THRESHOLD, BmLightPollutionStore  # noqa: E402

STARGAZING_SPOTS_PATH = ROOT / "stargazing_spots.json"

SITE_TYPE_LABELS = {
    "dark_sky": "暗い空(天の川など淡い対象向け)",
    "night_view": "夜景系(光害あり、明るい星・惑星や夜景との組み合わせ向け)",
}


def main() -> None:
    raw = STARGAZING_SPOTS_PATH.read_bytes().decode("utf-8")
    crlf = "\r\n" in raw
    data = json.loads(raw)
    store = BmLightPollutionStore()

    counts = {"dark_sky": 0, "night_view": 0}
    for spot in data["spots"]:
        spot["site_type"] = store.site_type(spot["lat"], spot["lon"])
        counts[spot["site_type"]] += 1
        r = store.get(spot["lat"], spot["lon"])
        print(f"  {spot['name']}（{spot['municipality']}）: ALR={r.alr:.2f} -> {SITE_TYPE_LABELS[spot['site_type']]}")

    data["counts"]["spots_dark_sky"] = counts["dark_sky"]
    data["counts"]["spots_night_view"] = counts["night_view"]
    out = json.dumps(data, ensure_ascii=False, indent=2)
    STARGAZING_SPOTS_PATH.write_bytes((out.replace("\n", "\r\n") if crlf else out).encode("utf-8"))
    print(f"\n暗い空 {counts['dark_sky']}件 / 夜景系 {counts['night_view']}件(仮閾値 ALR {BM_ALR_THRESHOLD})")


if __name__ == "__main__":
    main()
