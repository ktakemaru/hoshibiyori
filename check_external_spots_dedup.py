"""ユーザーが他システムから入手した星空撮影スポットリスト(external_spots_20260907.csv)を、
既存のstargazing_spots.json(spots 84件 + viewpoint_reference 751件)と座標ベースで
突合し、重複候補と新規候補に分類する(統合前の下調べ用、一時スクリプト)。
"""
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, "step7_geocoding")
from dedup import haversine_m, _names_match  # noqa: E402

ROOT = Path(__file__).parent
DUP_THRESHOLD_M = 1500.0

with open(ROOT / "external_spots_20260907.csv", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    new_spots = []
    for row in reader:
        lat_str, lon_str = row["位置情報"].split(",")
        new_spots.append({"name": row["場所名"].strip(), "lat": float(lat_str), "lon": float(lon_str)})

with open(ROOT / "stargazing_spots.json", encoding="utf-8") as f:
    data = json.load(f)

existing = []
for s in data["spots"]:
    existing.append({"name": s["name"], "lat": s["lat"], "lon": s["lon"], "src": "spots(curated)"})
for s in data["viewpoint_reference"]:
    existing.append({"name": s["name"], "lat": s["lat"], "lon": s["lon"], "src": "viewpoint_reference"})

NAME_MATCH_SEARCH_RADIUS_M = 10000.0

high_conf_dup = []
review_needed = []
new_lines = []

for ns in new_spots:
    all_dists = [(haversine_m(ns["lat"], ns["lon"], ex["lat"], ex["lon"]), ex) for ex in existing]
    all_dists.sort(key=lambda t: t[0])

    within = [(d, ex) for d, ex in all_dists if d <= DUP_THRESHOLD_M]
    name_matched_any = [(d, ex) for d, ex in all_dists
                         if d <= NAME_MATCH_SEARCH_RADIUS_M and _names_match(ns["name"], ex["name"])[0]]
    name_matched_close = [(d, ex) for d, ex in within if _names_match(ns["name"], ex["name"])[0]]

    if name_matched_close:
        d, ex = name_matched_close[0]
        high_conf_dup.append(f"[高確度重複 {d:5.0f}m 名前一致] {ns['name']:28s} <-> {ex['name']}（{ex['src']}）")
    elif name_matched_any:
        d, ex = name_matched_any[0]
        review_needed.append(f"[要確認 {d/1000:5.1f}km 同名だが距離あり] {ns['name']:28s} <-> {ex['name']}（{ex['src']}）")
    elif within:
        d, ex = within[0]
        review_needed.append(f"[要確認 {d:5.0f}m 名前不一致] {ns['name']:28s} <-> {ex['name']}（{ex['src']}）")
    else:
        d, ex = all_dists[0] if all_dists else (None, None)
        near_note = f"(最寄り既存地点まで{d/1000:.1f}km: {ex['name']})" if ex else ""
        new_lines.append(f"[新規候補] {ns['name']:28s} {near_note}")

print(f"=== 高確度重複(名前一致・{DUP_THRESHOLD_M:.0f}m以内、{len(high_conf_dup)}件、スキップ推奨) ===")
for line in high_conf_dup:
    print(line)

print(f"\n=== 要確認({len(review_needed)}件、目視判断が必要) ===")
for line in review_needed:
    print(line)

print(f"\n=== 新規候補({len(new_lines)}件) ===")
for line in new_lines:
    print(line)

print(f"\n合計: 新規{len(new_spots)}件中、高確度重複{len(high_conf_dup)}件・要確認{len(review_needed)}件・新規候補{len(new_lines)}件")
