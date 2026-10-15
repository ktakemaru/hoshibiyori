"""数値JSON(hoshibiyori-skyguide-data/1)を既存ロジックで組み立てる。

既定では通信しない: 雲量はディスクキャッシュのみ、稜線は stargazing_spots.json の horizon_profile(CSV)のみ。
通信が要る経路(allow_network=True)は呼び出し側が承認を得てから使う。
"""
from __future__ import annotations

import csv
import json
import math
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import astro
from .render import DATA_SCHEMA, SkyGuideError

ROOT = astro.ROOT
for _sub in ("step2_terrain", "step3_light_pollution", "step5_cloud_forecast"):
    if str(ROOT / _sub) not in sys.path:
        sys.path.insert(0, str(ROOT / _sub))

JST = astro.JST
SPOTS_PATH = ROOT / "stargazing_spots.json"
STEP_MIN = 20

ATTRIBUTION = ("天体位置はSkyfield(JPL DE421)で計算。雲量はOpen-Meteo経由の気象庁MSM・ECMWF IFS(CC BY 4.0)、"
               "地形は国土地理院の標高タイルを加工して作成、光害は David Lorenz 氏の Light Pollution Atlas によります。")
DISCLAIMER = ("雲量は予報値で、当日の空を保証するものではありません。山名と構図の位置関係は、現地での確認を前提にしてください。")


def load_spot(key: str) -> dict:
    spots = json.loads(SPOTS_PATH.read_text(encoding="utf-8"))["spots"]
    hits = [s for s in spots if s["id"] == key or s["name"] == key]
    if not hits:
        raise SkyGuideError(f"stargazing_spots.json に地点がありません: {key}(一覧にない地点は --name --lat --lon --elevation)")
    if len(hits) > 1:
        raise SkyGuideError(f"地点名が複数あります。id で指定してください: {[h['id'] for h in hits]}")
    return hits[0]


def read_horizon_csv(path: Path) -> list[float]:
    with path.open(encoding="utf-8") as f:
        rows = [r for r in csv.reader(f) if r and not r[0].startswith("#")][1:]
    hz = [round(float(r[1]), 1) for r in rows]
    if len(hz) != 360:
        raise SkyGuideError(f"稜線CSVが360行ではありません: {path}")
    return hz


def floor_to_step(dt: datetime, step: int) -> datetime:
    dt = dt.replace(second=0, microsecond=0)
    return dt - timedelta(minutes=dt.minute % step)


def ceil_to_step(dt: datetime, step: int) -> datetime:
    f = floor_to_step(dt, step)
    return f if f == dt.replace(second=0, microsecond=0) and dt.second == 0 else f + timedelta(minutes=step)


class CacheOnlyCloudCache:
    """通信しない雲量キャッシュ。GridCloudCache のディスクキャッシュ(TTL内)だけを読む。無ければNone(欠測)。

    キー・有効期限・読み取りは既存の GridCloudCache._read_disk をそのまま使う(既存クラスは変更しない)。
    キャッシュ先のディレクトリが無いときも作らず、「キャッシュなし」として扱う(書き込みは一切しない)。
    """

    def __init__(self, cache_dir: str | Path | None = None):
        from grid_cache import _DEFAULT_CACHE_DIR, GridCloudCache
        # コンストラクタは cache_dir を mkdir するので通さず、読み取りに必要な属性だけを持たせる
        self._inner = GridCloudCache.__new__(GridCloudCache)
        self._inner.cache_dir = Path(cache_dir) if cache_dir is not None else Path(_DEFAULT_CACHE_DIR)
        self._inner.disk_cache_enabled = True
        self.missing: list[tuple[str, float, float]] = []

    def get_hourly(self, lat, lon, model, forecast_days, variables):
        from grid_cache import grid_cell
        key = (model, grid_cell(lat, lon, model), forecast_days, variables)
        cached = self._inner._read_disk(key, model)
        if cached is None:
            self.missing.append((model, *grid_cell(lat, lon, model)))
        return cached


def cloud_cells_needed(lat: float, lon: float) -> list[tuple[str, tuple[float, float]]]:
    from cloud_forecast import ECMWF_MODEL, MSM_MODEL
    from grid_cache import grid_cell
    return [(m, grid_cell(lat, lon, m)) for m in (MSM_MODEL, ECMWF_MODEL)]


def cloud_by_hour(lat, lon, elev, name, dark_start: datetime, dark_end: datetime, cache) -> tuple[dict | None, str | None]:
    """夜の各時(開始の時〜終了の次の時)の視界遮蔽雲量。取れなければ (None, 理由)。"""
    from elevation_cloud import get_level_cloud_forecast, hourly_sky_obstruction_and_cloud_sea
    start = dark_start.replace(minute=0, second=0, microsecond=0)
    end = dark_end.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    levels = get_level_cloud_forecast(lat, lon, start, end, cache=cache)
    rows = hourly_sky_obstruction_and_cloud_sea(levels, elev)
    hours = [{"h": f"{r['dt_local'].hour:02d}", "pct": int(round(r["sky_obstruction"]))} for r in rows if r["sky_obstruction"] is not None]
    if len(hours) < len(rows):
        return None, ("この夜の予報(Open-Meteoの気象庁MSM・ECMWF)が取得できない時刻があります。過去の日付、または予報範囲外"
                      "(約2週間より先)、あるいはキャッシュ切れ(通信しない設定)の可能性があります")
    sources = {r["source"] for r in rows}
    return {"label": f"視界遮蔽雲量 %({'・'.join(sorted(sources))}、{name}の標高で補正)", "source": sorted(sources), "hours": hours}, None


def build_data(*, spot: dict, night_date: date, allow_network: bool = False, cloud_mode: str = "cache") -> dict:
    """spot: {name, prefecture?, municipality?, lat, lon, elevation_m, lpi?, mpsas?, horizon_profile?, coordinate_source?}"""
    from skyfield.api import load
    import explore_hoshibiyori as ex

    if not astro.EPHEMERIS_PATH.exists() and not allow_network:
        raise SkyGuideError("暦ファイル step1_astronomy/de421.bsp がありません(初回は自動ダウンロード=通信が必要)。--allow-network を付けるか、先に用意してください")
    lat, lon, elev = spot["lat"], spot["lon"], spot["elevation_m"]
    ts = load.timescale()
    eph = load(str(astro.EPHEMERIS_PATH))
    ds, de = ex.find_astro_dark_events(ts, eph, lat, lon, datetime(night_date.year, night_date.month, night_date.day, tzinfo=JST))
    if ds is None or de is None:
        raise SkyGuideError("この日付・地点には天文薄明終了〜開始の暗い時間帯がありません")
    t0, t1 = floor_to_step(ds, STEP_MIN), ceil_to_step(de, STEP_MIN)
    count = int((t1 - t0).total_seconds() // 60 // STEP_MIN) + 1
    times = astro.time_grid(t0, STEP_MIN, count)

    hp = spot.get("horizon_profile")
    if hp and (ROOT / hp).exists():
        horizon, hsrc = read_horizon_csv(ROOT / hp), hp
    else:
        raise SkyGuideError("この地点の稜線データ(horizon_profile CSV)がありません。step2_terrain/precompute_terrain.py か horizon_profile.py で"
                            "作ります(国土地理院のDEMタイルの取得=通信が要ります。--estimate で見込みを確認)")

    frames = astro.compute_frames(ts, eph, lat, lon, elev, times)
    events = astro.compute_events(ts, eph, lat, lon, elev, ds, de, horizon)

    cloud, reason = None, None
    if cloud_mode == "off":
        reason = "雲量の取得を指定されなかったため(--cloud off)"
    else:
        if cloud_mode == "cache":
            cache = CacheOnlyCloudCache()
        elif allow_network:
            from grid_cache import GridCloudCache
            cache = GridCloudCache()
        else:
            raise SkyGuideError("--cloud fetch は通信を伴うため --allow-network が必要です")
        cloud, reason = cloud_by_hour(lat, lon, elev, spot["name"], ds, de, cache)

    return {
        "schema": DATA_SCHEMA, "generated_at": datetime.now(JST).isoformat(timespec="seconds"),
        "spot": {"name": spot["name"], "prefecture": spot.get("prefecture"), "municipality": spot.get("municipality"),
                 "lat": lat, "lon": lon, "elevation_m": elev, "lpi": spot.get("lpi"), "mpsas": spot.get("mpsas"),
                 "coordinate_source": spot.get("coordinate_source", "ユーザー指定"),
                 "elevation_source": spot.get("elevation_source", "stargazing_spots.json(国土地理院DEM)")},
        "night": {"date": night_date.isoformat(), "dark_start": ds.strftime("%H:%M"), "dark_end": de.strftime("%H:%M"),
                  "dark_hours": round((de - ds).total_seconds() / 3600, 1)},
        "times": [t.strftime("%H:%M") for t in times], "frames": frames, "starmag": astro.starmag(),
        "horizon_deg": horizon, "horizon_source": hsrc,
        "cloud": cloud, "cloud_omitted_reason": reason,
        "peak_candidates": astro.detect_ridge_peaks(horizon), "events": events,
        "attribution": [ATTRIBUTION], "disclaimer": [DISCLAIMER],
    }


def estimate_requests(spot: dict) -> dict:
    """通信が必要になる見込み(実行しない)。雲量セルは未キャッシュ分、DEMは稜線CSVが無い場合のみ。"""
    lat, lon = spot["lat"], spot["lon"]
    from grid_cache import CACHE_TTL_SEC, GridCloudCache
    from elevation_cloud import level_hourly_vars
    from cloud_forecast import ECMWF_MAX_FORECAST_DAYS, ECMWF_MODEL, MSM_MAX_FORECAST_DAYS, MSM_MODEL
    g = GridCloudCache(disk_cache=True)
    days = {MSM_MODEL: MSM_MAX_FORECAST_DAYS, ECMWF_MODEL: ECMWF_MAX_FORECAST_DAYS}
    uncached = []
    for model, cell in cloud_cells_needed(lat, lon):
        key = (model, cell, days[model], level_hourly_vars())
        if g._read_disk(key, model) is None:
            uncached.append(f"{model} セル{cell}")
    out = {"cloud_cells_total": 2, "cloud_cells_uncached": uncached, "cloud_api_calls": len(uncached)}
    hp = spot.get("horizon_profile")
    out["horizon_csv"] = bool(hp and (ROOT / hp).exists())
    return out
