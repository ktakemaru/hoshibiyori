"""候補地点DB(検証済み7地点 + viewpoint 1609件)をareas.jsonで分類し、エリアごとの件数を集計する。"""
from __future__ import annotations

import json
from pathlib import Path

from areas import find_areas, load_areas

TEST_SITES = [
    ("富士山頂", 35.3606, 138.7274),
    ("須走口五合目", 35.364942, 138.777077),
    ("精進湖 他手合浜", 35.490824, 138.605076),
    ("八ヶ岳南麓天文台", 35.882707, 138.36435),
    ("石廊崎", 34.602778, 138.845278),
    ("いすみ鉄道踏切", 35.282583, 140.297250),
    ("阿智村 ヘブンスそのはら付近", 35.456090, 137.633603),
]

VIEWPOINTS_PATH = Path(__file__).parent / "step6_viewpoint_survey" / "viewpoints_kanto.json"


def main() -> None:
    areas = load_areas()

    print("=== 検証済み7地点のエリア判定 ===")
    for name, lat, lon in TEST_SITES:
        matched = find_areas(lat, lon, areas)
        label = "、".join(a.name for a in matched) if matched else "エリア外"
        print(f"  {name:24s}: {label}")

    with open(VIEWPOINTS_PATH, encoding="utf-8") as f:
        viewpoints = json.load(f)

    print(f"\n=== viewpoint {len(viewpoints)}件のエリア別集計 ===")
    counts = {a.id: 0 for a in areas}
    outside = 0
    for v in viewpoints:
        matched = find_areas(v["lat"], v["lon"], areas)
        if not matched:
            outside += 1
        else:
            for a in matched:
                counts[a.id] += 1

    for a in areas:
        print(f"  {a.name:16s}({a.type:8s}): {counts[a.id]:5d}件")
    print(f"  {'エリア外':16s}{'':10s}: {outside:5d}件 ({outside/len(viewpoints)*100:.1f}%)")


if __name__ == "__main__":
    main()
