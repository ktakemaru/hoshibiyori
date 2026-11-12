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
# データ提供元が何のツールからのアクセスか判別できるよう、識別可能なUser-Agentを送る
# (GSIタイル・光害タイル・Nominatimと同じ方針。Open-Meteoは CC BY 4.0、出典表示が必要)。
_USER_AGENT = "hoshibiyori-cloud-forecast/1.0.0 (personal astrophotography tool; grid-cell cached, low-volume)"
ATTRIBUTION = "Weather data by Open-Meteo.com (https://open-meteo.com/), CC BY 4.0; models: JMA MSM, ECMWF IFS"
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


class OpenMeteoDailyLimitError(RuntimeError):
    """Open-Meteoが429(利用上限)を返し、以降の取得を中止することを表す。

    名前は後方互換のため「Daily」のまま(呼び出し側が捕まえている)。2026-11-13から、1分の上限(minutely)は
    grid_cache.GridCloudCache が65秒待って同じセルを取り直し(1回の実行で5回まで)、それでも足りないとき・
    1時間(hourly)・1日(daily)・種類が分からない(unknown)ときにこの例外で中止する。文に種類とreasonを入れる。
    """


# 429 の種類(本文の reason の語で分ける。2026-11-13)
RATE_LIMIT_KINDS = ("minutely", "hourly", "daily", "unknown")


def classify_rate_limit(reason_text: str | None) -> str:
    """429 の本文の reason から種類を返す。語は大文字小文字を区別しない。重い順(daily→hourly→minutely)に見る。"""
    text = (reason_text or "").lower()
    for kind in ("daily", "hourly", "minutely"):
        if kind in text:
            return kind
    return "unknown"


def _rate_limit_reason(resp) -> str:
    """429 の応答から reason を取り出す。JSON の reason が読めなければ本文の先頭200文字(それも無ければ空)。"""
    try:
        body = resp.json()
        if isinstance(body, dict) and isinstance(body.get("reason"), str):
            return body["reason"]
    except Exception:
        pass
    try:
        text = resp.text
        return text[:200] if isinstance(text, str) else ""
    except Exception:
        return ""


@dataclass
class FetchOutcome:
    """1回の取得結果。成功なら hourly に時系列、失敗なら hourly=None と理由が入る。"""
    hourly: dict[str, list] | None
    reason: str | None = None  # 失敗理由(人間向けの短い文字列)
    rate_limited: bool = False  # HTTP 429 を受けた場合 True(この関数の中ではリトライしない)
    # 時間の計測(画面表示用。2026-11-12)。attempts=試行の回数、elapsed_sec=通信にかかった秒数の合計
    # (再試行と、再試行の間の待ちを含む。2026-11-13から、通信の間隔の調整の待ちは含まない)、
    # failed_attempt_sec=失敗した試行(成功する前の失敗も含む)にかかった秒数の合計(再試行の間の待ちは含まない)。
    attempts: int = 0
    elapsed_sec: float = 0.0
    failed_attempt_sec: float = 0.0
    # 2026-11-13: 429 の種類(minutely/hourly/daily/unknown。429でなければNone)と本文のreason、
    # 通信の間隔の調整で待った秒数(この取得の全試行の合計)
    rate_limit_kind: str | None = None
    rate_limit_reason: str | None = None
    paced_sec: float = 0.0


# 時計(テストで差し替えられるよう、モジュールの変数にしておく)
_clock = time.perf_counter


# ---------------------------------------------------------------------------
# 通信の間隔の調整(2026-11-13)
# ---------------------------------------------------------------------------
# Open-Meteo の無料枠の上限(1分600・1時間5,000・1日10,000、IPアドレス単位)は、変数が多い・日数が長い
# 通信を1回より多く数える。直近60秒の重さの合計が PACING_LIMIT_PER_MINUTE を超えないよう、
# 通信の前(再試行も含む)に必要なだけ待つ。キャッシュヒットは通信しないので数えない。
PACING_WINDOW_SEC = 60.0
PACING_LIMIT_PER_MINUTE = 300.0  # 1分の上限600の半分(初期値)


def request_weight(variables: str, forecast_days: int) -> float:
    """1回の通信の重さの見積もり: max(1, 変数の数/10) × max(1, 予報日数/14)。"""
    n_vars = len([v for v in variables.split(",") if v.strip()])
    return max(1.0, n_vars / 10.0) * max(1.0, forecast_days / 14.0)


class RequestPacer:
    """直近 window_sec 秒の重さの合計が limit を超えないように待つ。時計と sleep は差し替えられる(テスト用)。"""

    def __init__(self, limit: float = PACING_LIMIT_PER_MINUTE, window_sec: float = PACING_WINDOW_SEC,
                 clock=time.monotonic, sleep=time.sleep):
        self.limit = limit
        self.window_sec = window_sec
        self.clock = clock
        self.sleep = sleep
        self._sent: list[tuple[float, float]] = []  # (送った時刻, 重さ)

    def _drop_old(self, now: float) -> None:
        cutoff = now - self.window_sec
        while self._sent and self._sent[0][0] <= cutoff:
            self._sent.pop(0)

    def window_total(self) -> float:
        self._drop_old(self.clock())
        return sum(w for _, w in self._sent)

    def acquire(self, weight: float) -> float:
        """重さ weight の通信を送ってよくなるまで待ち、送ったことを記録する。待った秒数を返す。"""
        waited = 0.0
        while True:
            now = self.clock()
            self._drop_old(now)
            total = sum(w for _, w in self._sent)
            if not self._sent or total + weight <= self.limit:
                self._sent.append((now, weight))
                return waited
            # 古いものから抜けていき、送れるようになる時刻まで待つ
            freed = 0.0
            wait_until = now
            for t_sent, w in self._sent:
                freed += w
                wait_until = t_sent + self.window_sec
                if total - freed + weight <= self.limit:
                    break
            delay = max(wait_until - now, 0.0)
            if delay > 0:
                self.sleep(delay)
                waited += delay


_PACER = RequestPacer()

# プロセスの中で使い回す接続(2026-11-12)。最初の通信のときに作る。
# 新しい接続を毎回張ると、TLSの途中で止まる(20秒の打ち切りまで待つ)ことがあるという実測
# (ビヨリコンシェルの計測で60回中11回、1本の接続を使い回すと0回)を受け、ヤマビヨリ v1.9.1 と同じ考え方で
# 入れた(ヤマビヨリのコードは見ずに独自に書いた)。切れた接続の張り直しは requests に任せ、
# アダプタや独自の再試行は付けない(再試行は _fetch_hourly_detailed のまま)。
_SESSION: requests.Session | None = None


def _http_session() -> requests.Session:
    global _SESSION
    if _SESSION is None:
        session = requests.Session()
        session.headers.update({"User-Agent": _USER_AGENT})
        _SESSION = session
    return _SESSION


def _fetch_hourly_detailed(lat: float, lon: float, model: str, forecast_days: int,
                           variables: str = _HOURLY_VARS) -> FetchOutcome:
    """Open-Meteoを呼び出す。761件規模のバッチ処理では一時的な接続エラーが起こり得るため、
    5xx・408・接続エラーは短い間隔で数回リトライする。429以外の4xxも回復しないため即座に失敗として返す。HTTP 429(利用上限)はリトライしても
    回復しないため、即座に rate_limited=True で返す(2026-10-12、yamabiyori v1.7.0の
    「全滅時は終了コード2」を元に、失敗理由を保持する形で独自拡張)。2026-11-13から、429の本文のreasonを読み
    種類(minutely/hourly/daily/unknown)を rate_limit_kind に入れて返す(1分の上限の待ちと取り直しは
    grid_cache 側)。各試行の前に通信の間隔の調整(_PACER)で待つことがある(待った秒数は paced_sec)。
    それでも失敗した場合は例外を投げず FetchOutcome(hourly=None, ...) を返し、
    呼び出し元(GridCloudCache)がそのセルをスキップ・集計できるようにする。
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": variables,
        "models": model,
        "forecast_days": forecast_days,
        "timezone": "Asia/Tokyo",
    }
    session = _http_session()
    weight = request_weight(variables, forecast_days)
    t0 = _clock()
    attempts = 0
    failed_sec = 0.0
    paced_sec = 0.0

    def outcome(hourly, reason=None, rate_limited=False, kind=None, rl_reason=None) -> FetchOutcome:
        # 通信の秒数から、間隔の調整の待ちを除く(内訳で別に数えるため)
        return FetchOutcome(hourly, reason=reason, rate_limited=rate_limited, attempts=attempts,
                            elapsed_sec=_clock() - t0 - paced_sec, failed_attempt_sec=failed_sec,
                            rate_limit_kind=kind, rate_limit_reason=rl_reason, paced_sec=paced_sec)

    for attempt in range(1, _FETCH_MAX_RETRIES + 1):
        attempts = attempt
        paced_sec += _PACER.acquire(weight)  # 再試行の通信も数える
        t_try = _clock()
        try:
            resp = session.get(_OPEN_METEO_URL, params=params, timeout=20, headers={"User-Agent": _USER_AGENT})
            if resp.status_code == 429:
                failed_sec += _clock() - t_try
                rl_reason = _rate_limit_reason(resp)
                kind = classify_rate_limit(rl_reason)
                print(f"    [警告] Open-Meteoが429(利用上限、種類={kind})を返しました"
                      f"(lat={lat},lon={lon},model={model})。reason: {rl_reason or '(本文なし)'}")
                return outcome(None, reason=f"HTTP 429 ({kind}): {rl_reason}", rate_limited=True,
                               kind=kind, rl_reason=rl_reason)
            if 400 <= resp.status_code < 500 and resp.status_code != 408:
                # 429以外の4xx(400/401/403/404等)はリクエスト側の問題でリトライしても回復しない。
                # 408(Request Timeout)だけは一時的な事象のため、5xxや接続エラーと同様にリトライする。
                failed_sec += _clock() - t_try
                print(f"    [警告] Open-Meteoが{resp.status_code}を返しました(lat={lat},lon={lon},model={model})。リトライしません")
                return outcome(None, reason=f"client_error (HTTP {resp.status_code})")
            resp.raise_for_status()
            return outcome(resp.json()["hourly"])
        except requests.RequestException as e:
            failed_sec += _clock() - t_try
            if attempt == _FETCH_MAX_RETRIES:
                print(f"    [警告] Open-Meteo取得失敗(lat={lat},lon={lon},model={model}): {e} "
                      f"-> {_FETCH_MAX_RETRIES}回リトライ後も失敗、このセルをスキップします")
                return outcome(None, reason=f"{type(e).__name__}: {e}")
            # 再試行のたびに1行出す(2026-11-13。回数・間隔・打ち切りは変えていない)
            print(f"    [再試行] Open-Meteo(lat={lat},lon={lon},model={model}): {type(e).__name__} -> "
                  f"{_FETCH_RETRY_BACKOFF_SEC * attempt:.0f}秒待って{attempt + 1}回目を試します")
            time.sleep(_FETCH_RETRY_BACKOFF_SEC * attempt)
    return outcome(None, reason="unknown")


def _fetch_hourly(lat: float, lon: float, model: str, forecast_days: int, variables: str = _HOURLY_VARS) -> dict[str, list] | None:
    """_fetch_hourly_detailed の後方互換ラッパー。失敗時はNoneを返す。"""
    return _fetch_hourly_detailed(lat, lon, model, forecast_days, variables).hourly


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
