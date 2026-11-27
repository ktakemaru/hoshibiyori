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
  horizon_profileフィールドに既に反映済み(stargazing_spots.json生成時に
  candidate_sites.dbとの照合・統合済みのため、本ファイル側で名前引きし直す必要はない)。
  候補地点DB自体(step7_geocoding/candidate_sites.db)はこのファイルからは直接参照しない。
エリア代表点による事前スクリーニングは今回は見送り、格子セルキャッシュのみのシンプルな構成。
"""
from __future__ import annotations

import csv
import json
import math
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parent
for sub in ["step1_astronomy", "step2_terrain", "step3_light_pollution", "step4_moonlight", "step5_cloud_forecast"]:
    sys.path.insert(0, str(ROOT / sub))

from skyfield import almanac  # noqa: E402
from skyfield.api import wgs84  # noqa: E402

from catalog import get_target  # noqa: E402
from sky_engine import altaz_at_time  # noqa: E402
from lp_source import LP_INDEX_LIMIT, BmLightPollutionStore, describe_alr  # noqa: E402
from moon_position import compute_moon_position  # noqa: E402
from elevation_cloud import get_level_cloud_forecast, hourly_sky_obstruction_and_cloud_sea, level_hourly_vars  # noqa: E402
from grid_cache import FAILED_CELL_RATE_ABORT, GridCloudCache, timing_line  # noqa: E402
from cloud_forecast import MSM_MAX_FORECAST_DAYS, MSM_MODEL, OpenMeteoDailyLimitError  # noqa: E402
from hb_paths import DATA_ROOT, ephemeris_load as load  # noqa: E402
from astro_grid_cache import ASTRO_GRID_MODES, DEFAULT_ASTRO_GRID, AstroNightCache, make_conditions  # noqa: E402

JST = timezone(timedelta(hours=9))

# --- パラメータ(既定値) ---
NUM_NIGHTS_TO_SCAN = 14
NUM_CANDIDATE_NIGHTS = 6
CLOUD_OBSTRUCTION_THRESHOLD = 30.0
MIN_CLEAR_WINDOW_HOURS = 1.0  # これ未満の晴れ間は「見頃」として採用しない(2026-09-07追加)
MOON_PHASE_NEGLIGIBLE_DEG = 150.0
MOON_SAMPLE_INTERVAL_MIN = 15  # longest_negligible_window の既定のサンプル間隔(保存の鍵に入れる)
EPHEMERIS_FILE = "de421.bsp"
TARGET_ID = "galactic_center"
# 探索の目的。"milkyway"=天の川(銀河中心の高度・方角・地形を条件にする、既定)、
# "stars"=星空・星座(銀河中心の条件を使わず、雲・月・光害・暗い時間帯だけで選ぶ)
TARGET_MODES = ("milkyway", "stars")
DEFAULT_TARGET_MODE = "milkyway"
# milkywayモードの候補がこの件数未満のとき、starsモードの案内を1行出す
MILKYWAY_FEW_RESULTS = 5

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
        "id": entry.get("id"),      # 変わらないID(AGENTS.md 第6節。2026-11-24)
        "name": name, "lat": entry["lat"], "lon": entry["lon"], "elevation_m": elevation_m,
        "municipality": entry.get("municipality") or "不明",
        "origin": entry["origin"],
        "horizon_csv": entry.get("horizon_profile"),
        "requires_lift_access": entry.get("requires_lift_access", False),
        # classify_site_darkness.py(2026-09-07)がspots配列(curated由来)に事前計算した分類。
        # viewpoint_reference側には無いため未計算の地点はNone(まだ「night_view」と決めつけない)。
        "site_type": entry.get("site_type"),
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


# 空の開け具合(2026-11-24)。順位・足切りには使わない。
SKY_OPEN_ALT_DEG = 20.0  # 稜線がこの高度以下の方位を「開けている」と数える(仮の値)
_sky_openness_cache: dict[str, dict] = {}


def sky_openness_of(profile: dict[int, float]) -> dict:
    """地形の地平線(方位ごとの稜線の高度)から、稜線の平均・最大と、高度 SKY_OPEN_ALT_DEG より上が開けている方位の割合。"""
    values = list(profile.values())
    return {"ridge_mean_deg": sum(values) / len(values), "ridge_max_deg": max(values),
            "open_fraction": sum(v <= SKY_OPEN_ALT_DEG for v in values) / len(values),
            "open_alt_deg": SKY_OPEN_ALT_DEG}


def sky_openness(site: dict) -> dict | None:
    """地形の地平線のデータがある地点だけ。無ければ None。"""
    csv_path = site.get("horizon_csv")
    if not csv_path:
        return None
    if csv_path not in _sky_openness_cache:
        _sky_openness_cache[csv_path] = sky_openness_of(load_horizon_profile(csv_path))
    return dict(_sky_openness_cache[csv_path])


def sky_openness_text(openness: dict | None) -> str | None:
    """「稜線の平均 8°・最大 24°」。データの無い地点は None(表示しない)。"""
    if openness is None:
        return None

    def deg(x: float) -> str:
        return f"{round(x) + 0:d}°"
    return f"稜線の平均 {deg(openness['ridge_mean_deg'])}・最大 {deg(openness['ridge_max_deg'])}"


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


def _moon_negligible_flags(ts, eph, lat: float, lon: float, times_local: list[datetime]) -> list[bool]:
    """各時刻について「月が地平線下、または新月に近く影響が小さい」か(compute_moon_position(標高0m)と同じ式)。

    時刻の配列を1回でSkyfieldに渡す。式は moon_position.compute_moon_position と同じ
    (高度<=0、または 位相角=180-月と太陽の離角 >= MOON_PHASE_NEGLIGIBLE_DEG)。
    """
    if not times_local:
        return []
    t = ts.from_datetimes([x.astimezone(timezone.utc) for x in times_local])
    observer = eph["earth"] + wgs84.latlon(lat, lon, elevation_m=0.0)
    at = observer.at(t)
    moon = at.observe(eph["moon"]).apparent()
    alt, _az, _ = moon.altaz()
    sun = at.observe(eph["sun"]).apparent()
    phase_angle = 180.0 - moon.separation_from(sun).degrees
    return [bool(a <= 0 or p >= MOON_PHASE_NEGLIGIBLE_DEG) for a, p in zip(alt.degrees, phase_angle)]


def longest_negligible_window(ts, eph, ref_lat: float, ref_lon: float, sunset: datetime, sunrise: datetime,
                               sample_interval_min: int = MOON_SAMPLE_INTERVAL_MIN) -> tuple[datetime | None, datetime | None, float]:
    sample_times = []
    t = sunset
    while t <= sunrise:
        sample_times.append(t)
        t += timedelta(minutes=sample_interval_min)
    # 月の高度・位相角は、compute_moon_position と同じ計算を時刻の配列でまとめて行う(2026-11-12、処理時間の短縮。
    # 1時刻ずつ呼ぶと地点×夜ごとに数十回のSkyfield呼び出しになっていた)。判定の式・サンプル間隔は同じ。
    flags = _moon_negligible_flags(ts, eph, ref_lat, ref_lon, sample_times)
    samples = list(zip(sample_times, flags))

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


def compute_site_night_window(ts, eph, site: dict, night_date: date,
                              astro: AstroNightCache | None = None) -> tuple[datetime | None, datetime | None, float]:
    """指定地点・指定夜について、天文薄明・無月時間帯を計算する。

    石廊崎1地点の座標を全候補地点で使い回すと、経度差による薄明・月の出没時刻のずれ
    (石廊崎〜佐渡・立山で数分〜十数分程度)が無視されるため、地点ごとに計算し直す
    (2026-09-07追加。night_dateの選定自体は引き続き石廊崎基準で行うが、実際の
    「見頃」区間・雲量取得範囲はこの関数の結果を使う)。

    2026-11-13(本人の決定): astro(AstroNightCache)を渡すと、地点ではなく0.25度格子(ECMWFと同じ切り方)の
    代表点で計算し、同じセルの地点で結果を使い回す(保存済みがあれば読むだけ)。astro=None は従来どおり
    地点自身の座標で計算する(`--astro-grid site`)。
    """
    if astro is not None:
        return astro.site_night_window(ts, eph, site, night_date)
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
    target_az: float | None             # starsモードではNone(銀河中心を評価しない)
    target_alt: float | None
    horizon_alt: float | None
    terrain_available: bool
    mean_obstruction: float
    lp_index: float                     # 光害の内部値(足切り・減点用。画面には出さない。lp_source.py)
    moon_free_hours: float
    clear_hours: float
    score: float = 0.0
    alr: float | None = None            # 光害(相対指数ALR)
    alr_rank_pct: float | None = None
    site_id: str | None = None          # 地点の変わらないID(2026-11-24)
    sky_openness: dict | None = None    # 空の開け具合(地形データの無い地点は None。順位には使わない。2026-11-24)


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
    lp_index: float
    clear_sky_pct: float | None
    moon_free_hours: float
    score: float = 0.0
    alr: float | None = None
    alr_rank_pct: float | None = None
    site_id: str | None = None
    sky_openness: dict | None = None


def make_lp_store() -> BmLightPollutionStore:
    """光害の入力(Black Marble由来のALR。日本で未較正の相対指数)。get(lat, lon) の brightness_ratio が
    `<= LP_INDEX_LIMIT` で足切りに使われる(ALRの仮閾値と同じ位置になるように規格化した内部値)。"""
    return BmLightPollutionStore()


def lp_limit_text(lp_store) -> str:
    """足切りの条件の表記(コンソール用)。"""
    return f"ALR<={lp_store.alr_threshold}(仮閾値・相対指数)"


class ReferenceForecastUnavailable(RuntimeError):
    """MSMの範囲内かを決める基準地点(石廊崎)のMSMのセルが、取得の失敗で空だったことを表す(2026-11-13)。

    この場合は夜を見込み側に回さず中止する(終了コード2)。「取得はできたが、その夜はMSMの範囲の外」とは区別する。
    """


REFERENCE_UNAVAILABLE_MESSAGE = "基準地点の予報を取得できなかったため中止します"


def forecast_regime_for_night(cache: GridCloudCache, ref_site: dict, night: "NightCandidate") -> str:
    """候補夜がMSM(精密)圏内かECMWF(見込み)圏内かを、実際のフォールバック結果から判定する。

    cloud_forecast.py/elevation_cloud.pyの結合ロジックが各時刻に付与するsource
    ("MSM"/"ECMWF")の多数決で判定する(既存のフォールバック判定をそのまま流用)。
    基準地点のMSMのセルが取得の失敗で空のときは ReferenceForecastUnavailable を投げる(2026-11-13)。
    """
    levels = get_level_cloud_forecast(ref_site["lat"], ref_site["lon"], night.window_start, night.window_end, cache=cache)
    fetch_failed = getattr(cache, "fetch_failed", None)
    if fetch_failed is not None and fetch_failed(ref_site["lat"], ref_site["lon"], MSM_MODEL,
                                                 MSM_MAX_FORECAST_DAYS, level_hourly_vars()):
        raise ReferenceForecastUnavailable(
            f"{REFERENCE_UNAVAILABLE_MESSAGE}(基準地点 {ref_site['name']} のMSMのセルの取得に失敗したため、"
            "MSMの範囲内かを決められません)")
    if not levels:
        return "ECMWF"
    msm_count = sum(1 for l in levels if l.source == "MSM")
    return "MSM" if msm_count > len(levels) / 2 else "ECMWF"


def compute_target_window(ts, eph, site: dict, target, window_start: datetime, window_end: datetime,
                           profile: dict[int, float] | None, sample_interval_min: int = 15):
    """月・地形から決まる、その夜・その地点での対象天体の「見頃時間帯」を求める(決定論的)。

    window_start/window_endはその地点自身の座標で計算した無月時間帯(compute_site_night_window参照)。
    地形地平線を上回っている(profileが無ければ高度0°を上回っている)連続区間のうち
    最長のものを返す。戻り値: (見頃開始, 見頃終了, 見頃内で最も高度が高い時刻とその高度・方位角)。

    2026-11-27(処理時間の短縮): 時刻の列を Skyfield に1回で渡して(方位, 高度)をまとめて計算し、見える・見えないの
    判定と最も高い時刻の選択に使う。まとめた計算は1時刻ずつの計算と末尾の桁で違うことがあるため、
    - 返す高度・方位は、選んだ時刻だけを従来と同じ1時刻の計算でやり直した値にする(値は従来と1ビットも違わない)。
    - 判定が末尾の桁で入れ替わりうるサンプル(地平線・稜線の高度との差、稜線の方位の丸めの境目[x.5°]との差、
      最も高い2つの時刻の高度の差が TARGET_TRACK_GUARD_DEG 未満)が1つでもあれば、従来の1時刻ずつの計算
      (_compute_target_window_scalar)に切り替える。決まり・刻み・閾値は変えていない。
    """
    times, t_sf = _sample_times(ts, window_start, window_end, sample_interval_min)
    if not times:
        return None, None, None, None, None
    az_arr, alt_arr = altaz_at_time(t_sf, eph, site["lat"], site["lon"], site["elevation_m"], target)
    az_list = [float(a) for a in az_arr]
    alt_list = [float(a) for a in alt_arr]

    guard = TARGET_TRACK_GUARD_DEG
    visible_flags = []
    for az, alt in zip(az_list, alt_list):
        if profile is not None:
            frac = az - math.floor(az)
            if abs(frac - 0.5) < guard:
                return _target_window_fallback(ts, eph, site, target, window_start, window_end, profile, sample_interval_min)
            horizon = horizon_alt_at(profile, az)
        else:
            horizon = 0.0
        if abs(alt - horizon) < guard:
            return _target_window_fallback(ts, eph, site, target, window_start, window_end, profile, sample_interval_min)
        visible_flags.append(alt > horizon)

    # 最長の連続区間(従来と同じ決まり。時刻の列と見える・見えないの並びだけで決まる)
    best_start, best_end, best_len = None, None, timedelta(0)
    cur_start = None
    for t, vis in zip(times, visible_flags):
        if vis and cur_start is None:
            cur_start = t
        elif not vis and cur_start is not None:
            length = t - cur_start
            if length > best_len:
                best_start, best_end, best_len = cur_start, t, length
            cur_start = None
    if cur_start is not None:
        length = times[-1] - cur_start
        if length > best_len:
            best_start, best_end = cur_start, times[-1]

    if best_start is None:
        return None, None, None, None, None

    in_window = [i for i, t in enumerate(times) if best_start <= t <= best_end]
    peak_i = max(in_window, key=lambda i: alt_list[i])   # 同じ高さなら先の時刻(従来の max と同じ)
    others = [alt_list[i] for i in in_window if i != peak_i]
    if others and alt_list[peak_i] - max(others) < guard:
        return _target_window_fallback(ts, eph, site, target, window_start, window_end, profile, sample_interval_min)
    peak_time = times[peak_i]
    # 返す値は、従来と同じ1時刻の計算でやり直す
    peak_az, peak_alt = altaz_at_time(ts.from_datetime(peak_time.astimezone(timezone.utc)), eph,
                                      site["lat"], site["lon"], site["elevation_m"], target)
    return best_start, best_end, peak_time, peak_az, peak_alt


# まとめた計算と1時刻ずつの計算の差(実測で約1e-13°)より十分大きく、判定の入れ替わりを防ぐための余裕(度)。
# この余裕の中にサンプルがあれば従来の計算に切り替えるだけで、判定の決まりそのものには使わない。
TARGET_TRACK_GUARD_DEG = 1e-6
# 従来の計算に切り替えた回数(確かめ用。結果には使わない)
target_window_fallbacks = 0

# 時刻の列の使い回し(同じ夜・同じ格子の地点は時間帯が同じ)。鍵には時刻の表し方(タイムゾーン)も入れる
# (同じ瞬間でもタイムゾーンが違えば返す時刻の表示が変わるため)。大きくなりすぎたら空にする。
_SAMPLE_TIMES_MEMO: dict = {}
_SAMPLE_TIMES_MEMO_MAX = 4096
sample_times_stats = {"hits": 0, "misses": 0}


def _sample_times(ts, start: datetime, end: datetime, interval_min: int):
    """start から end まで(end を含む)interval_min 分刻みの時刻のリストと、その Skyfield の Time(配列)。"""
    key = (id(ts), start, repr(start.tzinfo), end, repr(end.tzinfo), interval_min)
    hit = _SAMPLE_TIMES_MEMO.get(key)
    if hit is not None and hit[0] is ts:
        sample_times_stats["hits"] += 1
        return hit[1], hit[2]
    sample_times_stats["misses"] += 1
    times = []
    t = start
    while t <= end:
        times.append(t)
        t += timedelta(minutes=interval_min)
    t_sf = ts.from_datetimes([x.astimezone(timezone.utc) for x in times]) if times else None
    if len(_SAMPLE_TIMES_MEMO) >= _SAMPLE_TIMES_MEMO_MAX:
        _SAMPLE_TIMES_MEMO.clear()
    _SAMPLE_TIMES_MEMO[key] = (ts, times, t_sf)
    return times, t_sf


def _target_window_fallback(ts, eph, site, target, window_start, window_end, profile, sample_interval_min):
    global target_window_fallbacks
    target_window_fallbacks += 1
    return _compute_target_window_scalar(ts, eph, site, target, window_start, window_end, profile, sample_interval_min)


def _compute_target_window_scalar(ts, eph, site: dict, target, window_start: datetime, window_end: datetime,
                                  profile: dict[int, float] | None, sample_interval_min: int = 15):
    """従来(1.2.0まで)の1時刻ずつの計算。compute_target_window の切り替え先と、テストでの照合に使う。"""
    samples = []
    t = window_start
    while t <= window_end:
        t_sf = ts.from_datetime(t.astimezone(timezone.utc))
        az, alt = altaz_at_time(t_sf, eph, site["lat"], site["lon"], site["elevation_m"], target)
        if profile is not None:
            visible = alt > horizon_alt_at(profile, az)
        else:
            # 2026-11-16(利用者の承認): 地形データが無い地点は、地平線を水平(高度0°)として判定する。
            # 地形があれば稜線は0°より高いので、0°は「これより下では見えない」下限。以前は高度を見ずに
            # 常に見える扱いで、銀河中心が地平線の下の時期でも候補になっていた。新しい閾値は作らない(0°だけ)。
            visible = alt > 0.0
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


def reference_night(ts, eph, lat: float, lon: float, day: datetime) -> dict:
    """基準地点の1夜分(日没・日の出・天文薄明・無月時間帯)。stage1_moon_filter と all_nights_timeline が使う。

    日没・日の出が無い夜は他の値も None、暗い区間が無い夜は無月時間帯を None・0.0 にする
    (2026-11-13、保存の仕組みに入れるため1つにまとめた。計算の順と中身は従来と同じ)。
    """
    sunset, sunrise = find_sun_events(ts, eph, lat, lon, day)
    out = {"sunset": sunset, "sunrise": sunrise, "dark_start": None, "dark_end": None,
           "window_start": None, "window_end": None, "hours": 0.0}
    if sunset is None or sunrise is None:
        return out
    dark_start, dark_end = find_astro_dark_events(ts, eph, lat, lon, day)
    out["dark_start"], out["dark_end"] = dark_start, dark_end
    if dark_start is not None and dark_end is not None:
        w_start, w_end, hours = longest_negligible_window(ts, eph, lat, lon, dark_start, dark_end)
        out["window_start"], out["window_end"], out["hours"] = w_start, w_end, hours
    return out


def _reference_night(ts, eph, lat: float, lon: float, day: datetime, astro: AstroNightCache | None) -> dict:
    if astro is not None:
        return astro.reference_night(ts, eph, lat, lon, day)
    return reference_night(ts, eph, lat, lon, day)


# 走査した夜が候補の夜に選ばれなかった理由のコード(--json-out の scanned_nights 用、2026-11-16)。
# stage1_moon_filter の分かれ方(continue の3か所と、上位N夜の切り捨て)にそのまま対応する。
NOT_SELECTED_NO_SUN_EVENTS = "no_sunset_or_sunrise"        # 日没・日の出が求まらない
NOT_SELECTED_NO_DARKNESS = "no_astronomical_darkness"      # 天文薄明の終わり・始まりが求まらない
NOT_SELECTED_NO_MOON_FREE = "no_moon_free_window"          # 月の影響が小さい時間帯が無い
NOT_SELECTED_NOT_IN_TOP_N = "not_in_top_n"                 # 時間帯はあるが、長さの順で上位N夜に入らなかった
NOT_SELECTED_REASONS = (NOT_SELECTED_NO_SUN_EVENTS, NOT_SELECTED_NO_DARKNESS,
                        NOT_SELECTED_NO_MOON_FREE, NOT_SELECTED_NOT_IN_TOP_N)


def stage1_moon_filter(ts, eph, ref_lat: float, ref_lon: float,
                       astro: AstroNightCache | None = None,
                       scan_out: list | None = None) -> list[NightCandidate]:
    """scan_out にリストを渡すと、走査した全部の夜を日付順に (NightCandidate, 選ばれなかった理由 or None) で足す
    (2026-11-16、--json-out の scanned_nights 用)。計算は増えず(ループで既に求めた値を写すだけ)、
    選び方・並び・表示は渡さないときと同じ。"""
    today = datetime.now(JST).replace(hour=0, minute=0, second=0, microsecond=0)
    candidates = []
    scanned: list[tuple[NightCandidate, str | None]] = []
    for i in range(NUM_NIGHTS_TO_SCAN):
        day = today + timedelta(days=i)
        r = _reference_night(ts, eph, ref_lat, ref_lon, day, astro)
        sunset, sunrise = r["sunset"], r["sunrise"]
        if sunset is None or sunrise is None:
            if scan_out is not None:
                scanned.append((NightCandidate(day.date(), sunset, sunrise, None, None, None, None, None),
                                NOT_SELECTED_NO_SUN_EVENTS))
            continue
        dark_start, dark_end = r["dark_start"], r["dark_end"]
        if dark_start is None or dark_end is None:
            if scan_out is not None:
                scanned.append((NightCandidate(day.date(), sunset, sunrise, dark_start, dark_end, None, None, None),
                                NOT_SELECTED_NO_DARKNESS))
            continue
        w_start, w_end, hours = r["window_start"], r["window_end"], r["hours"]
        if w_start is None:
            if scan_out is not None:
                # 時間帯が無い夜の長さは 0.0(reference_night の値をそのまま。時刻は null)
                scanned.append((NightCandidate(day.date(), sunset, sunrise, dark_start, dark_end, None, None, hours),
                                NOT_SELECTED_NO_MOON_FREE))
            continue
        candidates.append(NightCandidate(
            night_date=day.date(), sunset=sunset, sunrise=sunrise,
            dark_start=dark_start, dark_end=dark_end,
            window_start=w_start, window_end=w_end, moon_free_hours=hours,
        ))
        if scan_out is not None:
            scanned.append((candidates[-1], None))

    candidates.sort(key=lambda c: c.moon_free_hours, reverse=True)
    top = candidates[:NUM_CANDIDATE_NIGHTS]
    if scan_out is not None:
        top_ids = {id(c) for c in top}
        scan_out.extend((n, reason if reason is not None or id(n) in top_ids else NOT_SELECTED_NOT_IN_TOP_N)
                        for n, reason in scanned)

    print(f"[第1段階: 月フィルタ] 直近{NUM_NIGHTS_TO_SCAN}夜を評価 -> "
          f"月の影響が小さい時間帯が長い順に上位{len(top)}夜を候補日とする")
    for c in top:
        print(f"    {c.night_date}  無月時間帯 {c.window_start.strftime('%H:%M')}"
              f"-{c.window_end.strftime('%H:%M(翌)') if c.window_end.date()!=c.window_start.date() else c.window_end.strftime('%H:%M')}"
              f"  ({c.moon_free_hours:.1f}時間)")
    return top


def all_nights_timeline(ts, eph, ref_lat: float, ref_lon: float,
                         num_nights: int = NUM_NIGHTS_TO_SCAN,
                         astro: AstroNightCache | None = None) -> list[NightCandidate]:
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
        r = _reference_night(ts, eph, ref_lat, ref_lon, day, astro)
        sunset, sunrise = r["sunset"], r["sunrise"]
        if sunset is None or sunrise is None:
            continue
        dark_start, dark_end = r["dark_start"], r["dark_end"]
        w_start, w_end, hours = r["window_start"], r["window_end"], r["hours"]
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


def stage2_cloud_filter(ts, eph, nights: list[NightCandidate], sites: list[dict], cache: GridCloudCache,
                        astro: AstroNightCache | None = None) -> list[dict]:
    survivors = []
    total_pairs = 0
    for night in nights:
        for i, site in enumerate(sites):
            total_pairs += 1
            w_start, w_end, hours = compute_site_night_window(ts, eph, site, night.night_date, astro)
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


# 星空・星座モード(--target stars)の一覧の見出しの語(2026-11-16)。対象の語は generate_report.py の星空・星座モードに
# 合わせ、並び順の説明は final_rank_key / outlook_rank_key の星空・星座モードの順に合わせる。
STARS_HEADING_TARGET = "星空・星座モード・天の川は対象外"
STARS_FINAL_ORDER = "晴れ時間が長い→平均雲量が低い→光害(ALR)が小さい→月の影響が小さい時間が長い順"
STARS_OUTLOOK_ORDER = "光害(ALR)が小さい→月の影響が小さい時間が長い順"


def final_score(mean_obstruction: float, best_alt: float, h_alt: float | None, clear_hours: float,
                brightness_ratio: float) -> float:
    """近日中(FinalCandidate.score、天の川モード)のスコア。式は 1.2.0 の stage3_direction_filter のまま
    (2026-11-27 に関数へ移しただけ。聞かれた夜の順位 night_rank でも同じ式を使うため)。"""
    return (
        (100.0 - mean_obstruction) * 1.0
        + max(0.0, best_alt - (h_alt or 0.0)) * 0.5
        + clear_hours * 3.0
        - brightness_ratio * 10.0
    )


def outlook_score(brightness_ratio: float, peak_alt: float, horizon_alt: float, moon_free_hours: float) -> float:
    """見込み(OutlookCandidate.score、天の川モード)のスコア。horizon_alt は最も高い時刻の方位の稜線(地形データが無ければ 0.0)。
    式は 1.2.0 の stage_outlook のまま(2026-11-27 に関数へ移しただけ)。"""
    return (
        (100.0 - brightness_ratio * 10.0)
        + max(0.0, peak_alt - horizon_alt) * 0.5
        + moon_free_hours * 3.0
    )


def peak_altitude_scalar(ts, eph, site: dict, target, window_start: datetime, window_end: datetime,
                         sample_interval_min: int = 15):
    """時間帯の中で対象天体が最も高い時刻(15分刻み、同じ高さなら先の時刻)の (高度, 方位, 時刻)。サンプルが無ければ
    (-90.0, None, None)。1.2.0 の stage3_direction_filter のループのまま(2026-11-27 に関数へ移しただけ)。"""
    best_alt, best_az, best_time = -90.0, None, None
    t = window_start
    while t <= window_end:
        t_sf = ts.from_datetime(t.astimezone(timezone.utc))
        az, alt = altaz_at_time(t_sf, eph, site["lat"], site["lon"], site["elevation_m"], target)
        if alt > best_alt:
            best_alt, best_az, best_time = alt, az, t
        t += timedelta(minutes=sample_interval_min)
    return best_alt, best_az, best_time


def peak_altitude(ts, eph, site: dict, target, window_start: datetime, window_end: datetime,
                  sample_interval_min: int = 15):
    """peak_altitude_scalar と同じ結果を、時刻の列をまとめた計算で速く求める(聞かれた夜の順位で使う)。
    最も高い2時刻の差が TARGET_TRACK_GUARD_DEG 未満なら peak_altitude_scalar に切り替える。返す値は選んだ時刻の1時刻の計算。"""
    times, t_sf = _sample_times(ts, window_start, window_end, sample_interval_min)
    if not times:
        return -90.0, None, None
    _az, alt_arr = altaz_at_time(t_sf, eph, site["lat"], site["lon"], site["elevation_m"], target)
    alts = [float(a) for a in alt_arr]
    best_i = max(range(len(alts)), key=lambda i: alts[i])      # 同じ高さなら先の時刻
    others = [a for i, a in enumerate(alts) if i != best_i]
    if (others and alts[best_i] - max(others) < TARGET_TRACK_GUARD_DEG) or alts[best_i] - (-90.0) < TARGET_TRACK_GUARD_DEG:
        return peak_altitude_scalar(ts, eph, site, target, window_start, window_end, sample_interval_min)
    best_time = times[best_i]
    az, alt = altaz_at_time(ts.from_datetime(best_time.astimezone(timezone.utc)), eph,
                            site["lat"], site["lon"], site["elevation_m"], target)
    return alt, az, best_time


def final_rank_key(f: "FinalCandidate", target_mode: str = DEFAULT_TARGET_MODE):
    """降順ソート用のキー(大きいほど上位)。milkywayは従来のスコア。
    starsは、晴れ時間が長い → 平均雲量が低い → ALRが小さい → 月の影響が小さい時間が長い、の辞書式順序。"""
    if target_mode == "stars":
        return (f.clear_hours, -f.mean_obstruction, -(f.alr if f.alr is not None else f.lp_index), f.moon_free_hours)
    return (f.score,)


def outlook_rank_key(o: "OutlookCandidate", target_mode: str = DEFAULT_TARGET_MODE):
    """見込み(ECMWF)側。starsは雲を使わないため、ALRが小さい → 月の影響が小さい時間が長い、の順。"""
    if target_mode == "stars":
        return (-(o.alr if o.alr is not None else o.lp_index), o.moon_free_hours)
    return (o.score,)


def stage3_direction_filter(ts, eph, survivors: list[dict], lp_store: BmLightPollutionStore,
                            target_mode: str = DEFAULT_TARGET_MODE) -> list[FinalCandidate]:
    stars_mode = target_mode == "stars"
    target = get_target(TARGET_ID)
    finals = []
    horizon_profile_cache: dict[str, dict[int, float]] = {}
    no_terrain_count = 0

    for s in survivors:
        night: NightCandidate = s["night"]
        site = s["site"]
        window_start, window_end, moon_free_hours = s["window_start"], s["window_end"], s["moon_free_hours"]

        lp_result = lp_store.get(site["lat"], site["lon"])

        if stars_mode:
            # 銀河中心の高度・方角・地形(稜線)は評価しない。光害だけ足切りに使う。
            if lp_result.brightness_ratio <= LP_INDEX_LIMIT:
                finals.append(FinalCandidate(
                    night_date=night.night_date, site_name=site["name"], municipality=site["municipality"],
                    origin=site["origin"], site_lat=site["lat"], site_lon=site["lon"],
                    requires_lift_access=site["requires_lift_access"],
                    window_start=window_start, window_end=window_end,
                    best_time=window_start, target_az=None, target_alt=None,
                    horizon_alt=None, terrain_available=False,
                    mean_obstruction=s["mean_obstruction"], lp_index=lp_result.brightness_ratio,
                    moon_free_hours=moon_free_hours, clear_hours=s["clear_hours"], score=0.0,
                    alr=lp_result.alr, alr_rank_pct=lp_result.rank_pct, site_id=site.get("id"),
                    sky_openness=sky_openness(site),
                ))
            continue

        profile = None
        if site["horizon_csv"]:
            if site["horizon_csv"] not in horizon_profile_cache:
                horizon_profile_cache[site["horizon_csv"]] = load_horizon_profile(site["horizon_csv"])
            profile = horizon_profile_cache[site["horizon_csv"]]

        best_alt, best_az, best_time = peak_altitude_scalar(ts, eph, site, target, window_start, window_end)

        if best_time is None:
            continue

        clears_light_pollution = lp_result.brightness_ratio <= LP_INDEX_LIMIT

        if profile is not None:
            h_alt = horizon_alt_at(profile, best_az)
            clears_horizon = best_alt > h_alt
            terrain_available = True
        else:
            h_alt = None
            # 2026-11-16(利用者の承認): 地形データが無い地点は、地平線を水平(高度0°)として判定する
            # (以前は判定をスキップして通過扱い)。horizon_alt は従来どおり None のまま(0 を入れない)。
            clears_horizon = best_alt > 0.0
            terrain_available = False

        if clears_horizon and clears_light_pollution:
            if not terrain_available:
                no_terrain_count += 1   # 通過した候補のうち地形データが無いもの(2026-11-24、光害の足切りの後に数える)
            score = final_score(s["mean_obstruction"], best_alt, h_alt, s["clear_hours"], lp_result.brightness_ratio)
            finals.append(FinalCandidate(
                night_date=night.night_date, site_name=site["name"], municipality=site["municipality"],
                origin=site["origin"], site_lat=site["lat"], site_lon=site["lon"],
                requires_lift_access=site["requires_lift_access"],
                window_start=window_start, window_end=window_end,
                best_time=best_time, target_az=best_az, target_alt=best_alt,
                horizon_alt=h_alt, terrain_available=terrain_available,
                mean_obstruction=s["mean_obstruction"], lp_index=lp_result.brightness_ratio,
                moon_free_hours=moon_free_hours, clear_hours=s["clear_hours"], score=score,
                alr=lp_result.alr, alr_rank_pct=lp_result.rank_pct, site_id=site.get("id"),
                sky_openness=sky_openness(site),
            ))

    if stars_mode:
        print(f"\n[第3段階: 光害フィルタ(星空・星座モード)] {len(survivors)}組のうち、"
              f"銀河中心の方角・地形は評価せず、{lp_limit_text(lp_store)}を満たすのは {len(finals)}件")
        return finals
    print(f"\n[第3段階: 方角フィルタ] {len(survivors)}組のうち、"
          f"「{target.name}が地形地平線を上回り(地形データ有りの場合)、かつ{lp_limit_text(lp_store)}」を満たすのは"
          f" {len(finals)}件")
    print(f"    うち地形データなし(地平線を高度0°として判定して通過): {no_terrain_count}件")
    return finals


def stage_outlook(ts, eph, nights: list["NightCandidate"], sites: list[dict],
                   lp_store: BmLightPollutionStore, cache: GridCloudCache,
                   target_mode: str = DEFAULT_TARGET_MODE,
                   astro: AstroNightCache | None = None) -> list[OutlookCandidate]:
    """ECMWF圏内(長期見込み)の夜を処理する。雲量は数値スコア・足切りに使わず、
    月・地形・光害という決定論的要素だけでランキングし、雲は「晴天率」の参考値として添える。
    """
    stars_mode = target_mode == "stars"
    target = get_target(TARGET_ID)
    horizon_profile_cache: dict[str, dict[int, float]] = {}
    results = []

    for night in nights:
        for site in sites:
            # 光害の足切りを天文計算より先に行う(2026-11-12、処理時間の短縮)。光害で落ちる地点は
            # 結果に入らず、ここまでの計算に副作用も無いため、残る候補・順位・表示は同じ。
            lp_result = lp_store.get(site["lat"], site["lon"])
            if lp_result.brightness_ratio > LP_INDEX_LIMIT:
                continue

            w_start, w_end, moon_free_hours = compute_site_night_window(ts, eph, site, night.night_date, astro)
            if w_start is None:
                continue

            profile = None
            if stars_mode:
                # 銀河中心を評価しないので、見どころ区間は暗い無月時間帯そのもの
                v_start, v_end, peak_az, peak_alt = w_start, w_end, None, None
            else:
                if site["horizon_csv"]:
                    if site["horizon_csv"] not in horizon_profile_cache:
                        horizon_profile_cache[site["horizon_csv"]] = load_horizon_profile(site["horizon_csv"])
                    profile = horizon_profile_cache[site["horizon_csv"]]

                v_start, v_end, peak_time, peak_az, peak_alt = compute_target_window(ts, eph, site, target, w_start, w_end, profile)
                if v_start is None:
                    continue

            # 雲量は参考値(晴天率)としてのみ計算し、足切りには使わない
            levels = get_level_cloud_forecast(site["lat"], site["lon"], v_start, v_end, cache=cache)
            rows = hourly_sky_obstruction_and_cloud_sea(levels, site["elevation_m"])
            valid = [r["sky_obstruction"] for r in rows if r["sky_obstruction"] is not None]
            clear_sky_pct = (
                100.0 * sum(1 for v in valid if v <= CLOUD_OBSTRUCTION_THRESHOLD) / len(valid)
                if valid else None
            )

            if stars_mode:
                score = 0.0   # 並び順は outlook_rank_key が決める(銀河中心の項が無いため)
            else:
                score = outlook_score(lp_result.brightness_ratio, peak_alt,
                                      horizon_alt_at(profile, peak_az) if profile is not None else 0.0, moon_free_hours)

            results.append(OutlookCandidate(
                night_date=night.night_date, site_name=site["name"], municipality=site["municipality"],
                origin=site["origin"], site_lat=site["lat"], site_lon=site["lon"],
                requires_lift_access=site["requires_lift_access"],
                visible_start=v_start, visible_end=v_end,
                target_az=peak_az, target_alt=peak_alt,
                horizon_alt=(horizon_alt_at(profile, peak_az) if profile is not None and peak_az is not None else None),
                terrain_available=profile is not None,
                lp_index=lp_result.brightness_ratio,
                clear_sky_pct=clear_sky_pct, moon_free_hours=moon_free_hours, score=score,
                alr=lp_result.alr, alr_rank_pct=lp_result.rank_pct, site_id=site.get("id"),
                sky_openness=sky_openness(site),
            ))

    print(f"\n[見込み(ECMWF圏内)] 候補日{len(nights)}日 × 候補地点{len(sites)}件のうち、"
          f"月・{'光害' if stars_mode else '地形・光害'}の決定論的条件を満たすのは {len(results)}件"
          f"(雲量は足切りに使わず、晴天率として参考表示のみ)")
    return results


# 天の川モードの各候補の行で、地形データの無い地点に付ける注記(2026-11-16。地平線を高度0°として判定している。
# 以前は「地形データなし(未評価)」)。星空・星座モードでは表示しない。
NO_TERRAIN_NOTE = "地形データなし(地平線を高度0°として判定)"


# MSM の範囲の外(ECMWF だけ)の夜に付ける印(2026-11-24)。雲量での足切りが効かず、確かさが低いため
ECMWF_ONLY_NOTE = "ECMWFだけの予報(目安)"


def _print_outlook_items(outlooks: list[OutlookCandidate], target, top_n: int,
                         target_mode: str = DEFAULT_TARGET_MODE) -> None:
    stars_mode = target_mode == "stars"
    for i, o in enumerate(outlooks[:top_n], 1):
        terrain_note = (f"地形地平線{o.horizon_alt:.1f}°を{o.target_alt - o.horizon_alt:.1f}°上回る"
                         if o.terrain_available and o.horizon_alt is not None else NO_TERRAIN_NOTE)
        clear_note = f"参考: この時間帯の晴天率 約{o.clear_sky_pct:.0f}%" if o.clear_sky_pct is not None else "参考: 晴天率データなし"
        print(f"\n[{i}位]" + ("" if stars_mode else f" スコア {o.score:.1f}"))
        print(f"  日付      : {o.night_date} {ECMWF_ONLY_NOTE}")
        print(f"  地点      : {o.site_name}（{o.municipality}）")
        print(f"  由来      : {ORIGIN_LABELS.get(o.origin, o.origin)}")
        if stars_mode:
            print(f"  暗い無月時間帯: {o.visible_start.strftime('%H:%M')} 〜 {o.visible_end.strftime('%H:%M')}")
            if o.sky_openness is not None:
                print(f"  空の開け  : {sky_openness_text(o.sky_openness)}")
        else:
            print(f"  {target.name}の見頃: {o.visible_start.strftime('%H:%M')} 〜 {o.visible_end.strftime('%H:%M')}"
                  f"（{terrain_note}）")
        print(f"  光害(相対指数): {describe_alr(o.alr, o.alr_rank_pct)}")
        print(f"  → 晴れれば {o.visible_start.strftime('%H:%M')}〜{o.visible_end.strftime('%H:%M')} にチャンスがあります。"
              f"({clear_note})")


def print_outlook_report(outlooks: list[OutlookCandidate], top_n: int = 20, top_n_reference: int = 10,
                         target_mode: str = DEFAULT_TARGET_MODE) -> None:
    target = get_target(TARGET_ID)
    primary = sorted((o for o in outlooks if is_primary_origin(o.origin)), key=lambda o: outlook_rank_key(o, target_mode), reverse=True)
    reference = sorted((o for o in outlooks if not is_primary_origin(o.origin)), key=lambda o: outlook_rank_key(o, target_mode), reverse=True)

    stars_mode = target_mode == "stars"
    print(f"\n{'-'*78}")
    if stars_mode:
        # 2026-11-16: 星空・星座モードは銀河中心もスコアも使わない。並びは outlook_rank_key の順
        print(f"見込み一覧・主要候補(対象: {STARS_HEADING_TARGET}、星空撮影名所ベース、"
              f"{STARS_OUTLOOK_ORDER}、上位{top_n}件)")
    else:
        print(f"見込み一覧・主要候補(対象: {target.name}、星空撮影名所ベース、"
              f"月・地形・光害による決定論的スコア順、上位{top_n}件)")
    print(f"{'-'*78}")
    if primary:
        _print_outlook_items(primary, target, top_n, target_mode)
    else:
        print("\n  該当なし(主要候補=curated由来の地点で条件を満たすものがありませんでした)")

    print(f"\n{'-'*78}")
    if stars_mode:
        print(f"見込み一覧・参考候補(対象: {STARS_HEADING_TARGET}、OSM展望データ由来・星空適性は未検証、"
              f"{STARS_OUTLOOK_ORDER}、上位{top_n_reference}件)")
    else:
        print(f"見込み一覧・参考候補(対象: {target.name}、OSM展望データ由来・星空適性は未検証、上位{top_n_reference}件)")
    print(f"{'-'*78}")
    if reference:
        _print_outlook_items(reference, target, top_n_reference, target_mode)
    else:
        print("\n  該当なし")


def _print_final_items(finals: list[FinalCandidate], target, top_n: int,
                       target_mode: str = DEFAULT_TARGET_MODE) -> None:
    stars_mode = target_mode == "stars"
    for i, f in enumerate(finals[:top_n], 1):
        terrain_note = (f"地形地平線 {f.horizon_alt:.1f}°を{f.target_alt - f.horizon_alt:.1f}°上回る"
                         if f.terrain_available and f.horizon_alt is not None else NO_TERRAIN_NOTE)
        print(f"\n[{i}位]" + ("" if stars_mode else f" スコア {f.score:.1f}"))
        print(f"  日付      : {f.night_date}")
        print(f"  地点      : {f.site_name}（{f.municipality}）")
        print(f"  由来      : {ORIGIN_LABELS.get(f.origin, f.origin)}")
        if stars_mode:
            print(f"  推奨時間帯 : {f.window_start.strftime('%H:%M')} 〜 {f.window_end.strftime('%H:%M')}"
                  f"（晴れ間 {f.clear_hours:.1f}時間、月の影響小 {f.moon_free_hours:.1f}時間）")
            if f.sky_openness is not None:
                print(f"  空の開け  : {sky_openness_text(f.sky_openness)}")
        else:
            print(f"  推奨時間帯 : {f.window_start.strftime('%H:%M')} 〜 {f.window_end.strftime('%H:%M')}"
                  f"（狙い目 {f.best_time.strftime('%H:%M')} 頃、月の影響小 {f.moon_free_hours:.1f}時間）")
            print(f"  {target.name}: 方位角{f.target_az:.0f}° / 高度{f.target_alt:.1f}°({terrain_note})")
        print(f"  条件要約  : 視界遮蔽雲量 平均{f.mean_obstruction:.0f}% / 光害(相対指数) {describe_alr(f.alr, f.alr_rank_pct)}")


def print_final_report(finals: list[FinalCandidate], top_n: int = 20, top_n_reference: int = 10,
                       target_mode: str = DEFAULT_TARGET_MODE) -> None:
    target = get_target(TARGET_ID)
    primary = sorted((f for f in finals if is_primary_origin(f.origin)), key=lambda f: final_rank_key(f, target_mode), reverse=True)
    reference = sorted((f for f in finals if not is_primary_origin(f.origin)), key=lambda f: final_rank_key(f, target_mode), reverse=True)

    stars_mode = target_mode == "stars"
    print(f"\n{'='*78}")
    if stars_mode:
        # 2026-11-16: 星空・星座モードは銀河中心もスコアも使わない。並びは final_rank_key の順
        print(f"探索モード 最終候補一覧・主要候補(対象: {STARS_HEADING_TARGET}、星空撮影名所ベース、"
              f"{STARS_FINAL_ORDER}、上位{top_n}件)")
    else:
        print(f"探索モード 最終候補一覧・主要候補(対象: {target.name}、星空撮影名所ベース、スコア順、上位{top_n}件)")
    print(f"{'='*78}")
    if primary:
        _print_final_items(primary, target, top_n, target_mode)
    else:
        print("\n  該当なし(主要候補=curated由来の地点で条件を満たすものがありませんでした)")

    print(f"\n{'='*78}")
    if stars_mode:
        print(f"探索モード 最終候補一覧・参考候補(対象: {STARS_HEADING_TARGET}、OSM展望データ由来・星空適性は未検証、"
              f"{STARS_FINAL_ORDER}、上位{top_n_reference}件)")
    else:
        print(f"探索モード 最終候補一覧・参考候補(対象: {target.name}、OSM展望データ由来・星空適性は未検証、上位{top_n_reference}件)")
    print(f"{'='*78}")
    if reference:
        _print_final_items(reference, target, top_n_reference, target_mode)
    else:
        print("\n  該当なし")


def parse_args(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="探索モード(月・雲量・地形・光害で夜と地点を絞る)。"
                                             "光害は Black Marble 由来のALR(日本で未較正の相対指数)")
    ap.add_argument("--target", choices=TARGET_MODES, default=DEFAULT_TARGET_MODE,
                    help="milkyway=天の川(既定。銀河中心の高度・方角・地形を条件にする) / "
                         "stars=星空・星座(銀河中心の条件を使わず、雲・月・光害・暗い時間帯で選ぶ。天の川は対象外)")
    add_astro_grid_argument(ap)
    ap.add_argument("--json-out", default=None, metavar="ファイル",
                    help="探索結果をJSON(スキーマ hoshibiyori-explore/1、候補は全件)で書き出す。"
                         "終了コード0のときだけ書く(2のときは書かず、既存のファイルにも触れない)。通信の量は変わらない")
    ap.add_argument("--nights", default=None, type=_nights_argument, metavar="YYYY-MM-DD[,YYYY-MM-DD…]",
                    help="夜の始まりの日付。候補の上位の夜に入らなくても雲量を調べる(--json-out の requested_nights と"
                         "画面の数行。候補の一覧・順位は変わらず、通信も増えない)")
    add_estimate_argument(ap)
    return ap.parse_args(argv)


def _nights_argument(text: str) -> list[date]:
    import argparse
    from requested_nights import parse_nights
    try:
        return parse_nights(text)
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"日付は YYYY-MM-DD をカンマ区切りで指定してください({text!r}: {e})") from e


def add_estimate_argument(ap) -> None:
    """--estimate(explore と generate_report で共通)。"""
    ap.add_argument("--estimate", action="store_true",
                    help="時間の見積もりだけを出して終わる(通信しない。探索も計算もしない)")


def print_estimate(kind: str, target: str, sites: list[dict], astro_grid: str) -> int:
    """--estimate の本体。終了コード 0。"""
    import time_estimates as te
    ref_site = next(s for s in sites if s["name"] == "石廊崎")
    state = te.cache_state(sys.modules[__name__], kind, sites, ref_site, astro_cache_dir=ASTRO_CACHE_DIR)
    if astro_grid == "site":    # 従来の地点ごとの計算は保存を読まない
        state.nights_ready = 0
    for line in te.estimate_lines(kind, target, sites, state):
        print(line)
    return 0


def add_astro_grid_argument(ap) -> None:
    """--astro-grid(explore と generate_report で共通)。"""
    ap.add_argument("--astro-grid", choices=ASTRO_GRID_MODES, default=DEFAULT_ASTRO_GRID,
                    help="ecmwf=薄明・月の時刻を0.25度格子の代表点で計算し、結果を保存して使い回す(既定。地点との差は"
                         "数分程度) / site=従来どおり地点ごとに計算する(保存は読まない・書かない)")


# 天文計算の保存先(None なら astro_grid_cache.DEFAULT_CACHE_DIR。計測・テストで差し替える)
ASTRO_CACHE_DIR: Path | None = None


def astro_conditions() -> dict:
    """保存の鍵に入れる計算の条件(格子の刻み・月の判定の閾値・サンプルの間隔・天体暦・保存の形式の版)。"""
    return make_conditions(moon_phase_negligible_deg=MOON_PHASE_NEGLIGIBLE_DEG,
                           sample_interval_min=MOON_SAMPLE_INTERVAL_MIN, ephemeris=EPHEMERIS_FILE)


def make_astro_cache(mode: str, cache_dir: Path | None = None, disk_cache: bool = True) -> AstroNightCache | None:
    """`--astro-grid` の値から、天文計算の格子とキャッシュを作る。site なら None(従来の地点ごとの計算)。"""
    if mode == "site":
        return None
    if mode != "ecmwf":
        raise ValueError(f"--astro-grid の値が不正: {mode!r}")
    return AstroNightCache(dark_fn=find_astro_dark_events, moon_fn=longest_negligible_window, ref_fn=reference_night,
                           conditions=astro_conditions(),
                           cache_dir=cache_dir if cache_dir is not None else ASTRO_CACHE_DIR, disk_cache=disk_cache)


def finish_astro_cache(astro: AstroNightCache | None) -> None:
    """保存して、集計の1行を出す(site のときは何もしない)。"""
    if astro is None:
        return
    try:
        astro.flush()
    except OSError as e:
        print(f"[注意] 天文計算の結果を保存できませんでした: {e}")
    print(astro.summary_line())


def main(argv=None) -> int:
    """終了コード: 0=完了(取得失敗があれば警告を表示)、2=取得失敗が多すぎる/429。"""
    args = parse_args(argv)
    if args.estimate:
        return print_estimate("explore", args.target, load_candidate_sites(), args.astro_grid)
    t0 = time.perf_counter()
    import time_estimates
    # 2026-11-24: 始まりの予告(標準エラーへ1行。標準出力と --json-out は変わらない)
    time_estimates.print_start_notice(sys.modules[__name__], "explore", args.target, load_candidate_sites, args.astro_grid)
    cache = GridCloudCache()
    astro = make_astro_cache(args.astro_grid)
    sink: dict = {}
    try:
        code = _run(cache, args, astro, sink)
    finally:
        finish_astro_cache(astro)
        # 全体の秒数と通信以外の秒数(画面表示のみ。終了コード2の経路でも出す)
        print(timing_line(time.perf_counter() - t0, cache.summary()))
        compute_line = compute_timing_line((sink.get("result") or {}).get("compute_sec"))
        if compute_line:
            print(compute_line)
    json_out = getattr(args, "json_out", None)
    if code == 0 and json_out:
        # 2026-11-16: 終了コード0の経路だけ書く(2のときは書かず、既存のファイルにも触れない)
        path = write_explore_json(json_out, sink.get("result"), cache, args)
        print(f"探索結果の JSON を書きました: {path}")
    return code


def night_highlights(ts, eph, ref_site: dict, scan: list, now: datetime | None = None) -> dict:
    """走査した夜ごとの見どころ(sky_highlights.build の値)。暗い時間帯が無い夜は None。流星群は夜によらないので1回だけ計算して
    各夜に渡す(build に渡す showers。中身は build が自分で計算するものと同じ)。冬の天の川の帯は scanned_nights の側にあるので渡さない。"""
    import sky_highlights as sh
    now = datetime.now(JST) if now is None else now
    me = sys.modules[__name__]
    showers = sh.upcoming_showers(me, ts, eph, ref_site["lat"], ref_site["lon"], now)
    by_night = {}
    for n, _reason in scan:
        if n.dark_start is None or n.dark_end is None:
            by_night[n.night_date] = None
            continue
        by_night[n.night_date] = sh.build(me, ts, eph, ref_site["lat"], ref_site["lon"], n.night_date, n.dark_start,
                                          n.dark_end, now, sh.GUIDE_MIN_ALT_DEG, None, showers)
    return {"reference_site": ref_site, "computed_at": now, "min_alt_deg": sh.GUIDE_MIN_ALT_DEG,
            "radiant_min_alt_deg": sh.RADIANT_MIN_ALT_DEG, "max_items_per_slot": sh.MAX_ITEMS_PER_SLOT,
            "showers": showers, "by_night": by_night}


def compute_timing_line(compute_sec: dict | None) -> str | None:
    """見込みの計算(stage_outlook)と --nights の計算(requested_nights.evaluate)の秒(2026-11-27、画面表示のみ)。
    --nights を付けないときは見込みだけ。探索が途中で止まったとき(材料が無い)は None。"""
    if not compute_sec:
        return None
    parts = [f"見込みの計算 {compute_sec.get('outlook', 0.0):.1f} 秒"]
    if "requested_nights" in compute_sec:
        parts.append(f"聞かれた夜(--nights)の計算 {compute_sec['requested_nights']:.1f} 秒")
    if "highlights" in compute_sec:
        parts.append(f"見どころ(--json-out)の計算 {compute_sec['highlights']:.1f} 秒")
    return "実行時間の内訳(計算): " + " / ".join(parts)


def explore_thresholds(alr_threshold: float) -> dict:
    """JSON に入れる閾値(コードの定数から。alr_threshold は探索で使った lp_store.alr_threshold)。"""
    return {
        "cloud_obstruction_threshold_pct": CLOUD_OBSTRUCTION_THRESHOLD,
        "min_clear_window_hours": MIN_CLEAR_WINDOW_HOURS,
        "lp_alr_threshold": alr_threshold,
        "lp_index_limit": LP_INDEX_LIMIT,
        "moon_phase_negligible_deg": MOON_PHASE_NEGLIGIBLE_DEG,
        "num_nights_to_scan": NUM_NIGHTS_TO_SCAN,
        "num_candidate_nights": NUM_CANDIDATE_NIGHTS,
        "milkyway_few_results": MILKYWAY_FEW_RESULTS,
        "failed_cell_rate_abort": FAILED_CELL_RATE_ABORT,
    }


def write_explore_json(path, result: dict | None, cache, args) -> Path:
    """探索の結果(_explore の戻り値)から JSON を組み立てて書く。"""
    import explore_json as ej
    result = result or {}
    target_mode = getattr(args, "target", DEFAULT_TARGET_MODE)
    commit, dirty = ej.git_state(ROOT)
    doc = ej.build_explore_json(
        generated_at=datetime.now(JST).replace(microsecond=0),
        version=ej.plugin_version(), commit=commit, dirty=dirty,
        target=target_mode, astro_grid=getattr(args, "astro_grid", DEFAULT_ASTRO_GRID),
        thresholds=explore_thresholds(result.get("alr_threshold")),
        reference_site=result.get("reference_site"),
        nights=result.get("nights", []), msm_dates=result.get("msm_dates", []),
        scanned_nights=result.get("scanned_nights"),
        finals=result.get("finals", []), outlooks=result.get("outlooks", []),
        final_rank_key=lambda f: final_rank_key(f, target_mode),
        outlook_rank_key=lambda o: outlook_rank_key(o, target_mode),
        is_primary=is_primary_origin,
        fetch_summary=cache.summary(), fetch_failures=list(getattr(cache, "failures", [])),
        sites=result.get("sites", {}), site_index=result.get("site_index", ()),
        requested_nights=result.get("requested_nights"), winter_bands=result.get("winter_bands"),
        highlights=result.get("highlights"),
    )
    return ej.write_json_atomic(path, doc)


def _run(cache: GridCloudCache, args, astro: AstroNightCache | None = None, sink: dict | None = None) -> int:
    try:
        # 走査した全部の夜(scanned_nights)は --json-out のときだけ集める
        kwargs = {"collect_scan": bool(getattr(args, "json_out", None))}
        if kwargs["collect_scan"]:
            kwargs["collect_highlights"] = True     # 夜ごとの見どころも --json-out のときだけ(2026-11-27)
        if getattr(args, "nights", None):
            kwargs["requested_dates"] = args.nights
        result = _explore(cache, args.target, astro, **kwargs)
        if sink is not None:
            sink["result"] = result
    except OpenMeteoDailyLimitError as e:
        print(f"\n[中止] {e}")
        print("  " + cache.summary().console_line())
        return 2
    except ReferenceForecastUnavailable as e:
        print(f"\n[中止] {e}")
        print("  " + cache.summary().console_line())
        for f in cache.failures[:10]:
            print(f"  失敗セル: {f.model} lat={f.lat} lon={f.lon} 理由={f.reason}")
        return 2
    summary = cache.summary()
    print(f"予報取得の集計: {summary.console_line()}")
    if summary.status == "abort":
        print(f"[異常] 失敗セル率が閾値({FAILED_CELL_RATE_ABORT:.0%})以上です。上の結果は予報が欠けており、候補の漏れがあります。")
        for f in cache.failures[:10]:
            print(f"  失敗セル: {f.model} lat={f.lat} lon={f.lon} 理由={f.reason}")
        return 2
    if summary.status == "partial":
        print("[注意] 一部の予報が取得できていないため、候補から漏れている地点・夜がある可能性があります。")
    return 0


def _explore(cache: GridCloudCache, target_mode: str = DEFAULT_TARGET_MODE,
             astro: AstroNightCache | None = None, collect_scan: bool = False,
             requested_dates: list[date] | None = None, collect_highlights: bool = False) -> dict:
    """探索して結果を画面に出す。戻り値は --json-out 用の材料(2026-11-16。画面の出力は変えていない)。
    collect_scan が真なら、第1段階で走査した全部の夜を scanned_nights として返す(計算は増えない)。
    requested_dates(--nights)があれば、その夜を requested_nights.py で調べる(通信は増えない。候補には混ぜない)。
    collect_highlights(--json-out のとき)が真なら、走査した夜ごとの見どころ(sky_highlights)を highlights として返す。"""
    t_start = time.time()

    ts = load.timescale()
    eph_path = DATA_ROOT / "step1_astronomy" / "de421.bsp"
    eph = load(str(eph_path))

    sites = load_candidate_sites()
    primary_sites = [s for s in sites if is_primary_origin(s["origin"])]
    reference_sites = [s for s in sites if not is_primary_origin(s["origin"])]
    print(f"候補地点(stargazing_spots.json): 主要候補(星空撮影名所ベース) {len(primary_sites)}件"
          f" + 参考候補(OSM展望データ) {len(reference_sites)}件 = 計{len(sites)}件を読み込み"
          f"(うち地形地平線データあり: {sum(1 for s in sites if s['horizon_csv'])}件)\n")
    if astro is not None:
        print(astro.start_line(sites) + "\n")

    lp_store = make_lp_store()
    print(f"[光害] Black Marble由来のALR(相対指数。空の明るさの等級・ボートル値は表示しない)。仮閾値 {lp_limit_text(lp_store)}\n")

    ref_site = next(s for s in sites if s["name"] == "石廊崎")
    scan: list | None = [] if collect_scan or requested_dates else None
    nights = stage1_moon_filter(ts, eph, ref_site["lat"], ref_site["lon"], astro, scan_out=scan)

    # 冬の天の川の帯(夜ごとの値、基準地点)。候補の選び方には使わない。JSON では走査した全部の夜、画面は星空・星座モードの候補の夜
    winter_bands: dict = {}
    if collect_scan or target_mode == "stars":
        import winter_milkyway as wm
        band_nights = {n.night_date: n for n in ([n for n, _ in scan] if collect_scan else nights)}
        winter_bands = {d: wm.night_band(ts, eph, ref_site["lat"], ref_site["lon"], n.dark_start, n.dark_end)
                        for d, n in band_nights.items()}
        if target_mode == "stars":
            print("\n[冬の天の川の帯](基準地点・平らな地平線の目安。順位には使わない)")
            for n in nights:
                print(f"    {n.night_date}  {wm.band_text(n.night_date, winter_bands.get(n.night_date))}")

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
        survivors = stage2_cloud_filter(ts, eph, msm_nights, sites, cache, astro)
        finals = stage3_direction_filter(ts, eph, survivors, lp_store, target_mode)
        print_final_report(finals, target_mode=target_mode)
    else:
        finals = []
        print("\n[精密予報パート] 該当する候補夜がありません(現時点では候補日が全てMSM予報期間の外)。")
    t_stage2_end = time.time()

    # 計算の内訳(2026-11-27): 見込みの計算と --nights の計算の秒(「実行時間の内訳(計算)」の行に出すだけ)
    compute_sec: dict = {}
    t_outlook = time.perf_counter()
    if ecmwf_nights:
        outlooks = stage_outlook(ts, eph, ecmwf_nights, sites, lp_store, cache, target_mode, astro)
        compute_sec["outlook"] = time.perf_counter() - t_outlook
        print_outlook_report(outlooks, target_mode=target_mode)
    else:
        outlooks = []
        compute_sec["outlook"] = 0.0
        print("\n[見込みパート] 該当する候補夜がありません。")

    requested = None
    if requested_dates:
        import requested_nights as rn
        t_requested = time.perf_counter()
        requested = rn.evaluate(sys.modules[__name__], ts, eph, requested_dates, scan, {n.night_date for n in nights},
                                {n.night_date for n in msm_nights}, sites, ref_site, cache, lp_store, target_mode, astro)
        compute_sec["requested_nights"] = time.perf_counter() - t_requested
        for line in rn.summary_lines(requested):
            print(line)

    highlights = None
    if collect_highlights and scan is not None:
        # 夜ごとの見どころ(2026-11-27、--json-out のときだけ)。レポートの「この時期の見どころ」と同じ関数・同じ基準
        # (基準地点・高度の基準)で、走査した夜ごとに作る。探索・順位・スコアには使わない。通信しない
        t_highlights = time.perf_counter()
        highlights = night_highlights(ts, eph, ref_site, scan)
        compute_sec["highlights"] = time.perf_counter() - t_highlights

    t_end = time.time()
    if target_mode == "milkyway" and len(finals) + len(outlooks) < MILKYWAY_FEW_RESULTS:
        print("\n候補が少ない場合は `--target stars` で星空・星座向けの候補を探せます。")

    print(f"\n{'='*78}")
    print(f"実行時間: 全体 {(t_end - t_start)/60:.1f}分"
          f"(うち雲量取得 {(t_stage2_end - t_stage2_start)/60:.1f}分)")
    print(f"格子セルキャッシュ最終統計: API呼び出し{cache.call_count}回 / キャッシュヒット{cache.cache_hit_count}回")
    result = {
        "sites": {"primary": len(primary_sites), "reference": len(reference_sites), "total": len(sites),
                  "with_horizon": sum(1 for s in sites if s["horizon_csv"])},
        "reference_site": ref_site, "nights": nights, "msm_dates": [n.night_date for n in msm_nights],
        "finals": finals, "outlooks": outlooks, "alr_threshold": lp_store.alr_threshold,
        "site_index": sites, "compute_sec": compute_sec,
    }
    if requested is not None:
        result["requested_nights"] = requested
    if highlights is not None:
        result["highlights"] = highlights
    if scan is not None:
        result["scanned_nights"] = scan
        result["winter_bands"] = winter_bands
    return result


if __name__ == "__main__":
    sys.exit(main())
