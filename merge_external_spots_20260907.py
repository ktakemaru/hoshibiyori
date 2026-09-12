"""外部システムから入手した星空撮影スポットリスト(external_spots_20260907.csv)のうち、
重複判定(scratch_dedup_check.py)で「新規」と判断された62件を、逆ジオコーディング・
標高取得・光害計算のうえstargazing_spots.jsonのspots配列に追加する(2026-09-07)。

重複判定結果(ユーザー確認済み):
- 高確度重複25件+目視判断で重複と判断した13件(計38件)はスキップ(既存を正とする)
- 新規候補50件+目視判断で別地点と判断した12件(計62件)を新規追加

新設origin="curated_external"(他システム由来、Web調査での説明文なし)。
ExPLORE_HOSHIBIYORI.PYのORIGIN_LABELS/PRIMARY_ORIGINSへの追加は別途手動で行う。
"""
import csv
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "step2_terrain")
sys.path.insert(0, "step3_light_pollution")
sys.path.insert(0, "step7_geocoding")

from gsi_dem import DemTileStore  # noqa: E402
from light_pollution import LightPollutionTileStore  # noqa: E402
from reverse_geocode import reverse_geocode_municipality  # noqa: E402

ROOT = Path(__file__).parent
LPI_THRESHOLD = 5.0  # explore_hoshibiyori.pyと同値(重複定義だが、このスクリプトは一時的な単体実行用)

SKIP_NAMES = {
    # 高確度重複(名前一致・1.5km以内)
    "車山高原（車山山頂）", "しらびそ高原", "乗鞍畳平（乗鞍岳）", "戦場ヶ原（展望台）",
    "奥日光・湯ノ湖", "中禅寺湖（歌ヶ浜駐車場）", "野反湖", "ヤビツ峠（菜の花台展望台）",
    "箱根・大観山展望台", "犬吠埼灯台", "野島埼灯台", "勝浦・八幡岬公園", "八ヶ岳南麓天文台",
    "清里高原（美し森）", "甘利山", "弥彦山山頂展望台", "田貫湖", "西伊豆・黄金崎",
    "あいあい岬（石廊崎）", "寸又峡", "茶臼山高原", "ひるがの高原", "白川郷（荻町城跡展望台）",
    "見附島", "立山室堂",
    # 目視判断で重複と判断(ユーザー確認済み)
    "ヘブンスそのはら（阿智村）", "美ヶ原高原展望台", "本栖湖（浩庵キャンプ場付近）",
    "精進湖（他々戸浜）", "山中湖（パノラマ台）", "朝霧高原（道の駅朝霧高原）", "天城高原",
    "伊良湖岬", "しらびそ山荘周辺", "赤城山（鳥居峠）", "堂平山天文台（堂平つくし村）",
    "奥多摩湖（水と緑のふれあい館前）", "星の峠の棚田",
}

with open(ROOT / "external_spots_20260907.csv", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    all_spots = []
    for row in reader:
        lat_str, lon_str = row["位置情報"].split(",")
        all_spots.append({"name": row["場所名"].strip(), "lat": float(lat_str), "lon": float(lon_str)})

to_add = [s for s in all_spots if s["name"] not in SKIP_NAMES]
print(f"追加対象: {len(to_add)}件(全{len(all_spots)}件中、スキップ{len(all_spots) - len(to_add)}件)")

dem_store = DemTileStore(cache_dir=str(ROOT / "step2_terrain" / "dem_cache"), dataset="dem")
lp_store = LightPollutionTileStore(cache_dir=str(ROOT / "step3_light_pollution" / "tile_cache"), year=2025)

with open(ROOT / "stargazing_spots.json", encoding="utf-8") as f:
    data = json.load(f)

existing_ids = [s["id"] for s in data["spots"] if s["id"].startswith("curated_ext:")]
next_num = len(existing_ids) + 1

new_entries = []
for i, s in enumerate(to_add, 1):
    geo = reverse_geocode_municipality(s["lat"], s["lon"])
    prefecture = geo.raw_address.get("state") if geo.raw_address else None
    municipality = geo.municipality
    elevation = dem_store.get_elevation(s["lat"], s["lon"])
    if elevation is None:
        elevation = 0.0
    lp_result = lp_store.get(s["lat"], s["lon"])
    site_type = "dark_sky" if lp_result.brightness_ratio <= LPI_THRESHOLD else "night_view"

    entry = {
        "id": f"curated_ext:{next_num:03d}",
        "name": s["name"],
        "prefecture": prefecture,
        "municipality": municipality or "不明",
        "description": None,
        "nominatim_display_name": None,
        "lat": s["lat"],
        "lon": s["lon"],
        "coordinate_source": "user_provided",
        "origin": "curated_external",
        "matched_candidate": None,
        "horizon_profile": None,
        "light_pollution_computed": True,
        "elevation_m": round(elevation, 2),
        "lpi": round(lp_result.brightness_ratio, 2),
        "mpsas": round(lp_result.mpsas, 2),
        "bortle_approx": lp_result.bortle_approx,
        "site_type": site_type,
    }
    new_entries.append(entry)
    next_num += 1
    print(f"  [{i}/{len(to_add)}] {s['name']:28s} -> {prefecture or '?'} {municipality or '?'} "
          f"標高{elevation:.0f}m LPI={lp_result.brightness_ratio:.2f} -> {site_type}"
          f"{' (geocodeエラー: ' + geo.error + ')' if geo.error else ''}")

data["spots"].extend(new_entries)
data["counts"]["spots_confirmed_total"] = len(data["spots"])
data["counts"]["spots_curated_external_added_20260907"] = len(new_entries)

with open(ROOT / "stargazing_spots.json", "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print(f"\n完了: {len(new_entries)}件をstargazing_spots.jsonのspots配列に追加しました(合計{len(data['spots'])}件)。")
