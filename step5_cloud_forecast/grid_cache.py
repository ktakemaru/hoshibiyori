"""格子セル単位でOpen-Meteo APIをキャッシュし、同一セルに属する地点間で結果を使い回す。

MSM(jma_msm)とECMWF(ecmwf_ifs025)は、緯度経度が近い地点でも同じ気象格子点の値を
返すことが多い。実測(Open-Meteoへの複数地点問い合わせで座標がどうスナップされるか
を確認)で判明した格子解像度:
- jma_msm    : 緯度0.05度 × 経度0.0625度刻み
- ecmwf_ifs025: 緯度0.25度 × 経度0.25度刻み(名前の025が示す通り)

このモジュールは、候補地点群を上記の格子に丸めてグループ化し、
同一セルに属する地点はAPI呼び出しを1回だけ行い結果を共有する(プロセス内メモリキャッシュ)。

2026-09-06、これに加えてディスクキャッシュを追加した(generate_report.py実行のたびに
毎回555回規模のAPI呼び出しがゼロから発生していたのを解消するため)。DEM標高タイルや
光害タイルと違い、雲量予報は時々刻々と更新される生きたデータのため、無期限キャッシュは
不適切(古い予報を「予報」として出し続けてしまう)。そのためモデルの実際の更新頻度に
合わせた短めのTTL(MSM=3時間、ECMWF=6時間)を設定し、期限切れのキャッシュは
自動的に無視して再取得する。TTLの根拠:
- JMA MSMは気象庁が3時間ごとに新しい初期時刻で計算を行うため、3時間を超えて
  キャッシュを使い続けると「別の初期時刻の予報」を古いまま返すことになる。
- ECMWF IFSは1日2回(00Z/12Z)の更新のため、6時間程度のキャッシュは実用上
  大きな鮮度低下にならない(見込み用途で細かい時間変化まで問わないため)。
"""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime
from pathlib import Path

from dataclasses import dataclass

from cloud_forecast import ECMWF_MODEL, MSM_MODEL, OpenMeteoDailyLimitError, _fetch_hourly_detailed

GRID_STEP_DEG = {
    MSM_MODEL: {"lat": 0.05, "lon": 0.0625},
    ECMWF_MODEL: {"lat": 0.25, "lon": 0.25},
}

_DEFAULT_CACHE_DIR = Path(__file__).parent / "cloud_cache"

# 取得失敗セル率(失敗セル数÷この実行で要求したユニークセル数)がこの値以上なら、
# レポートを出さずに異常終了(終了コード2)する。未満で1件以上の失敗なら警告付きで出力する。
# 値はユーザー承認済みの暫定値(2026-10-12)で、運用しながら調整してよい。
FAILED_CELL_RATE_ABORT = 0.20

# モデルの実際の更新頻度に合わせたディスクキャッシュの有効期限(秒)。
CACHE_TTL_SEC = {
    MSM_MODEL: 3 * 3600,
    ECMWF_MODEL: 6 * 3600,
}


@dataclass
class FailedCell:
    model: str
    lat: float
    lon: float
    reason: str


@dataclass
class FetchSummary:
    total_cells: int  # この実行で要求したユニークセル数(成功+失敗、キャッシュヒット含む)
    api_calls: int
    cache_hits: int
    failed: int
    rate_limited: bool

    @property
    def failed_rate(self) -> float:
        return self.failed / self.total_cells if self.total_cells else 0.0

    @property
    def status(self) -> str:
        """"ok"(失敗なし) / "partial"(警告付きで出力) / "abort"(出力せず終了コード2)。"""
        if self.rate_limited or (self.failed and self.failed_rate >= FAILED_CELL_RATE_ABORT):
            return "abort"
        return "partial" if self.failed else "ok"

    def console_line(self) -> str:
        return (f"取得セル{self.total_cells}件 / API呼び出し{self.api_calls}回 / "
                f"キャッシュヒット{self.cache_hits}回 / 失敗{self.failed}件({self.failed_rate:.1%})")


def grid_cell(lat: float, lon: float, model: str) -> tuple[float, float]:
    """指定モデルの格子解像度で(lat, lon)を丸め、セルを代表する座標を返す。"""
    step = GRID_STEP_DEG[model]
    cell_lat = round(lat / step["lat"]) * step["lat"]
    cell_lon = round(lon / step["lon"]) * step["lon"]
    return (round(cell_lat, 6), round(cell_lon, 6))


def group_points_by_cell(points: list[dict], model: str) -> dict[tuple[float, float], list[dict]]:
    """points([{'name':..,'lat':..,'lon':..}, ...])を格子セルごとにグループ化する。"""
    groups: dict[tuple[float, float], list[dict]] = {}
    for p in points:
        cell = grid_cell(p["lat"], p["lon"], model)
        groups.setdefault(cell, []).append(p)
    return groups


class GridCloudCache:
    """格子セル単位でAPI呼び出し結果をキャッシュするクラス。

    同じセルへの2回目以降の要求はAPIを再度呼ばず、キャッシュ済みの結果を返す。
    1セルにつき1回のAPI呼び出しで、変数指定した予報日数分(forecast_days)を
    まとめて取得するため、複数夜をまたぐ探索でも呼び出し回数は増えない。

    プロセス内メモリキャッシュに加えて、モデルごとのTTL(CACHE_TTL_SEC)付きの
    ディスクキャッシュを持つ。同じプロセス実行内ではメモリキャッシュがヒットし、
    別プロセス(再実行)でもTTL以内であればディスクキャッシュがヒットしてAPI呼び出しを
    省略できる。TTLはモデルの実際の更新頻度に基づく値で、鮮度が問題にならない範囲に
    限定している(詳細はモジュールdocstring参照)。
    """

    def __init__(self, cache_dir: str | Path = _DEFAULT_CACHE_DIR, disk_cache: bool = True):
        self._cache: dict[tuple[str, tuple[float, float], int], dict] = {}
        self.call_count = 0
        self.cache_hit_count = 0
        self.disk_hit_count = 0
        self.failures: list[FailedCell] = []
        self.rate_limited = False
        self.disk_cache_enabled = disk_cache
        self.cache_dir = Path(cache_dir)
        if self.disk_cache_enabled:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _disk_path(self, key: tuple) -> Path:
        digest = hashlib.sha1(json.dumps(key, ensure_ascii=False).encode("utf-8")).hexdigest()
        return self.cache_dir / f"{digest}.json"

    def _read_disk(self, key: tuple, model: str) -> dict | None:
        path = self._disk_path(key)
        if not path.exists():
            return None
        age_sec = time.time() - path.stat().st_mtime
        if age_sec > CACHE_TTL_SEC[model]:
            return None  # 期限切れ。呼び出し元でAPI再取得させる(ファイルは上書きされる)
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return None

    def _write_disk(self, key: tuple, hourly: dict | None) -> None:
        if hourly is None:
            return  # 取得失敗は永続化しない(次回また再試行できるように)
        path = self._disk_path(key)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(hourly, f, ensure_ascii=False)

    def get_hourly(self, lat: float, lon: float, model: str, forecast_days: int, variables: str) -> dict[str, list] | None:
        """指定セルの時系列データを返す。取得に失敗した場合はNone(呼び出し元で欠測として扱う)。"""
        cell = grid_cell(lat, lon, model)
        key = (model, cell, forecast_days, variables)
        if key in self._cache:
            self.cache_hit_count += 1
            return self._cache[key]

        if self.disk_cache_enabled:
            cached = self._read_disk(key, model)
            if cached is not None:
                self._cache[key] = cached
                self.disk_hit_count += 1
                self.cache_hit_count += 1
                return cached

        cell_lat, cell_lon = cell
        outcome = _fetch_hourly_detailed(cell_lat, cell_lon, model, forecast_days, variables=variables)
        hourly = outcome.hourly
        self._cache[key] = hourly
        self.call_count += 1
        if hourly is None:
            self.failures.append(FailedCell(model, cell_lat, cell_lon, outcome.reason or "unknown"))
            if outcome.rate_limited:
                self.rate_limited = True
                raise OpenMeteoDailyLimitError(
                    "Open-Meteoが429(利用上限)を返したため、以降の取得を中止します")
        if self.disk_cache_enabled:
            self._write_disk(key, hourly)
        return hourly

    def summary(self) -> FetchSummary:
        return FetchSummary(
            total_cells=len(self._cache), api_calls=self.call_count,
            cache_hits=self.cache_hit_count, failed=len(self.failures),
            rate_limited=self.rate_limited,
        )
