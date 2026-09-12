"""stargazing_spots.jsonのspots配列(curated由来84件)に光害データ(LPI等)を付与し、
「暗い空(dark_sky)」「夜景系(night_view)」に分類するタグ(site_type)を追加する。

背景: curated_spots.json(Web調査ベース)は光害データを見ずに「星空スポット」という
紹介文だけを根拠に収集しているため、実際には夜景で有名な高台(菜の花台・大観山展望台等、
光害LPIが高い)が「星空スポット」として混入している。これらは天の川銀河中心のような
淡い対象には向かないが、街の灯りと明るい星を組み合わせる撮影地としては別の価値がある。
両者を光害データに基づいて機械的に見分けられるようにする(2026-09-07、ユーザー提案により追加)。

分類基準はexplore_hoshibiyori.pyのLPI_THRESHOLDをそのままimportして使う(値を
重複定義すると、後で閾値を調整した際にこちらの更新を忘れて食い違うおそれがあるため)。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "step3_light_pollution"))
sys.path.insert(0, str(ROOT))

from light_pollution import LightPollutionTileStore  # noqa: E402
from explore_hoshibiyori import LPI_THRESHOLD  # noqa: E402

STARGAZING_SPOTS_PATH = ROOT / "stargazing_spots.json"

SITE_TYPE_LABELS = {
    "dark_sky": "暗い空(天の川など淡い対象向け)",
    "night_view": "夜景系(光害あり、明るい星・惑星や夜景との組み合わせ向け)",
}


def main() -> None:
    with open(STARGAZING_SPOTS_PATH, encoding="utf-8") as f:
        data = json.load(f)

    lp_store = LightPollutionTileStore(cache_dir=str(ROOT / "step3_light_pollution" / "tile_cache"), year=2025)

    dark_sky_count = 0
    night_view_count = 0
    for spot in data["spots"]:
        result = lp_store.get(spot["lat"], spot["lon"])
        spot["lpi"] = round(result.brightness_ratio, 2)
        spot["mpsas"] = round(result.mpsas, 2)
        spot["bortle_approx"] = result.bortle_approx
        spot["light_pollution_computed"] = True
        if result.brightness_ratio <= LPI_THRESHOLD:
            spot["site_type"] = "dark_sky"
            dark_sky_count += 1
        else:
            spot["site_type"] = "night_view"
            night_view_count += 1
        print(f"  {spot['name']}（{spot['municipality']}）: LPI={spot['lpi']:.2f} "
              f"bortle≈{spot['bortle_approx']} -> {SITE_TYPE_LABELS[spot['site_type']]}")

    data["counts"]["spots_dark_sky"] = dark_sky_count
    data["counts"]["spots_night_view"] = night_view_count
    data["_note_site_type"] = (
        f"2026-09-07追加。spots配列の各エントリにlpi/mpsas/bortle_approx/site_typeを追加した。"
        f"site_typeはexplore_hoshibiyori.pyのLPI_THRESHOLD(現在{LPI_THRESHOLD})と同じ基準で"
        "dark_sky(暗い空、天の川など淡い対象向け)/night_view(夜景系、光害あり)に分類したもの。"
        "curated_spots.json由来の「星空スポット」紹介文には、実際には夜景で有名な高台"
        "(光害が高い)も混入しているため、これを機械的に見分けられるようにする目的で追加した"
        "(classify_site_darkness.py参照)。閾値は当初3.0だったが、ユーザーの実地経験"
        "(神磯の鳥居LPI4.93・安房埼灯台LPI3.27で単発長時間露光による天の川撮影に成功、"
        "菜の花台LPI6.49・高尾山LPI10.18は同ユーザーの経験上撮影が難しい)を踏まえ"
        "2026-09-07に5.0へ引き上げた(explore_hoshibiyori.py参照)。"
    )

    with open(STARGAZING_SPOTS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\n完了: dark_sky {dark_sky_count}件 / night_view {night_view_count}件")
    print(f"{STARGAZING_SPOTS_PATH} を更新しました。")


if __name__ == "__main__":
    main()
