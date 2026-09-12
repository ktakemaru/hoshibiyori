"""hoshibiyori 静的ランキング: 日時に依存しない条件(光害+地形)だけでcurated 84件を順位付けする。

探索モード(explore_hoshibiyori.py)のスコアは月齢・対象天体の方位角・雲量など日時依存の要素を
多分に含むため、「この地点は絶対的にどれくらい星空撮影に適しているか」を見るには不向きな場面がある。
本スクリプトは、時刻や日付、対象天体を一切考慮せず、以下の2つの静的な地点固有データだけを用いる。

- 光害(step3_light_pollution): 地点の光害輝度比LPI・mag/arcsec^2・簡易ボートル近似。
- 地形(step2_terrain, stargazing_spots.jsonのhorizon_profile): 360方位角の地平線仰角プロファイルから
  「平均地平線仰角」(全方位の平均。低い=全方位的に開けている、高い=周囲を山などに囲まれている)、
  「最も開けた方位の仰角」「最も塞がれた方位の仰角」を算出する。特定の対象天体の方位に絞らないのは、
  本ランキングが日時非依存(=特定の一夜・一天体を前提にしない)であることの裏返し。

静的スコア = (100 - LPI×10) - 平均地平線仰角×2.0
  - 光害項は探索モード本体と同じ重み(LPI×10)を踏襲。
  - 地形項は「全方位の平均仰角」×2.0(探索モードの片方向仰角差×0.5より重めに設定。
    全方位平均は特定方位の値より変動が小さいため、同程度の影響を持たせるための調整)。
  重み付けは一つの目安であり、絶対的な基準ではない。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent
for sub in ["step2_terrain", "step3_light_pollution"]:
    sys.path.insert(0, str(ROOT / sub))

from light_pollution import LightPollutionTileStore  # noqa: E402

STARGAZING_SPOTS_PATH = ROOT / "stargazing_spots.json"

ELEVATION_BY_NAME = {
    "富士山頂": 3776.0, "須走口五合目": 1975.0, "精進湖 他手合浜": 914.56,
    "八ヶ岳南麓天文台": 1060.38, "石廊崎": 60.0, "いすみ鉄道踏切": 17.57,
    "ヘブンスそのはら": 1600.36,
}


def load_horizon_profile(csv_path: str) -> dict[int, float]:
    import csv
    profile = {}
    with open(ROOT / csv_path, encoding="utf-8") as f:
        lines = [l for l in f if not l.startswith("#")]
    reader = csv.DictReader(lines)
    for row in reader:
        profile[int(row["azimuth_deg"])] = float(row["horizon_altitude_deg"])
    return profile


def main() -> None:
    with open(STARGAZING_SPOTS_PATH, encoding="utf-8") as f:
        data = json.load(f)
    spots = data["spots"]

    lp_store = LightPollutionTileStore(cache_dir=str(ROOT / "step3_light_pollution" / "tile_cache"), year=2025)

    rows = []
    for s in spots:
        lp = lp_store.get(s["lat"], s["lon"])
        profile = load_horizon_profile(s["horizon_profile"])
        values = list(profile.values())
        mean_h = sum(values) / len(values)
        max_h = max(values)
        min_h = min(values)
        elevation_m = ELEVATION_BY_NAME.get(s["name"], s.get("elevation_m"))

        static_score = (100.0 - lp.brightness_ratio * 10.0) - mean_h * 2.0

        rows.append({
            "name": s["name"], "prefecture": s["prefecture"], "municipality": s["municipality"],
            "elevation_m": elevation_m, "lpi": lp.brightness_ratio, "mpsas": lp.mpsas,
            "bortle": lp.bortle_approx, "mean_horizon": mean_h, "max_horizon": max_h,
            "min_horizon": min_h, "static_score": static_score,
        })

    rows.sort(key=lambda r: r["static_score"], reverse=True)

    print(f"{'順位':>4} {'地点':16s} {'都道府県':6s} {'標高':>6s} {'LPI':>6s} {'mag/as2':>8s} "
          f"{'Bortle':>6s} {'地平線平均':>8s} {'最悪方位':>8s} {'最良方位':>8s} {'静的スコア':>8s}")
    print("-" * 100)
    for i, r in enumerate(rows, 1):
        ele_str = f"{r['elevation_m']:.0f}m" if r["elevation_m"] is not None else "?"
        print(f"{i:4d} {r['name']:16s} {r['prefecture']:6s} {ele_str:>6s} "
              f"{r['lpi']:6.2f} {r['mpsas']:8.2f} {r['bortle']:6d} "
              f"{r['mean_horizon']:8.1f} {r['max_horizon']:8.1f} {r['min_horizon']:8.1f} "
              f"{r['static_score']:8.1f}")


if __name__ == "__main__":
    main()
