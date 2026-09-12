"""エリア代表点による粗い事前スクリーニング。

各エリアにつき代表点を1つ設定し、その代表点の時間別雲量から
「そのエリア・その夜に視界遮蔽雲量が閾値を下回る時間帯が1回でもあるか」を判定する。
これにより、明らかに全域が悪天候のエリア×夜の組み合わせについては、
そのエリアに属する候補地点の詳細計算(地点ごとのAPI呼び出し)を丸ごとスキップできる。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from elevation_cloud import get_level_cloud_forecast, hourly_sky_obstruction_and_cloud_sea
from grid_cache import GridCloudCache

ROOT = Path(__file__).parent.parent

# エリアの代表点(名前, 緯度, 経度, 代表標高m)。既存7地点があるエリアはそれを流用。
AREA_REPRESENTATIVE_POINTS = {
    "yatsugatake": ("八ヶ岳南麓天文台", 35.882707, 138.36435, 1060.0),
    "fuji_goko": ("富士山頂", 35.3606, 138.7274, 3776.0),
    "nikko": ("中禅寺湖(代表点)", 36.7397, 139.4839, 1270.0),
    "oku_tama_chichibu": ("雲取山周辺(代表点)", 35.8547, 138.9364, 2017.0),
    "izu_peninsula": ("石廊崎", 34.602778, 138.845278, 60.0),
    "boso_peninsula": ("いすみ鉄道踏切", 35.282583, 140.297250, 17.57),
    "miura_peninsula": ("城ヶ島(代表点)", 35.135, 139.616, 30.0),
}

CLOUD_THRESHOLD = 30.0


def prescreen_area_night(cache: GridCloudCache, lat: float, lon: float, elevation_m: float,
                          window_start: datetime, window_end: datetime, threshold: float = CLOUD_THRESHOLD) -> bool:
    """代表点の窓内に、視界遮蔽雲量が閾値を下回る時間帯が1回でもあればTrue。

    取得・結合・合成はelevation_cloud.pyの共通関数に委ねる(2026-09-13変更。従来は本関数が
    APIレスポンスの解釈と標準大気高度による合成を独自に再実装しており、elevation_cloud.py側の
    ジオポテンシャル高度対応・面ごとの欠損許容などの改善が反映されない状態だった)。
    要求変数もelevation_cloud.pyと同一になるため、格子セルキャッシュのキーも共有される
    (同じセルに対して事前スクリーニングと本計算で二重にAPIを呼ばない)。
    forecast_daysは夜ごとに変えず常に最大値で固定する(get_level_cloud_forecast側の仕様)。
    """
    levels = get_level_cloud_forecast(lat, lon, window_start, window_end, cache=cache)
    rows = hourly_sky_obstruction_and_cloud_sea(levels, elevation_m)
    for r in rows:
        v = r["sky_obstruction"]
        if v is not None and v < threshold:
            return True
    return False
