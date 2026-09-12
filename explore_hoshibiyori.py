"""hoshibiyori 探索モード本体: 月 -> 雲 -> 方角 の3段階漏斗型パイプライン。

第1段階(月フィルタ): 直近14日間の各夜について、天文薄明終了〜天文薄明開始(太陽高度-18°、
  2026-09-07に日没〜日の出から変更)のうち「月が地平線下、または新月に近く影響が小さい」
  時間帯の長さを求め、長い順に上位候補日を抽出する。
第2段階(雲フィルタ): 候補日ごとに各候補地点(標高考慮)の時間別視界遮蔽雲量を計算し、
  閾値以下が連続MIN_CLEAR_WINDOW_HOURS時間以上続く「晴れ間」があるものだけを残す
  (2026-09-07変更。従来は区間全体の平均値のみで判定しており、「見頃」として表示する
  時間帯自体は雲の状況を反映していなかった。現在はfind_longest_clear_window()で
  見つけた最長の晴れ間そのものを以降の段階に渡す)。雲量取得はすべて
  grid_cache.GridCloudCache 経由(格子セル単位でAPI呼び出しを共有)。
第3段階(方角フィルタ): 残った組み合わせについて対象天体の方位角・高度を計算し、
  地形地平線を上回り、かつ光害が一定以下のものだけを最終候補とする。
  地形地平線プロファイルが無い地点は地形チェックをスキップし、
  結果に「地形データなし」と明示する(正式対応は地形バッチ計算を別途実施後)。

候補地点は stargazing_spots.json(2026-09-06新設の統合マスターファイル)を読み込む。
  - spots配列(84件、origin="curated"/"curated+test_site"/"curated+viewpoint"): 星空撮影の
    専門家・愛好家によるWeb調査(集合知)に基づく主軸データ。今後の探索・スコアリングの中心。
  - viewpoint_reference配列(751件、origin="viewpoint"/"test_site"): OSM tourism=viewpoint由来の
    機械的収集データ(星空適性は未フィルタ)。参考候補として補助的に扱い、レポートも区別して出力する。
  地形地平線プロファイル・光害計算済みフラグは、いずれの配列でもエントリごとの
  horizon_profile/light_pollution_computedフィールドに既に反映済み(stargazing_spots.json生成時に
  candidate_sites.dbとの照合・統合済みのため、本ファイル側で名前引きし直す必要はない)。
  候補地点DB自体(step7_geocoding/candidate_sites.db)はこのファイルからは直接参照しない。
エリア代表点による事前スクリーニングは今回は見送り、格子セルキャッシュのみのシンプルな構成。
"""
from __future__ import annotations

import csv
import json
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parent
for sub in ["step1_astronomy", "step2_terrain", "step3_light_pollution", "step4_moonlight", "step5_cloud_forecast"]:
    sys.path.insert(0, str(ROOT / sub))

from skyfield import almanac  # noqa: E402
from skyfield.api import load, wgs84  # noqa: E402

from catalog import get_target  # noqa: E402
from sky_engine import altaz_at_time  # noqa: E402
from light_pollution import LightPollutionTileStore  # noqa: E402
from moon_position import compute_moon_position  # noqa: E402
from moon_brightness import combine_sky_brightness  # noqa: E402
from elevation_cloud import get_level_cloud_forecast, hourly_sky_obstruction_and_cloud_sea  # noqa: E402
from grid_cache import GridCloudCache  # noqa: E402

JST = timezone(timedelta(hours=9))

# --- パラメータ(既定値) ---
NUM_NIGHTS_TO_SCAN = 14
NUM_CANDIDATE_NIGHTS = 6
CLOUD_OBSTRUCTION_THRESHOLD = 30.0
MIN_CLEAR_WINDOW_HOURS = 1.0  # これ未満の晴れ間は「見頃」として採用しない(2026-09-07追加)
# 2026-09-07、ユーザーの実地経験により3.0から5.0に引き上げ。神磯の鳥居(LPI 4.93)・
# 安房埼灯台(LPI 3.27)は単発長時間露光(ISO3200・20秒程度、追尾・比較明合成等の
# 特別な機材なし)で天の川撮影に成功した実績がある一方、菜の花台(LPI 6.49)・
# 高尾山(LPI 10.18)は同ユーザーの経験上、天の川等の撮影は難しく明るい天体中心の
# 星空観賞向けとのこと。成功実績(4.93)と失敗経験(6.49)の間に閾値を置く。
LPI_THRESHOLD = 5.0
MOON_PHASE_NEGLIGIBLE_DEG = 150.0
TARGET_ID = "galactic_center"

STARGAZING_SPOTS_PATH = ROOT / "stargazing_spots.json"

# 検証済み7地点(いずれもstargazing_spots.json側にhorizon_profileとして既に記録済み)の標高(m)。
# stargazing_spots.jsonのspots配列(curated由来)は緯度経度のみで標高情報を持たないため、
# 名前が一致するものはここで正確な標高を補う。それ以外(curated大半・viewpoint参考データで
# eleタグが無いもの)はDEFAULT_ELEVATION_Mを暫定既定値として使う。
ELEVATION_BY_NAME = {
    "富士山頂": 3776.0, "須走口五合目": 1975.0, "精進湖 他手合浜": 914.56,
    "八ヶ岳南麓天文台": 1060.38, "石廊崎": 60.0, "いすみ鉄道踏切": 17.57,
    "ヘブンスそのはら": 1600.36,
}
DEFAULT_ELEVATION_M = 300.0  # 標高情報が無い地点に対する暫定既定値

# originごとの由来ラベル(レポート出力での注記に使う)。
# curated系("curated"/"curated+test_site"/"curated+viewpoint")は星空撮影名所として主軸扱い、
# viewpoint/test_siteはOSM由来の一般展望データで星空適性は未フィルタのため参考候補として区別する。
ORIGIN_LABELS = {
    "curated": "星空撮影名所(集合知ベース)",
    "curated+test_site": "星空撮影名所(集合知ベース、検証済み地点データと統合)",
    "curated+viewpoint": "星空撮影名所(集合知ベース、OSM展望データと統合)",
    "viewpoint": "一般展望スポット(星空適性未検証・参考候補)",
    "test_site": "検証済み地点(地形・光害データあり、集合知データには未登録)",
    # 2026-09-07追加。別システムで収集された星空撮影スポットリスト(場所名+座標のみ、
    # Web調査の説明文なし)をユーザーが持ち込みマージしたもの。curatedと同様に主軸データ
    # として扱うが、由来の出所(説明文の有無)を区別するため別のorigin値にしている。
    "curated_external": "星空撮影名所(外部リストより追加、説明文なし)",
}
PRIMARY_ORIGINS = {"curated", "curated+test_site", "curated+viewpoint", "curated_external"}


def is_primary_origin(origin: str) -> bool:
    return origin in PRIMARY_ORIGINS


def _build_site(entry: dict) -> dict:
    name = entry["name"]
    ele = entry.get("ele")
    if name in ELEVATION_BY_NAME:
        elevation_m = ELEVATION_BY_NAME[name]
    elif entry.get("elevation_m") is not None:
        # step2_terrain/precompute_terrain.pyがDEMタイルから実測した標高
        # (spots配列81件、2026-09-06計算済み)。ele(OSM由来)より優先する。
        elevation_m = entry["elevation_m"]
    elif ele:
        try:
            elevation_m = float(ele)
        except (TypeError, ValueError):
            elevation_m = DEFAULT_ELEVATION_M
    else:
        elevation_m = DEFAULT_ELEVATION_M

    return {
        "name": name, "lat": entry["lat"], "lon": entry["lon"], "elevation_m": elevation_m,
        "municipality": entry.get("municipality") or "不明",
        "origin": entry["origin"],
        "horizon_csv": entry.get("horizon_profile"),
        "requires_lift_access": entry.get("requires_lift_access", False),
        # classify_site_darkness.py(2026-09-07)がspots配列(curated由来)に事前計算した分類。
        # viewpoint_reference側には無いため未計算の地点はNone(まだ「night_view」と決めつけない)。
        "site_type": entry.get("site_type"),
        "lpi_precomputed": entry.get("lpi"),
    }


def load_candidate_sites() -> list[dict]:
    with open(STARGAZING_SPOTS_PATH, encoding="utf-8") as f:
        data = json.load(f)

    sites = [_build_site(s) for s in data["spots"]]
    sites += [_build_site(s) for s in data["viewpoint_reference"]]
    return sites


def load_horizon_profile(csv_path: str) -> dict[int, float]:
    profile = {}
    with open(ROOT / csv_path, encoding="utf-8") as f:
        lines = [l for l in f if not l.startswith("#")]
    reader = csv.DictReader(lines)
    for row in reader:
        profile[int(row["azimuth_deg"])] = float(row["horizon_altitude_deg"])
    return profile


def horizon_alt_at(profile: dict[int, float], az_deg: float) -> float:
    return profile[round(az_deg) % 360]


def find_sun_events(ts, eph, lat: float, lon: float, day_start_local: datetime) -> tuple[datetime, datetime]:
    topos = wgs84.latlon(lat, lon)
    t0 = ts.from_datetime(day_start_local.astimezone(timezone.utc))
    t1 = ts.from_datetime((day_start_local + timedelta(hours=48)).astimezone(timezone.utc))
    f = almanac.risings_and_settings(eph, eph["sun"], topos)
    times, events = almanac.find_discrete(t0, t1, f)

    sunset = None
    sunrise = None
    for t, is_rise in zip(times, events):
        local_dt = t.utc_datetime().astimezone(JST)
        if local_dt.date() == day_start_local.date() and not is_rise and sunset is None:
            sunset = local_dt
        elif sunset is not None and is_rise and local_dt > sunset and sunrise is None:
            sunrise = local_dt
    return sunset, sunrise


def find_astro_dark_events(ts, eph, lat: float, lon: float, day_start_local: datetime) -> tuple[datetime | None, datetime | None]:
    """天文薄明終了(太陽高度-18°を下回る)を基準とした「完全に暗い」区間の開始・終了時刻を求める。

    日没直後は市民薄明・航海薄明・天文薄明が明るいうちは空が完全に暗くならず、
    肉眼・カメラともに天の川等は見えにくい(この閾値はSkyfieldのdark_twilight_dayの
    区分[4=昼, 3=市民薄明, 2=航海薄明, 1=天文薄明, 0=夜]における「0」への遷移と一致)。
    """
    topos = wgs84.latlon(lat, lon)
    t0 = ts.from_datetime(day_start_local.astimezone(timezone.utc))
    t1 = ts.from_datetime((day_start_local + timedelta(hours=48)).astimezone(timezone.utc))
    f = almanac.dark_twilight_day(eph, topos)
    times, events = almanac.find_discrete(t0, t1, f)

    dark_start = None
    dark_end = None
    for t, val in zip(times, events):
        local_dt = t.utc_datetime().astimezone(JST)
        if val == 0 and local_dt.date() == day_start_local.date() and dark_start is None:
            dark_start = local_dt
        elif dark_start is not None and val == 1 and local_dt > dark_start and dark_end is None:
            dark_end = local_dt
    return dark_start, dark_end


def longest_negligible_window(ts, eph, ref_lat: float, ref_lon: float, sunset: datetime, sunrise: datetime,
                               sample_interval_min: int = 15) -> tuple[datetime | None, datetime | None, float]:
    samples = []
    t = sunset
    while t <= sunrise:
        moon = compute_moon_position(ts, eph, ref_lat, ref_lon, 0.0, t)
        negligible = moon.alt_deg <= 0 or moon.phase_angle_deg >= MOON_PHASE_NEGLIGIBLE_DEG
        samples.append((t, negligible))
        t += timedelta(minutes=sample_interval_min)

    best_start, best_end, best_len = None, None, 0.0
    cur_start = None
    for t, neg in samples:
        if neg and cur_start is None:
            cur_start = t
        elif not neg and cur_start is not None:
            length = (t - cur_start).total_seconds() / 3600.0
            if length > best_len:
                best_start, best_end, best_len = cur_start, t, length
            cur_start = None
    if cur_start is not None:
        length = (samples[-1][0] - cur_start).total_seconds() / 3600.0
        if length > best_len:
            best_start, best_end, best_len = cur_start, samples[-1][0], length

    return best_start, best_end, best_len


def compute_site_night_window(ts, eph, site: dict, night_date: date) -> tuple[datetime | None, datetime | None, float]:
    """指定地点・指定夜について、その地点自身の座標を基準に天文薄明・無月時間帯を計算する。

    石廊崎1地点の座標を全候補地点で使い回すと、経度差による薄明・月の出没時刻のずれ
    (石廊崎〜佐渡・立山で数分〜十数分程度)が無視されるため、地点ごとに計算し直す
    (2026-09-07追加。night_dateの選定自体は引き続き石廊崎基準で行うが、実際の
    「見頃」区間・雲量取得範囲はこの関数の結果を使う)。
    """
    day_start_local = datetime(night_date.year, night_date.month, night_date.day, tzinfo=JST)
    dark_start, dark_end = find_astro_dark_events(ts, eph, site["lat"], site["lon"], day_start_local)
    if dark_start is None or dark_end is None:
        return None, None, 0.0
    return longest_negligible_window(ts, eph, site["lat"], site["lon"], dark_start, dark_end)


@dataclass
class NightCandidate:
    night_date: date
    sunset: datetime
    sunrise: datetime
    dark_start: datetime | None
    dark_end: datetime | None
    window_start: datetime | None
    window_end: datetime | None
    moon_free_hours: float


@dataclass
class FinalCandidate:
    night_date: date
    site_name: str
    municipality: str
    origin: str
    site_lat: float
    site_lon: float
    requires_lift_access: bool
    window_start: datetime
    window_end: datetime
    best_time: datetime
    target_az: float
    target_alt: float
    horizon_alt: float | None
    terrain_available: bool
    mean_obstruction: float
    lpi: float
    effective_mpsas: float
    moon_free_hours: float
    clear_hours: float
    score: float = 0.0


@dataclass
class OutlookCandidate:
    """ECMWF圏内(長期)の候補。雲量は数値スコアに使わず、参考値(晴天率)として添える。"""
    night_date: date
    site_name: str
    municipality: str
    origin: str
    site_lat: float
    site_lon: float
    requires_lift_access: bool
    visible_start: datetime | None
    visible_end: datetime | None
    target_az: float | None
    target_alt: float | None
    horizon_alt: float | None
    terrain_available: bool
    lpi: float
    effective_mpsas: float
    clear_sky_pct: float | None
    moon_free_hours: float
    score: float = 0.0


def forecast_regime_for_night(cache: GridCloudCache, ref_site: dict, night: "NightCandidate") -> str:
    """候補夜がMSM(精密)圏内かECMWF(見込み)圏内かを、実際のフォールバック結果から判定する。

    cloud_forecast.py/elevation_cloud.pyの結合ロジックが各時刻に付与するsource
    ("MSM"/"ECMWF")の多数決で判定する(既存のフォールバック判定をそのまま流用)。
    """
    levels = get_level_cloud_forecast(ref_site["lat"], ref_site["lon"], night.window_start, night.window_end, cache=cache)
    if not levels:
        return "ECMWF"
    msm_count = sum(1 for l in levels if l.source == "MSM")
    return "MSM" if msm_count > len(levels) / 2 else "ECMWF"


def compute_target_window(ts, eph, site: dict, target, window_start: datetime, window_end: datetime,
                           profile: dict[int, float] | None, sample_interval_min: int = 15):
    """月・地形から決まる、その夜・その地点での対象天体の「見頃時間帯」を求める(決定論的)。

    window_start/window_endはその地点自身の座標で計算した無月時間帯(compute_site_night_window参照)。
    地形地平線を上回っている(profileが無ければ常に可視とみなす)連続区間のうち
    最長のものを返す。戻り値: (見頃開始, 見頃終了, 見頃内で最も高度が高い時刻とその高度・方位角)。
    """
    samples = []
    t = window_start
    while t <= window_end:
        t_sf = ts.from_datetime(t.astimezone(timezone.utc))
        az, alt = altaz_at_time(t_sf, eph, site["lat"], site["lon"], site["elevation_m"], target)
        if profile is not None:
            visible = alt > horizon_alt_at(profile, az)
        else:
            visible = True
        samples.append((t, az, alt, visible))
        t += timedelta(minutes=sample_interval_min)

    best_start, best_end, best_len = None, None, timedelta(0)
    cur_start = None
    for t, az, alt, vis in samples:
        if vis and cur_start is None:
            cur_start = t
        elif not vis and cur_start is not None:
            length = t - cur_start
            if length > best_len:
                best_start, best_end, best_len = cur_start, t, length
            cur_start = None
    if cur_start is not None:
        length = samples[-1][0] - cur_start
        if length > best_len:
            best_start, best_end = cur_start, samples[-1][0]

    if best_start is None:
        return None, None, None, None, None

    in_window = [s for s in samples if best_start <= s[0] <= best_end]
    peak = max(in_window, key=lambda s: s[2])
    peak_time, peak_az, peak_alt, _ = peak
    return best_start, best_end, peak_time, peak_az, peak_alt


def stage1_moon_filter(ts, eph, ref_lat: float, ref_lon: float) -> list[NightCandidate]:
    today = datetime.now(JST).replace(hour=0, minute=0, second=0, microsecond=0)
    candidates = []
    for i in range(NUM_NIGHTS_TO_SCAN):
        day = today + timedelta(days=i)
        sunset, sunrise = find_sun_events(ts, eph, ref_lat, ref_lon, day)
        if sunset is None or sunrise is None:
            continue
        dark_start, dark_end = find_astro_dark_events(ts, eph, ref_lat, ref_lon, day)
        if dark_start is None or dark_end is None:
            continue
        w_start, w_end, hours = longest_negligible_window(ts, eph, ref_lat, ref_lon, dark_start, dark_end)
        if w_start is None:
            continue
        candidates.append(NightCandidate(
            night_date=day.date(), sunset=sunset, sunrise=sunrise,
            dark_start=dark_start, dark_end=dark_end,
            window_start=w_start, window_end=w_end, moon_free_hours=hours,
        ))

    candidates.sort(key=lambda c: c.moon_free_hours, reverse=True)
    top = candidates[:NUM_CANDIDATE_NIGHTS]

    print(f"[第1段階: 月フィルタ] 直近{NUM_NIGHTS_TO_SCAN}夜を評価 -> "
          f"月の影響が小さい時間帯が長い順に上位{len(top)}夜を候補日とする")
    for c in top:
        print(f"    {c.night_date}  無月時間帯 {c.window_start.strftime('%H:%M')}"
              f"-{c.window_end.strftime('%H:%M(翌)') if c.window_end.date()!=c.window_start.date() else c.window_end.strftime('%H:%M')}"
              f"  ({c.moon_free_hours:.1f}時間)")
    return top


def all_nights_timeline(ts, eph, ref_lat: float, ref_lon: float,
                         num_nights: int = NUM_NIGHTS_TO_SCAN) -> list[NightCandidate]:
    """直近num_nights夜すべてを日付順(トップNに絞らない)で評価する。

    HTMLレポートの概況タイムライン・計画用カレンダー向け。無月時間帯が全く
    得られない夜(理論上まれ)はwindow_start/window_end=None・moon_free_hours=0.0
    として含める。stage2_cloud_filter等に渡す前に呼び出し側でNoneを除外すること
    (既存のstage1_moon_filterの「トップN」出力は元々window有りのみに絞られている)。
    """
    today = datetime.now(JST).replace(hour=0, minute=0, second=0, microsecond=0)
    timeline = []
    for i in range(num_nights):
        day = today + timedelta(days=i)
        sunset, sunrise = find_sun_events(ts, eph, ref_lat, ref_lon, day)
        if sunset is None or sunrise is None:
            continue
        dark_start, dark_end = find_astro_dark_events(ts, eph, ref_lat, ref_lon, day)
        if dark_start is not None and dark_end is not None:
            w_start, w_end, hours = longest_negligible_window(ts, eph, ref_lat, ref_lon, dark_start, dark_end)
        else:
            w_start, w_end, hours = None, None, 0.0
        timeline.append(NightCandidate(
            night_date=day.date(), sunset=sunset, sunrise=sunrise,
            dark_start=dark_start, dark_end=dark_end,
            window_start=w_start, window_end=w_end, moon_free_hours=hours,
        ))
    return timeline


def find_longest_clear_window(rows: list[dict], threshold: float, window_start: datetime, window_end: datetime,
                               min_hours: float = MIN_CLEAR_WINDOW_HOURS) -> tuple[datetime | None, datetime | None, float | None]:
    """時間別の視界遮蔽雲量(hourly_sky_obstruction_and_cloud_seaの戻り値)から、
    しきい値以下が連続する区間のうち最長のものを[window_start, window_end]の範囲内で求める。

    2026-09-07追加。従来は区間全体([window_start, window_end])の平均視界遮蔽雲量を
    足切り閾値と比べるだけで、「見頃」として表示する時間帯自体は雲の状況を反映していなかった
    (区間の前半だけ晴れて後半は曇っていても、平均さえ閾値以下なら区間全体を「見頃」と表示していた)。
    各行のdt_localは「その時刻から1時間分」の雲量を表す(Open-Meteo時間別データの粒度による近似)。
    最長区間がmin_hours未満しかない場合は「見頃」と呼べるほどの晴れ間がないとみなし
    (None, None, None)を返す。戻り値: (区間開始, 区間終了, 区間内平均視界遮蔽雲量)。
    """
    runs = []
    cur = []
    for r in rows:
        v = r["sky_obstruction"]
        if v is not None and v <= threshold:
            cur.append(r)
        elif cur:
            runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)

    best = None
    for run in runs:
        start = max(run[0]["dt_local"], window_start)
        end = min(run[-1]["dt_local"] + timedelta(hours=1), window_end)
        if end <= start:
            continue
        length_hours = (end - start).total_seconds() / 3600.0
        if best is None or length_hours > best[2]:
            mean_obstruction = sum(r["sky_obstruction"] for r in run) / len(run)
            best = (start, end, length_hours, mean_obstruction)

    if best is None or best[2] < min_hours:
        return None, None, None
    start, end, _length_hours, mean_obstruction = best
    return start, end, mean_obstruction


def stage2_cloud_filter(ts, eph, nights: list[NightCandidate], sites: list[dict], cache: GridCloudCache) -> list[dict]:
    survivors = []
    total_pairs = 0
    for night in nights:
        for i, site in enumerate(sites):
            total_pairs += 1
            w_start, w_end, hours = compute_site_night_window(ts, eph, site, night.night_date)
            if w_start is None:
                continue
            levels = get_level_cloud_forecast(site["lat"], site["lon"], w_start, w_end, cache=cache)
            rows = hourly_sky_obstruction_and_cloud_sea(levels, site["elevation_m"])
            clear_start, clear_end, mean_obstruction = find_longest_clear_window(
                rows, CLOUD_OBSTRUCTION_THRESHOLD, w_start, w_end)
            if clear_start is None:
                continue
            clear_hours = (clear_end - clear_start).total_seconds() / 3600.0
            survivors.append({
                "night": night, "site": site, "mean_obstruction": mean_obstruction,
                "window_start": clear_start, "window_end": clear_end,
                "moon_free_hours": hours, "clear_hours": clear_hours,
            })

            if (i + 1) % 200 == 0:
                print(f"    ...{night.night_date} {i+1}/{len(sites)}地点処理済み "
                      f"(API呼び出し{cache.call_count}回, キャッシュヒット{cache.cache_hit_count}回)")

    print(f"\n[第2段階: 雲フィルタ] 候補日{len(nights)}日 × 候補地点{len(sites)}件 = "
          f"{total_pairs}組み合わせのうち、視界遮蔽雲量{CLOUD_OBSTRUCTION_THRESHOLD:.0f}%以下が"
          f"連続{MIN_CLEAR_WINDOW_HOURS:.0f}時間以上続く晴れ間があるのは {len(survivors)}組")
    print(f"    (格子セルキャッシュ: API呼び出し{cache.call_count}回 / キャッシュヒット{cache.cache_hit_count}回)")
    return survivors


def stage3_direction_filter(ts, eph, survivors: list[dict], lp_store: LightPollutionTileStore) -> list[FinalCandidate]:
    target = get_target(TARGET_ID)
    finals = []
    horizon_profile_cache: dict[str, dict[int, float]] = {}
    no_terrain_count = 0

    for s in survivors:
        night: NightCandidate = s["night"]
        site = s["site"]
        window_start, window_end, moon_free_hours = s["window_start"], s["window_end"], s["moon_free_hours"]

        profile = None
        if site["horizon_csv"]:
            if site["horizon_csv"] not in horizon_profile_cache:
                horizon_profile_cache[site["horizon_csv"]] = load_horizon_profile(site["horizon_csv"])
            profile = horizon_profile_cache[site["horizon_csv"]]

        lp_result = lp_store.get(site["lat"], site["lon"])

        best_alt, best_az, best_time = -90.0, None, None
        t = window_start
        while t <= window_end:
            t_sf = ts.from_datetime(t.astimezone(timezone.utc))
            az, alt = altaz_at_time(t_sf, eph, site["lat"], site["lon"], site["elevation_m"], target)
            if alt > best_alt:
                best_alt, best_az, best_time = alt, az, t
            t += timedelta(minutes=15)

        if best_time is None:
            continue

        clears_light_pollution = lp_result.brightness_ratio <= LPI_THRESHOLD

        if profile is not None:
            h_alt = horizon_alt_at(profile, best_az)
            clears_horizon = best_alt > h_alt
            terrain_available = True
        else:
            h_alt = None
            clears_horizon = True  # 地形データが無いため判定をスキップ(暫定): 通過扱いとし、結果に明示する
            terrain_available = False
            no_terrain_count += 1

        if clears_horizon and clears_light_pollution:
            moon = compute_moon_position(ts, eph, site["lat"], site["lon"], site["elevation_m"], best_time)
            effective = combine_sky_brightness(lp_result.mpsas, moon.alt_deg, moon.phase_angle_deg)

            score = (
                (100.0 - s["mean_obstruction"]) * 1.0
                + max(0.0, best_alt - (h_alt or 0.0)) * 0.5
                + s["clear_hours"] * 3.0
                - lp_result.brightness_ratio * 10.0
            )
            finals.append(FinalCandidate(
                night_date=night.night_date, site_name=site["name"], municipality=site["municipality"],
                origin=site["origin"], site_lat=site["lat"], site_lon=site["lon"],
                requires_lift_access=site["requires_lift_access"],
                window_start=window_start, window_end=window_end,
                best_time=best_time, target_az=best_az, target_alt=best_alt,
                horizon_alt=h_alt, terrain_available=terrain_available,
                mean_obstruction=s["mean_obstruction"], lpi=lp_result.brightness_ratio,
                effective_mpsas=effective["effective_mpsas"],
                moon_free_hours=moon_free_hours, clear_hours=s["clear_hours"], score=score,
            ))

    print(f"\n[第3段階: 方角フィルタ] {len(survivors)}組のうち、"
          f"「{target.name}が地形地平線を上回り(地形データ有りの場合)、かつLPI<={LPI_THRESHOLD}」を満たすのは"
          f" {len(finals)}件")
    print(f"    うち地形データなし(viewpoint由来、地形チェック未実施・暫定通過): {no_terrain_count}件")
    return finals


def stage_outlook(ts, eph, nights: list["NightCandidate"], sites: list[dict],
                   lp_store: LightPollutionTileStore, cache: GridCloudCache) -> list[OutlookCandidate]:
    """ECMWF圏内(長期見込み)の夜を処理する。雲量は数値スコア・足切りに使わず、
    月・地形・光害という決定論的要素だけでランキングし、雲は「晴天率」の参考値として添える。
    """
    target = get_target(TARGET_ID)
    horizon_profile_cache: dict[str, dict[int, float]] = {}
    results = []

    for night in nights:
        for site in sites:
            w_start, w_end, moon_free_hours = compute_site_night_window(ts, eph, site, night.night_date)
            if w_start is None:
                continue

            profile = None
            if site["horizon_csv"]:
                if site["horizon_csv"] not in horizon_profile_cache:
                    horizon_profile_cache[site["horizon_csv"]] = load_horizon_profile(site["horizon_csv"])
                profile = horizon_profile_cache[site["horizon_csv"]]

            v_start, v_end, peak_time, peak_az, peak_alt = compute_target_window(ts, eph, site, target, w_start, w_end, profile)
            if v_start is None:
                continue

            lp_result = lp_store.get(site["lat"], site["lon"])
            if lp_result.brightness_ratio > LPI_THRESHOLD:
                continue

            moon = compute_moon_position(ts, eph, site["lat"], site["lon"], site["elevation_m"], peak_time)
            effective = combine_sky_brightness(lp_result.mpsas, moon.alt_deg, moon.phase_angle_deg)

            # 雲量は参考値(晴天率)としてのみ計算し、足切りには使わない
            levels = get_level_cloud_forecast(site["lat"], site["lon"], v_start, v_end, cache=cache)
            rows = hourly_sky_obstruction_and_cloud_sea(levels, site["elevation_m"])
            valid = [r["sky_obstruction"] for r in rows if r["sky_obstruction"] is not None]
            clear_sky_pct = (
                100.0 * sum(1 for v in valid if v <= CLOUD_OBSTRUCTION_THRESHOLD) / len(valid)
                if valid else None
            )

            score = (
                (100.0 - lp_result.brightness_ratio * 10.0)
                + max(0.0, peak_alt - (horizon_alt_at(profile, peak_az) if profile is not None else 0.0)) * 0.5
                + moon_free_hours * 3.0
            )

            results.append(OutlookCandidate(
                night_date=night.night_date, site_name=site["name"], municipality=site["municipality"],
                origin=site["origin"], site_lat=site["lat"], site_lon=site["lon"],
                requires_lift_access=site["requires_lift_access"],
                visible_start=v_start, visible_end=v_end,
                target_az=peak_az, target_alt=peak_alt,
                horizon_alt=(horizon_alt_at(profile, peak_az) if profile is not None else None),
                terrain_available=profile is not None,
                lpi=lp_result.brightness_ratio, effective_mpsas=effective["effective_mpsas"],
                clear_sky_pct=clear_sky_pct, moon_free_hours=moon_free_hours, score=score,
            ))

    print(f"\n[見込み(ECMWF圏内)] 候補日{len(nights)}日 × 候補地点{len(sites)}件のうち、"
          f"月・地形・光害の決定論的条件を満たすのは {len(results)}件"
          f"(雲量は足切りに使わず、晴天率として参考表示のみ)")
    return results


def _print_outlook_items(outlooks: list[OutlookCandidate], target, top_n: int) -> None:
    for i, o in enumerate(outlooks[:top_n], 1):
        terrain_note = (f"地形地平線{o.horizon_alt:.1f}°を{o.target_alt - o.horizon_alt:.1f}°上回る"
                         if o.terrain_available else "地形データなし(未評価)")
        clear_note = f"参考: この時間帯の晴天率 約{o.clear_sky_pct:.0f}%" if o.clear_sky_pct is not None else "参考: 晴天率データなし"
        print(f"\n[{i}位] スコア {o.score:.1f}")
        print(f"  日付      : {o.night_date}")
        print(f"  地点      : {o.site_name}（{o.municipality}）")
        print(f"  由来      : {ORIGIN_LABELS.get(o.origin, o.origin)}")
        print(f"  {target.name}の見頃: {o.visible_start.strftime('%H:%M')} 〜 {o.visible_end.strftime('%H:%M')}"
              f"（{terrain_note}）")
        print(f"  実効的な空の明るさ: {o.effective_mpsas:.2f} mag/arcsec^2 (光害LPI {o.lpi:.2f}、月の影響込み)")
        print(f"  → 晴れれば {o.visible_start.strftime('%H:%M')}〜{o.visible_end.strftime('%H:%M')} にチャンスがあります。"
              f"({clear_note})")


def print_outlook_report(outlooks: list[OutlookCandidate], top_n: int = 20, top_n_reference: int = 10) -> None:
    target = get_target(TARGET_ID)
    primary = sorted((o for o in outlooks if is_primary_origin(o.origin)), key=lambda o: o.score, reverse=True)
    reference = sorted((o for o in outlooks if not is_primary_origin(o.origin)), key=lambda o: o.score, reverse=True)

    print(f"\n{'-'*78}")
    print(f"見込み一覧・主要候補(対象: {target.name}、星空撮影名所ベース、"
          f"月・地形・光害による決定論的スコア順、上位{top_n}件)")
    print(f"{'-'*78}")
    if primary:
        _print_outlook_items(primary, target, top_n)
    else:
        print("\n  該当なし(主要候補=curated由来の地点で条件を満たすものがありませんでした)")

    print(f"\n{'-'*78}")
    print(f"見込み一覧・参考候補(対象: {target.name}、OSM展望データ由来・星空適性は未検証、上位{top_n_reference}件)")
    print(f"{'-'*78}")
    if reference:
        _print_outlook_items(reference, target, top_n_reference)
    else:
        print("\n  該当なし")


def _print_final_items(finals: list[FinalCandidate], target, top_n: int) -> None:
    for i, f in enumerate(finals[:top_n], 1):
        terrain_note = (f"地形地平線 {f.horizon_alt:.1f}°を{f.target_alt - f.horizon_alt:.1f}°上回る"
                         if f.terrain_available else "地形データなし(未評価)")
        print(f"\n[{i}位] スコア {f.score:.1f}")
        print(f"  日付      : {f.night_date}")
        print(f"  地点      : {f.site_name}（{f.municipality}）")
        print(f"  由来      : {ORIGIN_LABELS.get(f.origin, f.origin)}")
        print(f"  推奨時間帯 : {f.window_start.strftime('%H:%M')} 〜 {f.window_end.strftime('%H:%M')}"
              f"（狙い目 {f.best_time.strftime('%H:%M')} 頃、月の影響小 {f.moon_free_hours:.1f}時間）")
        print(f"  {target.name}: 方位角{f.target_az:.0f}° / 高度{f.target_alt:.1f}°({terrain_note})")
        print(f"  条件要約  : 視界遮蔽雲量 平均{f.mean_obstruction:.0f}% / 光害LPI {f.lpi:.2f} / "
              f"実効的な空の明るさ {f.effective_mpsas:.2f} mag/arcsec^2")


def print_final_report(finals: list[FinalCandidate], top_n: int = 20, top_n_reference: int = 10) -> None:
    target = get_target(TARGET_ID)
    primary = sorted((f for f in finals if is_primary_origin(f.origin)), key=lambda f: f.score, reverse=True)
    reference = sorted((f for f in finals if not is_primary_origin(f.origin)), key=lambda f: f.score, reverse=True)

    print(f"\n{'='*78}")
    print(f"探索モード 最終候補一覧・主要候補(対象: {target.name}、星空撮影名所ベース、スコア順、上位{top_n}件)")
    print(f"{'='*78}")
    if primary:
        _print_final_items(primary, target, top_n)
    else:
        print("\n  該当なし(主要候補=curated由来の地点で条件を満たすものがありませんでした)")

    print(f"\n{'='*78}")
    print(f"探索モード 最終候補一覧・参考候補(対象: {target.name}、OSM展望データ由来・星空適性は未検証、上位{top_n_reference}件)")
    print(f"{'='*78}")
    if reference:
        _print_final_items(reference, target, top_n_reference)
    else:
        print("\n  該当なし")


def main() -> None:
    t_start = time.time()

    ts = load.timescale()
    eph = load(str(ROOT / "step1_astronomy" / "de421.bsp"))

    sites = load_candidate_sites()
    primary_sites = [s for s in sites if is_primary_origin(s["origin"])]
    reference_sites = [s for s in sites if not is_primary_origin(s["origin"])]
    print(f"候補地点(stargazing_spots.json): 主要候補(星空撮影名所ベース) {len(primary_sites)}件"
          f" + 参考候補(OSM展望データ) {len(reference_sites)}件 = 計{len(sites)}件を読み込み"
          f"(うち地形地平線データあり: {sum(1 for s in sites if s['horizon_csv'])}件)\n")

    cache = GridCloudCache()
    lp_store = LightPollutionTileStore(cache_dir=str(ROOT / "step3_light_pollution" / "tile_cache"), year=2025)

    ref_site = next(s for s in sites if s["name"] == "石廊崎")
    nights = stage1_moon_filter(ts, eph, ref_site["lat"], ref_site["lon"])

    msm_nights = [n for n in nights if forecast_regime_for_night(cache, ref_site, n) == "MSM"]
    ecmwf_nights = [n for n in nights if n not in msm_nights]

    print(f"\n[リードタイム判定] 候補{len(nights)}夜のうち、MSM精密予報圏内(起点から約75時間以内)は"
          f" {len(msm_nights)}夜、それ以降のECMWF見込み圏内は {len(ecmwf_nights)}夜")

    print(f"\n{'='*78}")
    print(f"探索モード レポート: 直近{len(msm_nights)}日分は精密予報、それ以降{len(ecmwf_nights)}日分は"
          f"天文条件による見込み、の2部構成")
    print(f"{'='*78}")

    t_stage2_start = time.time()
    if msm_nights:
        survivors = stage2_cloud_filter(ts, eph, msm_nights, sites, cache)
        finals = stage3_direction_filter(ts, eph, survivors, lp_store)
        print_final_report(finals)
    else:
        finals = []
        print("\n[精密予報パート] 該当する候補夜がありません(現時点では候補日が全てMSM予報期間の外)。")
    t_stage2_end = time.time()

    if ecmwf_nights:
        outlooks = stage_outlook(ts, eph, ecmwf_nights, sites, lp_store, cache)
        print_outlook_report(outlooks)
    else:
        outlooks = []
        print("\n[見込みパート] 該当する候補夜がありません。")

    t_end = time.time()
    print(f"\n{'='*78}")
    print(f"実行時間: 全体 {(t_end - t_start)/60:.1f}分"
          f"(うち雲量取得 {(t_stage2_end - t_stage2_start)/60:.1f}分)")
    print(f"格子セルキャッシュ最終統計: API呼び出し{cache.call_count}回 / キャッシュヒット{cache.cache_hit_count}回")


if __name__ == "__main__":
    main()
