"""星の日和(hoshibiyori) ステップ6: 展望地点データ(OpenStreetMap)網羅性の検証。

Overpass API (https://overpass-api.de/api/interpreter、認証不要)を使い、
関東地方のバウンディングボックス内で tourism=viewpoint タグが付いたノードを取得する。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import requests

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# 関東地方のバウンディングボックス(南, 西, 北, 東)
# 西端は当初138.5だったが、これだと八ヶ岳山域(経度138.20〜138.50)がほぼ範囲外になり
# viewpoint件数が不自然に0件になる欠落が発覚したため、138.0まで西に拡張した
# (山梨・長野県境の八ヶ岳西麓側まで含める)。
BBOX = (34.5, 138.0, 37.0, 141.0)


@dataclass
class Viewpoint:
    id: int
    lat: float
    lon: float
    name: str | None
    ele: str | None
    description: str | None


def build_query(bbox: tuple[float, float, float, float]) -> str:
    south, west, north, east = bbox
    return f"""
[out:json][timeout:60];
node["tourism"="viewpoint"]({south},{west},{north},{east});
out body;
""".strip()


def fetch_viewpoints(bbox: tuple[float, float, float, float] = BBOX) -> list[Viewpoint]:
    query = build_query(bbox)
    resp = requests.post(
        OVERPASS_URL,
        data={"data": query},
        timeout=90,
        headers={"User-Agent": "hoshibiyori-research/0.1 (personal astrophotography tool; low-volume)"},
    )
    resp.raise_for_status()
    data = resp.json()

    viewpoints = []
    for e in data["elements"]:
        tags = e.get("tags", {})
        viewpoints.append(Viewpoint(
            id=e["id"], lat=e["lat"], lon=e["lon"],
            name=tags.get("name"), ele=tags.get("ele"), description=tags.get("description"),
        ))
    return viewpoints


def save_viewpoints_json(viewpoints: list[Viewpoint], path: str | Path) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump([vars(v) for v in viewpoints], f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    vps = fetch_viewpoints()
    print(f"取得件数: {len(vps)}")
    save_viewpoints_json(vps, "viewpoints_kanto.json")
    print("viewpoints_kanto.json に保存しました。")
