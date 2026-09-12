"""取得したviewpointデータの分布確認と、既存検証地点との近傍チェック。"""
from __future__ import annotations

import json
import math

from fetch_viewpoints import BBOX, fetch_viewpoints, save_viewpoints_json

# これまで検証してきた地点(緯度, 経度)
TEST_SITES = {
    "富士山頂": (35.3606, 138.7274),
    "須走口五合目": (35.364942, 138.777077),
    "精進湖 他手合浜": (35.490824, 138.605076),
    "八ヶ岳南麓天文台": (35.882707, 138.36435),
    "石廊崎": (34.602778, 138.845278),
    "いすみ鉄道踏切": (35.282583, 140.297250),
    "阿智村 ヘブンスそのはら付近": (35.456090, 137.633603),
}

# 都市部・山間部・海岸部の代表的な小地域(南, 北, 西, 東)で密度を比較する
REGIONS = {
    "東京都心(都市部)": (35.60, 35.75, 139.60, 139.85),
    "秩父・奥多摩(山間部)": (35.85, 36.05, 138.75, 139.05),
    "伊豆半島(海岸・山)": (34.60, 35.20, 138.75, 139.15),
    "房総半島南部(海岸)": (34.90, 35.30, 139.90, 140.40),
    "日光・足尾(山間部)": (36.60, 36.90, 139.40, 139.70),
    "鎌倉・湘南(海岸)": (35.25, 35.40, 139.45, 139.65),
}


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def main() -> None:
    viewpoints = fetch_viewpoints()
    save_viewpoints_json(viewpoints, "viewpoints_kanto.json")

    print(f"=== 関東地方 tourism=viewpoint 取得結果 ===")
    print(f"バウンディングボックス: 南{BBOX[0]} 西{BBOX[1]} 北{BBOX[2]} 東{BBOX[3]}")
    print(f"総件数: {len(viewpoints)}\n")

    with_name = sum(1 for v in viewpoints if v.name)
    with_ele = sum(1 for v in viewpoints if v.ele)
    with_desc = sum(1 for v in viewpoints if v.description)
    print(f"name タグあり: {with_name} ({with_name/len(viewpoints)*100:.1f}%)")
    print(f"ele タグあり : {with_ele} ({with_ele/len(viewpoints)*100:.1f}%)")
    print(f"description タグあり: {with_desc} ({with_desc/len(viewpoints)*100:.1f}%)\n")

    print("--- 地域別の密度(都市部 vs 山間部 vs 海岸部) ---")
    for name, (lat_min, lat_max, lon_min, lon_max) in REGIONS.items():
        count = sum(1 for v in viewpoints if lat_min <= v.lat <= lat_max and lon_min <= v.lon <= lon_max)
        area_deg2 = (lat_max - lat_min) * (lon_max - lon_min)
        density = count / area_deg2
        print(f"  {name:24s} 件数={count:4d}  密度={density:7.1f}件/deg^2")
    print()

    print("--- 既存検証地点の近傍チェック ---")
    for name, (lat, lon) in TEST_SITES.items():
        in_bbox = BBOX[0] <= lat <= BBOX[2] and BBOX[1] <= lon <= BBOX[3]
        if not in_bbox:
            print(f"  {name:24s}: 検索範囲(関東bbox)外のため対象外")
            continue
        nearest = min(viewpoints, key=lambda v: haversine_m(lat, lon, v.lat, v.lon))
        d = haversine_m(lat, lon, nearest.lat, nearest.lon)
        print(f"  {name:24s}: 最近傍 {d:7.0f}m  name={nearest.name!r}")


if __name__ == "__main__":
    main()
