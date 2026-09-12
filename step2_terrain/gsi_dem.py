"""国土地理院「標高タイル」(cyberjapandata.gsi.go.jp)からのDEM取得。

- ログイン・APIキー不要の公開タイル配信を使用する。
- 出典表示が必須(国土地理院コンテンツ利用規約): 成果物には
  「出典:国土地理院」等の表示を行うこと。
- 無償公開されている公共インフラであるため、同一タイルへの重複アクセスを
  避けるようディスクキャッシュを必須とし、常識的な範囲のアクセス頻度に
  留めること(本モジュールは既定でディスクキャッシュ+緩やかな並列数を用いる)。

タイル仕様(標高タイルtxt形式): 256x256セルのCSVテキスト。1セル1行では
なく、1行が256個のカンマ区切り値(欠測は "e")。
"""
from __future__ import annotations

import math
import time
from pathlib import Path

import numpy as np
import requests

ATTRIBUTION = "出典: 国土地理院 (地理院タイル 標高タイル, cyberjapandata.gsi.go.jp)"

# データセット名 -> (URLテンプレート, 推奨ズームレベル)
DATASETS: dict[str, tuple[str, int]] = {
    "dem5a": ("https://cyberjapandata.gsi.go.jp/xyz/dem5a/{z}/{x}/{y}.txt", 15),  # 5mメッシュ(航空レーザ、都市部等のみ)
    "dem5b": ("https://cyberjapandata.gsi.go.jp/xyz/dem5b/{z}/{x}/{y}.txt", 15),  # 5mメッシュ(写真測量)
    "dem": ("https://cyberjapandata.gsi.go.jp/xyz/dem/{z}/{x}/{y}.txt", 14),      # 10mメッシュ(全国、既定)
}

_USER_AGENT = "hoshibiyori-terrain-horizon/0.1 (personal astrophotography tool; script-based, low-volume, cached)"
_REQUEST_TIMEOUT_SEC = 15
_POLITE_DELAY_SEC = 0.05  # 新規タイル取得ごとの小休止


def deg2tile_frac(lat_deg: float, lon_deg: float, zoom: int) -> tuple[float, float]:
    """緯度経度を(スリッピータイル規約での)小数タイル座標に変換する。"""
    lat_rad = math.radians(lat_deg)
    n = 2.0 ** zoom
    x = (lon_deg + 180.0) / 360.0 * n
    y = (1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * n
    return x, y


def tile_key(dataset: str, zoom: int, xtile: int, ytile: int) -> tuple[str, int, int, int]:
    return (dataset, zoom, xtile, ytile)


class DemTileStore:
    """DEMタイルのディスク+メモリキャッシュ、および取得を担当する。"""

    def __init__(self, cache_dir: str | Path, dataset: str = "dem", session: requests.Session | None = None):
        if dataset not in DATASETS:
            raise ValueError(f"未知のデータセット: {dataset}")
        self.dataset = dataset
        self.url_template, self.zoom = DATASETS[dataset]
        self.cache_dir = Path(cache_dir) / dataset
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": _USER_AGENT})
        self._mem_cache: dict[tuple[int, int], np.ndarray] = {}
        self.downloaded_count = 0
        self.cache_hit_count = 0
        self.failed_count = 0

    def _disk_path(self, xtile: int, ytile: int) -> Path:
        return self.cache_dir / f"{self.zoom}_{xtile}_{ytile}.npy"

    def _parse_txt(self, text: str) -> np.ndarray:
        rows = []
        for line in text.strip("\n").split("\n"):
            values = [np.nan if v.strip() in ("e", "E", "") else float(v) for v in line.split(",")]
            rows.append(values)
        arr = np.array(rows, dtype=np.float64)
        if arr.shape != (256, 256):
            padded = np.full((256, 256), np.nan, dtype=np.float64)
            padded[: arr.shape[0], : arr.shape[1]] = arr
            arr = padded
        return arr

    def get_tile(self, xtile: int, ytile: int) -> np.ndarray | None:
        """256x256のNumPy配列(欠測はNaN)を返す。取得完全失敗時はNoneを返す。"""
        mem_key = (xtile, ytile)
        if mem_key in self._mem_cache:
            return self._mem_cache[mem_key]

        disk_path = self._disk_path(xtile, ytile)
        if disk_path.exists():
            arr = np.load(disk_path)
            self._mem_cache[mem_key] = arr
            self.cache_hit_count += 1
            return arr

        url = self.url_template.format(z=self.zoom, x=xtile, y=ytile)
        try:
            resp = self.session.get(url, timeout=_REQUEST_TIMEOUT_SEC)
        except requests.RequestException:
            self.failed_count += 1
            return None

        if resp.status_code == 404:
            # タイル範囲外(データ提供なし)。全欠測として扱いキャッシュする。
            arr = np.full((256, 256), np.nan, dtype=np.float64)
        elif resp.status_code == 200:
            arr = self._parse_txt(resp.text)
        else:
            self.failed_count += 1
            return None

        np.save(disk_path, arr)
        self._mem_cache[mem_key] = arr
        self.downloaded_count += 1
        time.sleep(_POLITE_DELAY_SEC)
        return arr

    def get_elevation(self, lat_deg: float, lon_deg: float) -> float | None:
        """指定地点の標高(m)を返す。海上等でデータが無い場合は0.0(海面)を返す。

        タイル取得そのものが失敗した場合(通信エラー)はNoneを返す。
        """
        x_frac, y_frac = deg2tile_frac(lat_deg, lon_deg, self.zoom)
        xtile = int(math.floor(x_frac))
        ytile = int(math.floor(y_frac))
        tile = self.get_tile(xtile, ytile)
        if tile is None:
            return None
        px = min(int((x_frac - xtile) * 256), 255)
        py = min(int((y_frac - ytile) * 256), 255)
        val = tile[py, px]
        if np.isnan(val):
            return 0.0  # 地理院標高タイルは陸域のみのため、欠測=海面と仮定
        return float(val)
