"""おすすめエリア判定: areas.json(バウンディングボックス方式)による地点->エリア判定。"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

_DEFAULT_PATH = Path(__file__).parent / "areas.json"


@dataclass
class Area:
    id: str
    name: str
    type: str
    lat_min: float
    lat_max: float
    lon_min: float
    lon_max: float

    def contains(self, lat: float, lon: float) -> bool:
        return self.lat_min <= lat <= self.lat_max and self.lon_min <= lon <= self.lon_max


def load_areas(path: str | Path = _DEFAULT_PATH) -> list[Area]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    areas = []
    for a in data["areas"]:
        bbox = a["bbox"]
        areas.append(Area(
            id=a["id"], name=a["name"], type=a["type"],
            lat_min=bbox["lat_min"], lat_max=bbox["lat_max"],
            lon_min=bbox["lon_min"], lon_max=bbox["lon_max"],
        ))
    return areas


def find_areas(lat: float, lon: float, areas: list[Area] | None = None) -> list[Area]:
    """地点が属する全エリアを返す(バウンディングボックスは重なり得るため複数返る場合がある)。"""
    areas = areas or load_areas()
    return [a for a in areas if a.contains(lat, lon)]
