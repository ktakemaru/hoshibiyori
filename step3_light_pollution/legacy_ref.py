"""比較・検証用に、legacy(Lorenz氏のLight Pollution Atlas由来)のLPIを光害タイルから計算する(段階LP3)。

段階LP3で `stargazing_spots.json` から事前計算の lpi を外したため、legacy と突き合わせる解析スクリプト
(bm_threshold.py・bm_disagreements.py・validate_skyglow_bm.py・analyze_*.py)は、ここで都度計算する。
タイルは `step3_light_pollution/tile_cache/`(git管理外)にあればそれを使い、無ければ光害タイルを取得する
(通信あり。GitHub Pages配信、取得は逐次・キャッシュ、識別可能なUser-Agent。light_pollution.py のとおり)。
結果は表示・比較にだけ使い、ファイルへは書き戻さない。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from light_pollution import LightPollutionTileStore

HERE = Path(__file__).resolve().parent
LPI_THRESHOLD_LEGACY = 5.0  # explore_hoshibiyori.LPI_THRESHOLD と同じ(単体テストで突き合わせる)


def legacy_lpi(spots: list[dict], year: int = 2025) -> np.ndarray:
    store = LightPollutionTileStore(cache_dir=str(HERE / "tile_cache"), year=year)
    return np.array([store.get(s["lat"], s["lon"]).brightness_ratio for s in spots], float)
