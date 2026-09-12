"""星の日和(hoshibiyori) ステップ5: 雲量予報取得の検証。

Open-Meteo API (https://open-meteo.com/) を用いて、指定地点・時間範囲の雲量予報を
取得する。姉妹プロジェクトyamabiyoriが採用している「直近は高解像度のJMA MSM、
それ以降は広域・長期のECMWFを使う」という使い分けの考え方を踏襲するが、
コードはhoshibiyori独自に実装したものである(2026-09-13にユーザー承認のもとyamabiyori側を
読み取り専用で参照し設計知見を取り込んだが、コードのコピーはしていない。詳細はCLAUDE.md)。
なお、本モジュールの全層/下層/中層/上層雲量(cloudcover系)は単発利用向けで、探索パイプラインは
elevation_cloud.py側が同じ変数を気圧面データと一括取得して使う(2026-09-13の見上げ型ハイブリッド化)。

- JMA MSM (jma_msm): 気象庁メソスケールモデル。日本周辺を高解像度(~5km格子)で
  カバーするが、予報期間は短い(実際には起点から約78時間程度まで)。
- ECMWF IFS (ecmwf_ifs025): 欧州中期予報センターのモデル。解像度は粗い(0.25度、
  約25km格子)が、予報期間が長い(10日以上)。

登山用途(yamabiyori、主に早朝〜昼の行動時間帯)とは異なり、天体撮影用途では
夜間、特に日付をまたぐ時間帯(例: 23時〜翌1時)の雲量が重要になる点に注意する。
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import requests

JST = timezone(timedelta(hours=9))

_OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
_HOURLY_VARS = "cloudcover,cloudcover_low,cloudcover_mid,cloudcover_high"

MSM_MODEL = "jma_msm"
ECMWF_MODEL = "ecmwf_ifs025"
MSM_MAX_FORECAST_DAYS = 4  # MSMの実質的な予報期間(約78時間)をカバーするための要求日数
ECMWF_MAX_FORECAST_DAYS = 15  # Open-Meteoで指定可能なECMWFの最大予報日数


@dataclass
class HourlyCloud:
    dt_local: datetime  # JST
    cloud_total: float | None
    cloud_low: float | None
    cloud_mid: float | None
    cloud_high: float | None
    source: str  # "MSM" または "ECMWF"


_FETCH_MAX_RETRIES = 3
_FETCH_RETRY_BACKOFF_SEC = 2.0


def _fetch_hourly(lat: float, lon: float, model: str, forecast_days: int, variables: str = _HOURLY_VARS) -> dict[str, list] | None:
    """Open-Meteoを呼び出す。761件規模のバッチ処理では一時的な接続エラーが起こり得るため、
    短い間隔で数回リトライする。それでも失敗した場合はNoneを返し(例外は投げない)、
    呼び出し元(GridCloudCache)がそのセルをスキップできるようにする。
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": variables,
        "models": model,
        "forecast_days": forecast_days,
        "timezone": "Asia/Tokyo",
    }
    for attempt in range(1, _FETCH_MAX_RETRIES + 1):
        try:
            resp = requests.get(_OPEN_METEO_URL, params=params, timeout=20)
            resp.raise_for_status()
            return resp.json()["hourly"]
        except requests.RequestException as e:
            if attempt == _FETCH_MAX_RETRIES:
                print(f"    [警告] Open-Meteo取得失敗(lat={lat},lon={lon},model={model}): {e} "
                      f"-> {_FETCH_MAX_RETRIES}回リトライ後も失敗、このセルをスキップします")
                return None
            time.sleep(_FETCH_RETRY_BACKOFF_SEC * attempt)
    return None


def _to_dict_by_time(hourly: dict[str, list] | None) -> dict[datetime, dict]:
    if hourly is None:
        return {}
    result = {}
    times = hourly["time"]
    for i, t_str in enumerate(times):
        dt_local = datetime.fromisoformat(t_str).replace(tzinfo=JST)
        result[dt_local] = {
            "cloud_total": hourly["cloudcover"][i],
            "cloud_low": hourly["cloudcover_low"][i],
            "cloud_mid": hourly["cloudcover_mid"][i],
            "cloud_high": hourly["cloudcover_high"][i],
        }
    return result


def get_cloud_forecast(lat: float, lon: float, start_dt_local: datetime, end_dt_local: datetime,
                        cache: "GridCloudCache | None" = None) -> list[HourlyCloud]:
    """指定した緯度経度・時間範囲(JST、start以上end以下、1時間刻み)の雲量予報を取得する。

    直近はMSM、MSMの予報期間を超える先はECMWFを使い、1本の時系列として結合する。

    cache: grid_cache.GridCloudCache を渡すと、格子セル単位でAPI呼び出し結果を
      共有する(同一セルへの再問い合わせを避ける)。省略時はこの呼び出し専用の
      使い捨てキャッシュを内部で作る(単発利用時の後方互換用)。
    forecast_daysは呼び出し時刻に依存せず常に最大値で固定する
    (同じ地点への問い合わせが異なる日に行われてもキャッシュキーが一致するようにするため)。
    """
    from grid_cache import GridCloudCache

    if cache is None:
        cache = GridCloudCache()

    msm_hourly = cache.get_hourly(lat, lon, MSM_MODEL, MSM_MAX_FORECAST_DAYS, _HOURLY_VARS)
    ecmwf_hourly = cache.get_hourly(lat, lon, ECMWF_MODEL, ECMWF_MAX_FORECAST_DAYS, _HOURLY_VARS)

    msm_by_time = _to_dict_by_time(msm_hourly)
    ecmwf_by_time = _to_dict_by_time(ecmwf_hourly)

    results = []
    t = start_dt_local.replace(minute=0, second=0, microsecond=0)
    while t <= end_dt_local:
        msm_entry = msm_by_time.get(t)
        if msm_entry is not None and msm_entry["cloud_total"] is not None:
            results.append(HourlyCloud(
                dt_local=t, source="MSM",
                cloud_total=msm_entry["cloud_total"], cloud_low=msm_entry["cloud_low"],
                cloud_mid=msm_entry["cloud_mid"], cloud_high=msm_entry["cloud_high"],
            ))
        else:
            ecmwf_entry = ecmwf_by_time.get(t)
            if ecmwf_entry is not None and ecmwf_entry["cloud_total"] is not None:
                results.append(HourlyCloud(
                    dt_local=t, source="ECMWF",
                    cloud_total=ecmwf_entry["cloud_total"], cloud_low=ecmwf_entry["cloud_low"],
                    cloud_mid=ecmwf_entry["cloud_mid"], cloud_high=ecmwf_entry["cloud_high"],
                ))
            else:
                results.append(HourlyCloud(t, None, None, None, None, source="N/A"))
        t += timedelta(hours=1)

    return results


def milkyway_viewing_cloud_summary(
    lat: float, lon: float, night_date_local: date,
    start_hour: int = 23, end_hour: int = 1, stat: str = "mean",
    elevation_m: float = 0.0, cache: "GridCloudCache | None" = None,
) -> dict:
    """「その夜の天の川見頃時間帯」の雲量代表値を返す。

    night_date_local: 「夜」の基準日(例: 6/13の夜、なら date(2026,6,13))。
    start_hour, end_hour: 見頃時間帯(例: 23時〜翌1時なら start_hour=23, end_hour=1)。
      end_hour <= start_hour の場合は日付をまたぐものとして扱う
      (登山用途の早朝〜昼の時間帯とは異なり、天体撮影では夜間・日またぎが基本のため)。
    stat: "mean"(平均) / "max"(最悪ケース=最大雲量) / "min"(最良ケース=最小雲量)。
    elevation_m: 観測者標高(m)。0の場合、地表〜低層の気圧面もほぼ全て「観測者より上」
      として扱われるため、全層(cloudcover)集計に近い挙動になる。標高が高いほど、
      その標高より低い気圧面の雲量は「視界遮蔽雲量(sky_obstruction)」の集計から
      除外される(elevation_cloud.pyの気圧面別データを使用)。
    """
    from elevation_cloud import get_level_cloud_forecast, hourly_sky_obstruction_and_cloud_sea
    from grid_cache import GridCloudCache

    if cache is None:
        cache = GridCloudCache()

    start_dt = datetime(night_date_local.year, night_date_local.month, night_date_local.day, start_hour, tzinfo=JST)
    if end_hour <= start_hour:
        end_date = night_date_local + timedelta(days=1)
    else:
        end_date = night_date_local
    end_dt = datetime(end_date.year, end_date.month, end_date.day, end_hour, tzinfo=JST)

    hourly = get_cloud_forecast(lat, lon, start_dt, end_dt, cache=cache)
    valid = [h for h in hourly if h.cloud_total is not None]

    hourly_levels = get_level_cloud_forecast(lat, lon, start_dt, end_dt, cache=cache)
    obstruction_rows = hourly_sky_obstruction_and_cloud_sea(hourly_levels, elevation_m)
    valid_obstruction = [r for r in obstruction_rows if r["sky_obstruction"] is not None]

    def agg(values: list[float]) -> float:
        if stat == "mean":
            return sum(values) / len(values)
        if stat == "max":
            return max(values)
        if stat == "min":
            return min(values)
        raise ValueError(f"未知の統計値: {stat}")

    result = {
        "start": start_dt, "end": end_dt, "stat": stat, "elevation_m": elevation_m,
        "cloud_total": None, "cloud_low": None, "cloud_mid": None, "cloud_high": None,
        "sky_obstruction": None, "cloud_sea_index": None,
        "hourly": hourly, "hourly_obstruction": obstruction_rows,
    }
    if valid:
        result.update({
            "cloud_total": agg([h.cloud_total for h in valid]),
            "cloud_low": agg([h.cloud_low for h in valid]),
            "cloud_mid": agg([h.cloud_mid for h in valid]),
            "cloud_high": agg([h.cloud_high for h in valid]),
        })
    if valid_obstruction:
        result["sky_obstruction"] = agg([r["sky_obstruction"] for r in valid_obstruction])
        cloud_sea_values = [r["cloud_sea_index"] for r in valid_obstruction if r["cloud_sea_index"] is not None]
        if cloud_sea_values:
            result["cloud_sea_index"] = agg(cloud_sea_values)
            print(f"[雲海指数ログ] {lat},{lon} 標高{elevation_m:.0f}m "
                  f"{start_dt.strftime('%m/%d %H:%M')}-{end_dt.strftime('%H:%M')}: "
                  f"雲海指数({stat})={result['cloud_sea_index']:.1f}%")

    return result
