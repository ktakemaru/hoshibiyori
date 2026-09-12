"""星の日和(hoshibiyori) ステップ3: 光害データ取得の検証。

データ出典: David Lorenz "Light Pollution Atlas" (https://djlorenz.github.io/astronomy/lp/)
  - Cinzano/Falchiの手法をベースに、NOAA/EOGのVIIRS夜間光データ(最新年)を用いて
    著者(David Lorenz)が独自に再計算した人工夜空光害(天頂方向)の全球データ。
  - 当初依頼のあった Falchi et al. 2016 "World Atlas of Artificial Night Sky
    Brightness" 原本データは、GFZ Potsdam Data Servicesが著者への利用申請フォーム
    経由でのみ配布しており(一般公開ダウンロード不可)、NOAA/EOGのVIIRS年次コンポジット
    も現在はアカウント認証必須のため、いずれも「認証不要で直接取得」の条件を満たさない。
    本モジュールはその代替として、認証不要でアクセスできる本データソースを使用する。
  - データ取得元URL: サイトの地図(overlay/dark.html)がクリック時に読み込む生バイナリタイル
    https://djlorenz.github.io/astronomy/binary_tiles/{year}/binary_tile_{tilex}_{tiley}.dat.gz
    (認証・APIキー不要。GitHub Pages配信。robots.txt等によるアクセス制限の記載も無し)
  - ★ライセンス・利用条件について: サイト内に明示的なライセンス表記(CCライセンス等)や
    「Used with permission」等の記載は見つからなかった。著者(David Lorenz,
    dlorenz@wisc.edu)による利用規約の明文化はなく、地図上でのクリックによる
    ポイント参照(本モジュールが再現している機能そのもの)は公開機能として提供されている。
    個人・非商用の検証目的での本モジュールのような低頻度アクセスは問題ないと考えられるが、
    一般公開するサービスに組み込む場合は、事前に著者へ利用可否を確認することを推奨する。
    (詳細は CLAUDE.md の「光害データ取得に関する注意」を参照)

ボートルスケール変換について:
  - サイト作成者(David Lorenz)自身が bortle.html で「天頂輝度とボートルスケールを
    安易に対応させるべきではない」と明言しており(実測データでも同じ天頂輝度が
    複数のボートルクラスにまたがることを示している)、本モジュールの変換は
    あくまで簡易的な目安であり、公式・厳密な換算ではない。
  - 変換テーブルは、一般に流布している「ボートルスケール<->等級/平方秒角(mag/arcsec^2)」
    の対応表を、本データの mpsas 変換式で明るさ比(LPI)に変換した値を用いている。
    この値は本データソースの LP Zone 境界(0.01, 0.11, 0.33, 0.58, 1.00, 1.73, 3.00,
    5.20, 9.00, 15.59, 27.00, 46.77)とほぼ一致しており、one-offの主観値ではない。
"""
from __future__ import annotations

import gzip
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import requests

ATTRIBUTION = "出典: David Lorenz, Light Pollution Atlas (https://djlorenz.github.io/astronomy/lp/)"

_TILE_URL_TEMPLATE = "https://djlorenz.github.io/astronomy/binary_tiles/{year}/binary_tile_{tilex}_{tiley}.dat.gz"
_TILE_GRID_SIZE = 600  # 1タイル=5度四方、1/120度(600x600点)格子
_USER_AGENT = "hoshibiyori-terrain-horizon/0.1 (personal astrophotography tool; low-volume, cached)"
_REQUEST_TIMEOUT_SEC = 20

# 簡易 Bortleスケール対応表(上限値, 明るさ比LPIのこの値未満ならそのクラス)
# 一般的なBortle<->mag/arcsec^2対応表をLPIに換算した値。本データのLPI Zone境界と概ね一致。
_BORTLE_THRESHOLDS = [
    (0.01, 1),
    (0.11, 2),
    (0.33, 3),
    (0.58, 4),
    (3.00, 5),
    (9.00, 6),
    (15.59, 7),
    (27.00, 8),
]
_BORTLE_MAX_CLASS = 9  # 上記いずれにも該当しない(27.00以上)場合


@dataclass
class LightPollutionResult:
    lat: float
    lon: float
    year: int
    brightness_ratio: float  # LPI: 人工天頂輝度 / 自然天頂輝度 の比
    mpsas: float  # 等級/平方秒角(概算)
    bortle_approx: int  # 簡易近似ボートルクラス(1-9)


def _latlon_to_tile_and_index(lat: float, lon: float) -> tuple[int, int, int, int]:
    """緯度経度から(tilex, tiley, ix, iy)を計算する。ix,iyは1始まりのタイル内格子インデックス。"""
    lon_from_dateline = (lon + 180.0) % 360.0
    lat_from_start = lat + 65.0
    if not (0.0 <= lat_from_start <= 140.0):
        raise ValueError(f"緯度{lat}はこのデータの範囲外です(65S〜75N)")

    tilex = int(lon_from_dateline // 5.0) + 1
    tiley = int(lat_from_start // 5.0) + 1
    tiley = min(max(tiley, 1), 28)

    ix = round(120.0 * (lon_from_dateline - 5.0 * (tilex - 1) + 1.0 / 240.0))
    iy = round(120.0 * (lat_from_start - 5.0 * (tiley - 1) + 1.0 / 240.0))
    ix = min(max(ix, 1), _TILE_GRID_SIZE)
    iy = min(max(iy, 1), _TILE_GRID_SIZE)
    return tilex, tiley, ix, iy


class LightPollutionTileStore:
    """光害タイル(gzip圧縮バイナリ)のディスク+メモリキャッシュと取得を担当する。"""

    def __init__(self, cache_dir: str | Path, year: int = 2025, session: requests.Session | None = None):
        self.year = year
        self.cache_dir = Path(cache_dir) / str(year)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": _USER_AGENT})
        self._mem_cache: dict[tuple[int, int], np.ndarray] = {}

    def _disk_path(self, tilex: int, tiley: int) -> Path:
        return self.cache_dir / f"tile_{tilex}_{tiley}.npy"

    def _get_tile_bytes(self, tilex: int, tiley: int) -> np.ndarray:
        mem_key = (tilex, tiley)
        if mem_key in self._mem_cache:
            return self._mem_cache[mem_key]

        disk_path = self._disk_path(tilex, tiley)
        if disk_path.exists():
            arr = np.load(disk_path)
            self._mem_cache[mem_key] = arr
            return arr

        url = _TILE_URL_TEMPLATE.format(year=self.year, tilex=tilex, tiley=tiley)
        resp = self.session.get(url, timeout=_REQUEST_TIMEOUT_SEC)
        resp.raise_for_status()
        raw = gzip.decompress(resp.content)
        arr = np.frombuffer(raw, dtype=np.int8)

        np.save(disk_path, arr)
        self._mem_cache[mem_key] = arr
        return arr

    def _compressed_value(self, data: np.ndarray, ix: int, iy: int) -> int:
        """タイル内格子点(ix,iy)(1始まり)の圧縮済み輝度値を復元する。

        エンコード方式: 左下角のみ2バイト(base-128)の絶対値、以降は1バイトの
        差分値の累積和で再構築する(djlorenz Light Pollution Atlasのタイル
        クリック処理JSをそのまま踏襲)。
        """
        first_number = 128 * int(data[0]) + int(data[1])
        change = 0
        for i in range(1, iy):
            change += int(data[_TILE_GRID_SIZE * i + 1])
        for i in range(1, ix):
            change += int(data[_TILE_GRID_SIZE * (iy - 1) + 1 + i])
        return first_number + change

    def get(self, lat: float, lon: float) -> LightPollutionResult:
        tilex, tiley, ix, iy = _latlon_to_tile_and_index(lat, lon)
        data = self._get_tile_bytes(tilex, tiley)
        compressed = self._compressed_value(data, ix, iy)

        brightness_ratio = (5.0 / 195.0) * (math.exp(0.0195 * compressed) - 1.0)
        mpsas = 22.0 - 5.0 * math.log(1.0 + brightness_ratio) / math.log(100.0)
        bortle = bortle_from_ratio(brightness_ratio)

        return LightPollutionResult(
            lat=lat, lon=lon, year=self.year,
            brightness_ratio=brightness_ratio, mpsas=mpsas, bortle_approx=bortle,
        )


def bortle_from_ratio(brightness_ratio: float) -> int:
    """人工天頂輝度比(LPI)から簡易近似のボートルクラス(1-9)を返す。

    注意: これは厳密な変換ではない。データ提供元(David Lorenz)自身が、
    天頂輝度とボートルスケールを単純に対応させることに警鐘を鳴らしており
    (例: 黄色ゾーン=通説ではBortle4だが実際はBortle5であることが多い)、
    ここでの変換もあくまで大まかな目安として扱うこと。
    """
    for threshold, bortle_class in _BORTLE_THRESHOLDS:
        if brightness_ratio < threshold:
            return bortle_class
    return _BORTLE_MAX_CLASS
