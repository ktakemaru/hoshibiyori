"""撮影対象カタログ(targets.json)の読み込み。"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

_DEFAULT_PATH = Path(__file__).parent / "targets.json"


@dataclass
class Target:
    id: str
    name: str
    name_en: str
    ra_hours: float
    dec_deg: float
    best_season: str
    best_months: list[int]
    # 見どころ用(2026-11-24。sky_highlights.py)。無い対象は既定値
    kind: str = ""               # 星 / 星団 / 星雲 / 銀河 / 星の並び
    group: str = ""              # まとめて出す組(星座・星の並び)。空なら単独
    first_magnitude: bool = False
    source: str = ""             # 座標の出どころ(空は従来からの対象)


def load_targets(path: str | Path = _DEFAULT_PATH) -> list[Target]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return [Target(**t) for t in data["targets"]]


def get_target(target_id: str, path: str | Path = _DEFAULT_PATH) -> Target:
    for t in load_targets(path):
        if t.id == target_id:
            return t
    raise KeyError(f"カタログに対象が見つかりません: {target_id}")
