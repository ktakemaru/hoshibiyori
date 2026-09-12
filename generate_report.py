"""hoshibiyori 探索モード結果のHTML Webレポート生成。

explore_hoshibiyori.pyの各ステージ関数をそのまま再利用し、印刷・共有向けの
3段構成レポート(report.html)を出力する。実行のたびに同じファイルを上書きする。

段構成:
  1段目(概況): 直近14夜の月齢タイムライン(月相アイコン+無月時間帯の長さ)と、
    期間全体の天気傾向を1〜2文で要約したヘッダー。
  2段目(直近・行動用): MSM(精密予報)圏内の候補を「気軽コース」(東京から概ね
    車で4〜5時間圏内の直線距離、離島・登山を要する地点を除く)と「硬派コース」
    (距離・アクセス方法を問わず条件だけで見たTOP10)の2本立てでスコア順に
    カード表示する。首都圏居住者が大半を占めるユーザー層にとって、佐渡・
    八丈島など好条件だが遠方の地点ばかりが上位を占めると実用性が低いという
    フィードバックを受けて2本立てにした(2026-09-06)。
    各カードに対応する番号ピンを、緯度経度を単純な線形変換で配置した
    模式図(SVG、実座標の地図ではない)上に表示する。ピンからは実際の
    Google Maps(https://www.google.com/maps?q=lat,lon)を新規タブで開ける。
  3段目(ECMWF圏内・計画用): 日付を横軸にしたカレンダー形式で、各夜の月齢・
    最有力候補地・「晴れれば◯時〜◯時にチャンス」を表示する。

地図タイル(Google Maps等)そのものはArtifact/ブラウザのCSP制約と無関係に
このファイルでも意図的に埋め込んでいない(stargazing_atlas.htmlと同じ方針)。
理由は実座標地図を描くには正確な海岸線データが必要で誤った地図を描画する
リスクがあるため、緯度経度に基づく模式図+実際のGoogle Mapsへの外部リンクと
いう構成に統一している。
"""
from __future__ import annotations

import html
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parent
for sub in ["step1_astronomy", "step2_terrain", "step3_light_pollution", "step4_moonlight", "step5_cloud_forecast"]:
    sys.path.insert(0, str(ROOT / sub))

from skyfield.api import load  # noqa: E402

from catalog import get_target  # noqa: E402
from sky_engine import altaz_at_datetime  # noqa: E402
from light_pollution import LightPollutionTileStore  # noqa: E402
from grid_cache import GridCloudCache  # noqa: E402
from elevation_cloud import get_level_cloud_forecast, hourly_sky_obstruction_and_cloud_sea  # noqa: E402

from explore_hoshibiyori import (  # noqa: E402
    JST, TARGET_ID, NUM_NIGHTS_TO_SCAN, LPI_THRESHOLD,
    NightCandidate, FinalCandidate, OutlookCandidate,
    ORIGIN_LABELS, is_primary_origin,
    load_candidate_sites, all_nights_timeline, forecast_regime_for_night,
    stage2_cloud_filter, stage3_direction_filter, stage_outlook,
    compute_site_night_window,
)
from jma_weather_map import fetch_jma_weather_map  # noqa: E402

OUTPUT_PATH = ROOT / "report.html"
TOP_N_TIER2 = 10

# --- JMA地上天気図(2段目「直近・行動用」、2026-09-06追加) ---
# 実況+24h予想+48h予想の3枚を画像として毎回取得・表示する(jma_weather_map.py参照)。
# 一方でWEATHER_MAP_COMMENTARYは「Claudeが画像を目視して書いた解説文」であり、
# generate_report.pyの実行だけでは自動更新されない。画像は毎回最新のものに
# 差し替わるため、実際の天気図とここでの文章が食い違う状態になりうる。
# そのためWEATHER_MAP_COMMENTARY_DATE(この解説文がいつの天気図をもとに書かれたか)を
# datetimeで保持し、レポート生成時刻との差がWEATHER_MAP_COMMENTARY_STALE_HOURSを
# 超えたら控えめな注記ではなく目立つ警告に切り替える(render_weather_map_section参照)。
# 天気図の内容が変わった際は、新しく取得された画像をClaudeに見せて本文を書き直し、
# WEATHER_MAP_COMMENTARY_DATEも取得時刻に更新すること。
WEATHER_MAP_COMMENTARY_DATE = datetime(2026, 9, 6, 19, 0, tzinfo=JST)
WEATHER_MAP_COMMENTARY_STALE_HOURS = 24
WEATHER_MAP_COMMENTARY = (
    "台風24号(実況時点で992hPa)が南方海上をゆっくり北上しており、日本の南岸には"
    "前線が停滞しています。48時間後には熱帯低気圧に弱まりながら本州へ近づく見込みで、"
    "日本海側には新たな低気圧が発生し前線を伴う予想です。この期間は太平洋側を中心に"
    "雲や雨の影響を受けやすく、天気の変化に注意してください。一方、北日本や日本海側は"
    "高気圧の勢力下で比較的安定した空模様が期待できます。"
)

# 模式図(SVG)の緯度経度範囲。関東甲信越・中部+伊豆諸島+佐渡が収まる固定枠
# (実行のたびにスケールが変わらないよう、対象データに合わせて可変にはしない)。
MAP_LAT_MIN, MAP_LAT_MAX = 32.9, 38.7
MAP_LON_MIN, MAP_LON_MAX = 135.5, 141.0
MAP_REF_POINTS = [
    ("東京", 35.681, 139.767),
    ("名古屋", 35.170, 136.906),
    ("新潟", 37.902, 139.023),
]

# --- この時期の見どころガイド(2026-09-06追加、1段目「概況」に表示) ---
# step1_astronomy/targets.jsonに登録済みの天体から、天の川銀河中心(探索モード本体の
# 主対象、常に表示)に加えて、星景写真の対象として人気があり肉眼でも見つけやすい
# 「季節の目印」を最大MAX_SEASONAL_TARGETS件、月に応じて自動選択する。
# 対象を増やしすぎないよう、四季を代表する大三角+定番星座に絞っている
# (北斗七星・すばるはtargets.jsonには残すが、このローテーションには含めない)。
# 特定の候補地点の地形地平線には依存せず、平坦な地平線を仮定した汎用的な目安
# (MIN_GUIDE_ALT_DEG以上で「見える」とみなす)であることに注意。
CORE_TARGET_ID = "galactic_center"
SEASONAL_TARGET_IDS = ["summer_triangle", "winter_triangle", "orion", "cassiopeia"]
MAX_SEASONAL_TARGETS = 2
MIN_GUIDE_ALT_DEG = 15.0
_GUIDE_SAMPLE_INTERVAL_MIN = 15

_SEASON_STATUS_LABEL = {
    "in_season": "見頃です",
    "coming_soon": "そろそろ見頃に入ってくる時期です",
    "leaving_soon": "そろそろ見納めの時期です",
}
_SEASON_STATUS_PRIORITY = {"in_season": 0, "coming_soon": 1, "leaving_soon": 2}

_COMPASS_16 = ["北", "北北東", "北東", "東北東", "東", "東南東", "南東", "南南東",
               "南", "南南西", "南西", "西南西", "西", "西北西", "北西", "北北西"]


def compass_direction(az_deg: float) -> str:
    idx = round(az_deg / 22.5) % 16
    return _COMPASS_16[idx]


def _season_status(best_months: list[int], month: int) -> str | None:
    """指定の月が対象の見頃期間に対してどの状態か返す(in_season/coming_soon/leaving_soon/None)。

    best_monthsは季節をまたぐ場合も暦順(例: カシオペヤ座なら[10,11,12,1])で並んでいる前提。
    """
    if month in best_months:
        return "in_season"
    prev_month = 12 if month == 1 else month - 1
    next_month = 1 if month == 12 else month + 1
    if next_month == best_months[0]:
        return "coming_soon"
    if prev_month == best_months[-1]:
        return "leaving_soon"
    return None


def select_seasonal_targets(month: int) -> list[tuple]:
    """月に応じて、常時表示の主対象+季節が近い天体を(Target, status)のペアで返す。"""
    core = get_target(CORE_TARGET_ID)
    selected = [(core, _season_status(core.best_months, month))]

    candidates = []
    for target_id in SEASONAL_TARGET_IDS:
        target = get_target(target_id)
        status = _season_status(target.best_months, month)
        if status is not None:
            candidates.append((target, status))
    candidates.sort(key=lambda c: _SEASON_STATUS_PRIORITY[c[1]])
    selected.extend(candidates[:MAX_SEASONAL_TARGETS])
    return selected

# --- 「気軽コース」判定(2026-09-06追加) ---
# ユーザーの大半が首都圏在住であるという想定に基づく、近場優先の簡易フィルタ。
# 道路距離・実際の所要時間はルート探索APIを使わないと分からないため、
# 東京駅からの直線距離で近似する(日本の道路は山がち・海岸沿いで迂回が多く、
# 実際の道路距離は直線距離の1.3〜1.5倍程度になることが多い。250kmという
# 設定値は「車で片道4〜5時間」の大まかな目安であり、正確な走行時間の
# 保証ではない。実際に近すぎる/遠すぎると感じた場合はCASUAL_RADIUS_KMを
# 調整すること)。
TOKYO_LAT, TOKYO_LON = 35.681, 139.767
CASUAL_RADIUS_KM = 250.0

# フェリー・飛行機でしか行けない離島は、直線距離が近くても「気軽」から除外する。
CASUAL_EXCLUDED_MUNICIPALITIES = ["神津島村", "三宅村", "八丈町", "佐渡市"]

# 車を停めてから徒歩30分を超えるような本格的な登山・縦走を要する地点。
# 現時点ではcurated由来84件のうち判明している分のみ手動で列挙している網羅版
# ではないリスト。該当地点に気づいたら追加すること。
CASUAL_EXCLUDED_HIKE_NAMES = ["甘利山", "剱沢キャンプ場"]


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    import math
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def distance_from_tokyo_km(lat: float, lon: float) -> float:
    return haversine_km(TOKYO_LAT, TOKYO_LON, lat, lon)


def is_casual_site(name: str, municipality: str, lat: float, lon: float, requires_lift_access: bool = False) -> bool:
    if distance_from_tokyo_km(lat, lon) > CASUAL_RADIUS_KM:
        return False
    if any(m in municipality for m in CASUAL_EXCLUDED_MUNICIPALITIES):
        return False
    if name in CASUAL_EXCLUDED_HIKE_NAMES:
        return False
    if requires_lift_access:
        # ロープウェイ・ゴンドラ・ケーブルカー・リフト・アルペンルート等、営業時間が
        # 定まった交通機関を使わないと到達できない地点(夜間は運行なしのため気軽コースに
        # 不適)。判定根拠はstargazing_spots.jsonのrequires_lift_access_noteを参照。
        return False
    return True

_MOON_ICONS = [
    (22.5, "🌑"), (67.5, "🌒"), (112.5, "🌓"), (157.5, "🌔"),
    (202.5, "🌕"), (247.5, "🌖"), (292.5, "🌗"), (337.5, "🌘"), (360.1, "🌑"),
]


def moon_phase_deg(ts, eph, dt_local: datetime) -> float:
    """月の位相を0(新月)〜360度(次の新月直前)の符号付きで返す(黄経差ベース)。

    moon_position.compute_moon_position()のphase_angle_deg(0=満月,180=新月、
    符号なし)は満ち欠けの方向(満ちていく/欠けていく)を区別できないため、
    アイコン選択にはここで黄経の差を使う。
    """
    t = ts.from_datetime(dt_local.astimezone(timezone.utc))
    earth = eph["earth"]
    moon_lon = earth.at(t).observe(eph["moon"]).apparent().ecliptic_latlon()[1].degrees
    sun_lon = earth.at(t).observe(eph["sun"]).apparent().ecliptic_latlon()[1].degrees
    return (moon_lon - sun_lon) % 360.0


def moon_icon_for(phase_deg: float) -> str:
    for threshold, icon in _MOON_ICONS:
        if phase_deg < threshold:
            return icon
    return "🌑"


def fmt_hm(dt: datetime) -> str:
    return dt.strftime("%H:%M")


def fmt_hm_rounded(dt: datetime, round_min: int = 30) -> str:
    """概況目安として、指定した分単位(既定30分)に四捨五入した時刻を返す。"""
    total_min = dt.hour * 60 + dt.minute
    rounded_total = round(total_min / round_min) * round_min
    rounded = dt.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(minutes=rounded_total)
    return rounded.strftime("%H:%M")


def fmt_range(start: datetime, end: datetime) -> str:
    same_day = start.date() == end.date()
    return f"{fmt_hm(start)}〜{fmt_hm(end)}" + ("" if same_day else "(翌)")


def maps_url(lat: float, lon: float) -> str:
    return f"https://www.google.com/maps?q={lat},{lon}"


def project(lat: float, lon: float, width: float, height: float) -> tuple[float, float]:
    x = (lon - MAP_LON_MIN) / (MAP_LON_MAX - MAP_LON_MIN) * width
    y = (MAP_LAT_MAX - lat) / (MAP_LAT_MAX - MAP_LAT_MIN) * height
    return x, y


def build_casual_weather_note(ts, eph, casual_eligible_sites: list[dict], msm_nights: list[NightCandidate],
                               cache: GridCloudCache) -> str:
    """気軽コース圏内(距離・離島・登山・リフト等を除いた候補地)の、MSM圏内の夜における
    視界遮蔽雲量の地域傾向を1〜2文で要約する。

    stage2_cloud_filter()は「条件を満たした組み合わせ」しか返さないため、条件を
    満たさなかった大多数の地点の雲量は分からない(=なぜ気軽コースの候補が少ないのか
    説明できない)。ここでは気軽コース圏内の全地点について雲量を再計算し、
    地域全体の傾向(平均視界遮蔽雲量・通過率)を示す。同じ格子セル・同じ夜であれば
    stage2_cloud_filter()実行時に既にキャッシュ済みのため、追加のAPI呼び出しは
    ほぼ発生しない。
    """
    if not msm_nights or not casual_eligible_sites:
        return ""

    CLOUD_OBSTRUCTION_THRESHOLD = 30.0
    obstructions = []
    pass_count = 0
    total_count = 0
    for night in msm_nights:
        for site in casual_eligible_sites:
            w_start, w_end, _ = compute_site_night_window(ts, eph, site, night.night_date)
            if w_start is None:
                continue
            levels = get_level_cloud_forecast(site["lat"], site["lon"], w_start, w_end, cache=cache)
            rows = hourly_sky_obstruction_and_cloud_sea(levels, site["elevation_m"])
            valid = [r["sky_obstruction"] for r in rows if r["sky_obstruction"] is not None]
            if not valid:
                continue
            avg = sum(valid) / len(valid)
            obstructions.append(avg)
            total_count += 1
            if avg <= CLOUD_OBSTRUCTION_THRESHOLD:
                pass_count += 1

    if not obstructions:
        return "気軽コース圏内の雲量データが取得できませんでした。"

    avg_all = sum(obstructions) / len(obstructions)
    if avg_all < 30:
        tone = "全体的に晴れ間が期待できる見込みです。"
    elif avg_all < 60:
        tone = "地域差が大きく、場所によって明暗が分かれる見込みです。"
    else:
        tone = "厚い雲に覆われる時間が長く、星空はあまり期待できない見込みです。"

    return (f"気軽コース圏内(東京から{CASUAL_RADIUS_KM:.0f}km圏内)の平均視界遮蔽雲量は"
            f"{avg_all:.0f}%、条件(30%以下)を満たす組み合わせは{pass_count}/{total_count}件でした。{tone}"
            "首都圏近郊は総じて候補が絞られやすいので、晴れる方角が偏っている夜は"
            "この期間だけ「硬派コース」側の遠方候補もあわせてご検討ください。")


def _find_visible_windows(ts, eph, lat: float, lon: float, target,
                           window_start: datetime, window_end: datetime) -> list[dict]:
    """window_start〜window_end内で、対象の高度がMIN_GUIDE_ALT_DEGを上回る連続区間をすべて返す。

    候補地点固有の地形地平線は考慮しない汎用ガイドのため、平坦な地平線+仰角閾値のみで判定する。
    各区間について、開始・終了・南中(最高高度)時刻とその方位角/高度をまとめる。
    """
    samples = []
    t = window_start
    while t <= window_end:
        az, alt = altaz_at_datetime(ts, eph, lat, lon, 0.0, target, t)
        samples.append((t, az, alt))
        t += timedelta(minutes=_GUIDE_SAMPLE_INTERVAL_MIN)

    windows = []
    cur = []
    for s in samples:
        if s[2] > MIN_GUIDE_ALT_DEG:
            cur.append(s)
        elif cur:
            windows.append(cur)
            cur = []
    if cur:
        windows.append(cur)

    results = []
    for w in windows:
        peak = max(w, key=lambda s: s[2])
        results.append({
            "start": w[0][0], "end": w[-1][0],
            "peak_time": peak[0], "peak_az": peak[1], "peak_alt": peak[2],
        })
    return results


def build_sky_guide(ts, eph, ref_lat: float, ref_lon: float, night: NightCandidate, month: int) -> dict:
    """代表夜(通常は直近14夜のうち今夜)について、月に応じて選んだ天体の見える時間帯と方角をまとめる。

    月の有無(無月時間帯)には左右されない一般的な「見どころ」ガイドなので、
    夜全体(天文薄明終了〜天文薄明開始)を対象にする(night.window_start/endという
    無月区間には限定しないが、空が完全に暗くなる時間帯には限定する)。
    """
    selected = select_seasonal_targets(month)
    targets_out = []
    for target, status in selected:
        if night.dark_start is None or night.dark_end is None:
            targets_out.append({"target": target, "status": status, "windows": []})
            continue
        windows = _find_visible_windows(ts, eph, ref_lat, ref_lon, target, night.dark_start, night.dark_end)
        targets_out.append({"target": target, "status": status, "windows": windows})
    return {"night_date": night.night_date, "targets": targets_out}


def build_period_summary(finals: list[FinalCandidate], outlooks: list[OutlookCandidate]) -> str:
    parts = []
    if finals:
        avg_obstruction = sum(f.mean_obstruction for f in finals) / len(finals)
        best = max(finals, key=lambda f: f.score)
        parts.append(
            f"直近の精密予報期間は平均視界遮蔽雲量{avg_obstruction:.0f}%で、"
            f"最有力は{best.night_date}の{best.site_name}(スコア{best.score:.0f})です。"
        )
    else:
        parts.append("直近の精密予報(MSM)圏内にはまだ候補夜がありません。")

    clear_vals = [o.clear_sky_pct for o in outlooks if o.clear_sky_pct is not None]
    if clear_vals:
        avg_clear = sum(clear_vals) / len(clear_vals)
        parts.append(f"中期(見込み)期間は参考晴天率が平均{avg_clear:.0f}%程度の夜が点在しています。")
    elif outlooks:
        parts.append("中期(見込み)期間は雲量の参考値が取得できていない夜が中心です。")

    return " ".join(parts)


def main() -> None:
    t_start = datetime.now(JST)
    ts = load.timescale()
    eph = load(str(ROOT / "step1_astronomy" / "de421.bsp"))
    target = get_target(TARGET_ID)

    # レポートは星空撮影名所として調査済みのcurated由来地点のみを対象とする
    # (OSM viewpoint由来の751件は星空適性が未検証の参考データのため、
    # 実行時間短縮とレポートの実用性向上を兼ねて2026-09-06に対象から外した)。
    all_sites = load_candidate_sites()
    sites = [s for s in all_sites if is_primary_origin(s["origin"])]
    ref_site = next(s for s in sites if s["name"] == "石廊崎")

    cache = GridCloudCache()
    lp_store = LightPollutionTileStore(cache_dir=str(ROOT / "step3_light_pollution" / "tile_cache"), year=2025)

    print(f"候補地点: {len(sites)}件を読み込み(curated由来のみ、viewpoint参考データ{len(all_sites)-len(sites)}件は対象外)")

    all_nights = all_nights_timeline(ts, eph, ref_site["lat"], ref_site["lon"], NUM_NIGHTS_TO_SCAN)
    print(f"[概況] 直近{len(all_nights)}夜を評価")

    # 各夜の月相アイコン(概況・カレンダー共通)
    night_icons: dict = {}
    for n in all_nights:
        mid = n.sunset + (n.sunrise - n.sunset) / 2
        night_icons[n.night_date] = moon_icon_for(moon_phase_deg(ts, eph, mid))

    nights_with_window = [n for n in all_nights if n.window_start is not None]
    regimes: dict = {}
    for n in nights_with_window:
        regimes[n.night_date] = forecast_regime_for_night(cache, ref_site, n)

    msm_nights = [n for n in nights_with_window if regimes[n.night_date] == "MSM"]
    ecmwf_nights = [n for n in nights_with_window if regimes[n.night_date] == "ECMWF"]
    print(f"[レジーム判定] MSM圏内{len(msm_nights)}夜 / ECMWF圏内{len(ecmwf_nights)}夜"
          f"(無月時間帯なし{len(all_nights) - len(nights_with_window)}夜)")

    finals: list[FinalCandidate] = []
    night_view_items: list[dict] = []
    if msm_nights:
        survivors = stage2_cloud_filter(ts, eph, msm_nights, sites, cache)
        finals = stage3_direction_filter(ts, eph, survivors, lp_store)
        # 「星空観賞向き」枠(2026-09-07追加): stage3のLPI足切りで気軽/硬派コースから
        # 除外される夜景系地点(site_type=="night_view")も、天気(晴れ間)条件さえ満たせば
        # 観賞向きスポットとして別枠で残す。地点ごとに最も晴れる(視界遮蔽雲量が低い)夜を1件だけ選ぶ。
        night_view_by_site: dict[str, dict] = {}
        for s in survivors:
            if s["site"].get("site_type") != "night_view":
                continue
            name = s["site"]["name"]
            if name not in night_view_by_site or s["mean_obstruction"] < night_view_by_site[name]["mean_obstruction"]:
                night_view_by_site[name] = {
                    "site_name": name, "municipality": s["site"]["municipality"],
                    "lat": s["site"]["lat"], "lon": s["site"]["lon"],
                    "night_date": s["night"].night_date,
                    "window_start": s["window_start"], "window_end": s["window_end"],
                    "mean_obstruction": s["mean_obstruction"],
                    "lpi": s["site"].get("lpi_precomputed") or 0.0,
                }
        night_view_items = sorted(night_view_by_site.values(), key=lambda c: c["mean_obstruction"])

    outlooks: list[OutlookCandidate] = []
    if ecmwf_nights:
        outlooks = stage_outlook(ts, eph, ecmwf_nights, sites, lp_store, cache)

    # MSM圏内に入るまでの残り日数
    msm_index = next((i for i, n in enumerate(all_nights) if regimes.get(n.night_date) == "MSM"), None)

    finals_casual = [f for f in finals
                     if is_casual_site(f.site_name, f.municipality, f.site_lat, f.site_lon, f.requires_lift_access)]
    tier2_casual = sorted(finals_casual, key=lambda f: f.score, reverse=True)[:TOP_N_TIER2]

    casual_eligible_sites = [s for s in sites
                              if is_casual_site(s["name"], s["municipality"], s["lat"], s["lon"], s["requires_lift_access"])]
    casual_weather_note = build_casual_weather_note(ts, eph, casual_eligible_sites, msm_nights, cache)

    sky_guide = build_sky_guide(ts, eph, ref_site["lat"], ref_site["lon"], all_nights[0], t_start.month)
    tier2_hardcore = sorted(finals, key=lambda f: f.score, reverse=True)[:TOP_N_TIER2]

    outlooks_by_date: dict = {}
    for o in outlooks:
        outlooks_by_date.setdefault(o.night_date, []).append(o)
    for lst in outlooks_by_date.values():
        lst.sort(key=lambda o: o.score, reverse=True)

    # 3段目の対象夜: MSM圏外(ECMWF、または無月時間帯なし)の夜すべて、日付順
    tier3_nights = [n for n in all_nights if regimes.get(n.night_date) != "MSM"]

    summary_text = build_period_summary(finals, outlooks)

    try:
        weather_map_paths = fetch_jma_weather_map()
        weather_map_html = render_weather_map_section(weather_map_paths, t_start)
    except Exception as e:
        print(f"[天気図] 取得に失敗したためスキップします: {e}")
        weather_map_html = ""

    html_out = render_html(
        target=target, generated_at=t_start, all_nights=all_nights, night_icons=night_icons,
        regimes=regimes, msm_index=msm_index, msm_nights_count=len(msm_nights),
        tier2_casual=tier2_casual, tier2_hardcore=tier2_hardcore, casual_weather_note=casual_weather_note,
        sky_guide=sky_guide,
        tier3_nights=tier3_nights, outlooks_by_date=outlooks_by_date, summary_text=summary_text,
        weather_map_html=weather_map_html, night_view_items=night_view_items,
    )
    OUTPUT_PATH.write_text(html_out, encoding="utf-8")

    t_end = datetime.now(JST)
    print(f"\n完了。{OUTPUT_PATH} に出力しました(所要時間 {(t_end - t_start).total_seconds()/60:.1f}分)。")
    print(f"格子セルキャッシュ: API呼び出し(実際にOpen-Meteoへ通信){cache.call_count}回 / "
          f"キャッシュヒット{cache.cache_hit_count}回(うちディスクキャッシュ{cache.disk_hit_count}回)")


def render_tier1(all_nights, night_icons, summary_text, sky_guide: dict | None = None) -> str:
    rows = []
    for n in all_nights:
        icon = night_icons[n.night_date]
        if n.window_start is not None:
            bar_pct = min(100, n.moon_free_hours / 12.0 * 100)
            detail = f"{n.moon_free_hours:.1f}時間"
        else:
            bar_pct = 0
            detail = "無月時間帯なし"
        rows.append(f"""
          <div class="moon-tick">
            <div class="moon-date">{n.night_date.strftime('%m/%d')}</div>
            <div class="moon-icon">{icon}</div>
            <div class="moon-bar-track"><div class="moon-bar-fill" style="width:{bar_pct:.0f}%"></div></div>
            <div class="moon-detail">{html.escape(detail)}</div>
          </div>""")
    sky_guide_html = render_sky_guide(sky_guide or {})

    return f"""
    <section class="tier tier1">
      <div class="tier-label">1</div>
      <h2>概況 &mdash; 直近{len(all_nights)}夜の月齢タイムライン</h2>
      <p class="summary-text">{html.escape(summary_text)}</p>
      <div class="moon-timeline">{"".join(rows)}</div>
      {sky_guide_html}
    </section>"""


def render_map_svg(cards) -> str:
    width, height = 320, 380
    ref_dots = []
    for label, lat, lon in MAP_REF_POINTS:
        x, y = project(lat, lon, width, height)
        ref_dots.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.5" class="ref-dot"/>'
                         f'<text x="{x+5:.1f}" y="{y+3:.1f}" class="ref-label">{html.escape(label)}</text>')

    pins = []
    for i, c in enumerate(cards, 1):
        x, y = project(c.site_lat, c.site_lon, width, height)
        pins.append(f"""
          <a href="{maps_url(c.site_lat, c.site_lon)}" target="_blank" rel="noopener" class="pin-link">
            <circle cx="{x:.1f}" cy="{y:.1f}" r="10" class="pin"/>
            <text x="{x:.1f}" y="{y:.1f}" class="pin-num" dy=".33em">{i}</text>
          </a>""")

    return f"""
    <svg viewBox="0 0 {width} {height}" class="schema-map" role="img" aria-label="候補地点の模式図(実座標の地図ではありません)">
      <rect x="0" y="0" width="{width}" height="{height}" class="map-bg"/>
      {"".join(f'<line x1="0" y1="{height*i/4:.0f}" x2="{width}" y2="{height*i/4:.0f}" class="grid-line"/>' for i in range(1,4))}
      {"".join(f'<line x1="{width*i/4:.0f}" y1="0" x2="{width*i/4:.0f}" y2="{height}" class="grid-line"/>' for i in range(1,4))}
      {"".join(ref_dots)}
      {"".join(pins)}
    </svg>"""


def render_candidate_group(cards, group_title: str, group_note: str, empty_note: str, weather_note: str = "") -> str:
    weather_html = f'<p class="weather-note">🌤 {html.escape(weather_note)}</p>' if weather_note else ""

    if not cards:
        return f"""
        <div class="cand-group">
          <h3 class="group-title">{html.escape(group_title)}</h3>
          <p class="group-note">{html.escape(group_note)}</p>
          {weather_html}
          <p class="empty-note">{html.escape(empty_note)}</p>
        </div>"""

    cards_html = []
    for i, c in enumerate(cards, 1):
        origin_label = ORIGIN_LABELS.get(c.origin, c.origin)
        dist_km = distance_from_tokyo_km(c.site_lat, c.site_lon)
        cards_html.append(f"""
          <div class="cand-card">
            <div class="cand-rank">{i}</div>
            <div class="cand-body">
              <h3>{html.escape(c.site_name)}<span class="cand-muni">（{html.escape(c.municipality)}）</span></h3>
              <div class="cand-badges">
                <span class="badge score">スコア {c.score:.0f}</span>
                <span class="badge origin">{html.escape(origin_label)}</span>
                <span class="badge dist">東京から直線{dist_km:.0f}km</span>
              </div>
              <dl class="cand-stats">
                <div><dt>見頃</dt><dd>{fmt_range(c.window_start, c.window_end)}(狙い目 {fmt_hm(c.best_time)})</dd></div>
                <div><dt>日付</dt><dd>{c.night_date}</dd></div>
                <div><dt>視界遮蔽雲量</dt><dd>平均{c.mean_obstruction:.0f}%</dd></div>
                <div><dt>実効的な空の明るさ</dt><dd>{c.effective_mpsas:.2f} mag/arcsec&sup2;</dd></div>
              </dl>
              <a class="btn-maps" href="{maps_url(c.site_lat, c.site_lon)}" target="_blank" rel="noopener">📍 Googleマップで開く</a>
            </div>
          </div>""")

    return f"""
        <div class="cand-group">
          <h3 class="group-title">{html.escape(group_title)}</h3>
          <p class="group-note">{html.escape(group_note)}</p>
          {weather_html}
          <div class="tier2-layout">
            <div class="cand-grid">{"".join(cards_html)}</div>
            <div class="map-panel">
              {render_map_svg(cards)}
              <p class="map-caption">緯度経度に基づく模式図(実座標の地図ではありません)。番号ピンをクリックすると実際のGoogleマップが新しいタブで開きます。</p>
            </div>
          </div>
        </div>"""


def render_night_view_group(items: list[dict]) -> str:
    """光害が強く天の川撮影の基準(LPI<=LPI_THRESHOLD)を満たさない「夜景系」地点向けの、
    「星空撮影に適する」ではなく「星空観賞が期待できる」ことだけを示す別枠セクション。

    2026-09-07追加。夜景で有名な高台(菜の花台・高尾山等)は、天の川銀河中心のような
    淡い対象の撮影には向かないため気軽/硬派コースの候補からは除外されるが、晴れていれば
    肉眼で星や明るい天体を楽しむことは十分できる。「撮影に適する」と「観賞が期待できる」を
    別バッジ(別セクション)として区別することで、除外理由を明示しつつ観賞用途の情報は残す。
    """
    if not items:
        return ""

    cards_html = []
    for c in items:
        cards_html.append(f"""
          <div class="cand-card nv-card">
            <div class="cand-rank">🌃</div>
            <div class="cand-body">
              <h3>{html.escape(c['site_name'])}<span class="cand-muni">（{html.escape(c['municipality'])}）</span></h3>
              <div class="cand-badges">
                <span class="badge nv">星空観賞向き(撮影には不向き)</span>
              </div>
              <dl class="cand-stats">
                <div><dt>晴れ間</dt><dd>{fmt_range(c['window_start'], c['window_end'])}</dd></div>
                <div><dt>日付</dt><dd>{c['night_date']}</dd></div>
                <div><dt>視界遮蔽雲量</dt><dd>平均{c['mean_obstruction']:.0f}%</dd></div>
                <div><dt>光害LPI</dt><dd>{c['lpi']:.2f}(天の川撮影の目安は{LPI_THRESHOLD:.1f}以下)</dd></div>
              </dl>
              <a class="btn-maps" href="{maps_url(c['lat'], c['lon'])}" target="_blank" rel="noopener">📍 Googleマップで開く</a>
            </div>
          </div>""")

    return f"""
        <div class="cand-group nv-group">
          <h3 class="group-title">🌃 星空観賞向きスポット(天の川撮影には不向き)</h3>
          <p class="group-note">夜景で有名な高台など、光害が強く天の川の淡い構造は写りにくい(光害LPIが
          撮影向きの基準を超える)ため気軽/硬派コースの候補からは除外した地点です。ただし晴れていれば
          肉眼で星や明るい天体・夜景と星空を組み合わせた撮影を楽しむには十分な条件です。</p>
          <div class="cand-grid">{"".join(cards_html)}</div>
        </div>"""


def render_sky_guide(sky_guide: dict) -> str:
    if not sky_guide or not sky_guide.get("targets"):
        return ""
    lines = []
    for t in sky_guide["targets"]:
        target = t["target"]
        status = t["status"]
        windows = t["windows"]
        status_phrase = _SEASON_STATUS_LABEL.get(status)
        prefix = f"{status_phrase}。" if status_phrase else ""

        if not windows:
            lines.append(f"<li><b>{html.escape(target.name)}</b>: {prefix}この時期は高度{MIN_GUIDE_ALT_DEG:.0f}&deg;以上には昇りません</li>")
            continue
        parts = []
        for w in windows:
            # 高度80°超(天頂付近)は方位角の変化が急峻で特定の方角として示す意味が薄いため、
            # 「ほぼ天頂」と表現する(南中高度が観測地の緯度と対象の赤緯の差で決まるため、
            # 夏の大三角のように緯度に近い赤緯を持つ対象では日本付近でしばしば天頂近くを通る)。
            direction = "ほぼ天頂" if w["peak_alt"] >= 80 else f"{compass_direction(w['peak_az'])}の空"
            parts.append(
                f"{fmt_hm_rounded(w['start'])}〜{fmt_hm_rounded(w['end'])}頃({direction}、"
                f"最高高度は{fmt_hm_rounded(w['peak_time'])}頃に約{w['peak_alt']:.0f}&deg;)"
            )
        lines.append(f"<li><b>{html.escape(target.name)}</b>: {prefix}{'、'.join(parts)}</li>")

    return f"""
        <div class="sky-guide">
          <h3 class="group-title">🌌 この時期の見どころ</h3>
          <p class="group-note">対象地点固有の地形は考慮しない一般的な目安です(地平線から{MIN_GUIDE_ALT_DEG:.0f}&deg;以上を「見える」の基準、
          時刻は30分単位に丸めています)。直近数日はほぼ同じ見え方のため今夜の分を代表として表示しています。
          実際に見えるかどうかは地形・雲量に左右されます。</p>
          <ul class="guide-list">{"".join(lines)}</ul>
        </div>"""


_WEATHER_MAP_STEP_LABELS = {"now": "実況", "plus24h": "24時間後の予想", "plus48h": "48時間後の予想"}


def render_weather_map_section(image_paths: list, now: datetime) -> str:
    if not image_paths:
        return ""

    cards = []
    for p in image_paths:
        step = p.stem.rsplit("_", 1)[-1]
        label = _WEATHER_MAP_STEP_LABELS.get(step, step)
        rel_src = p.relative_to(ROOT).as_posix()
        cards.append(f"""
          <figure class="wmap-card">
            <img src="{html.escape(rel_src)}" alt="JMA地上天気図({html.escape(label)})" loading="lazy">
            <figcaption>{html.escape(label)}</figcaption>
          </figure>""")

    commentary_date_label = WEATHER_MAP_COMMENTARY_DATE.strftime("%Y-%m-%d %H時取得分")
    age_hours = (now - WEATHER_MAP_COMMENTARY_DATE).total_seconds() / 3600

    if age_hours > WEATHER_MAP_COMMENTARY_STALE_HOURS:
        freshness_html = (
            f'<p class="wmap-stale-warning">⚠️ この解説文は約{age_hours:.0f}時間前'
            f'({html.escape(commentary_date_label)})の天気図をもとにしたものです。'
            "最新の図と食い違っている可能性があります。</p>"
        )
    else:
        freshness_html = (
            f'<p class="wmap-caveat">解説文は{html.escape(commentary_date_label)}の天気図をもとに手動で記述したものです。'
            "天気図画像はレポート生成のたびに気象庁から最新のものを取得しますが、解説文は自動更新されません。"
            "出典: 気象庁ホームページ(https://www.jma.go.jp/bosai/weather_map/)。</p>"
        )

    return f"""
      <div class="wmap-block">
        <h3>地上天気図(気象庁)</h3>
        <div class="wmap-row">{"".join(cards)}</div>
        <p class="wmap-commentary">{html.escape(WEATHER_MAP_COMMENTARY)}</p>
        {freshness_html}
      </div>"""


def render_tier2(tier2_casual, tier2_hardcore, msm_index, msm_nights_count: int, casual_weather_note: str = "",
                  weather_map_html: str = "", night_view_items: list[dict] | None = None) -> str:
    if msm_nights_count == 0:
        if msm_index is None:
            empty_note = "現在、直近の精密予報(MSM)圏内に候補夜がありません。JMA MSMは起点から約78時間程度をカバーするため、日を改めて実行すると近い夜から精密予報に切り替わる見込みです。"
        else:
            empty_note = f"精密予報(MSM)圏内の候補夜まであと約{msm_index}日です。"
    else:
        empty_note = (f"精密予報(MSM)圏内に{msm_nights_count}夜ありますが、条件(視界遮蔽雲量など)を満たす"
                       "候補地点が見つかりませんでした。3段目(計画用)の見込み情報もあわせてご確認ください。")

    casual_html = render_candidate_group(
        tier2_casual, f"気軽コース TOP{len(tier2_casual) or TOP_N_TIER2}",
        f"東京から直線距離{CASUAL_RADIUS_KM:.0f}km圏内(車で概ね4〜5時間の目安)・離島や本格的な登山・"
        "リフト等の交通機関を要する地点は除く。",
        empty_note, weather_note=casual_weather_note,
    )
    hardcore_html = render_candidate_group(
        tier2_hardcore, f"硬派コース TOP{len(tier2_hardcore) or TOP_N_TIER2}",
        "距離・アクセス方法を問わず、条件(月・地形・光害)だけで見た全国TOP。遠征・登山・離島渡航が前提の地点も含む。",
        empty_note,
    )
    night_view_html = render_night_view_group(night_view_items or [])

    return f"""
    <section class="tier tier2">
      <div class="tier-label">2</div>
      <h2>直近・行動用 &mdash; 精密予報(MSM)圏内</h2>
      {weather_map_html}
      {casual_html}
      {hardcore_html}
      {night_view_html}
    </section>"""


def render_tier3(tier3_nights, outlooks_by_date, night_icons, msm_index) -> str:
    if msm_index is None:
        msm_note = "現在の精密予報(MSM)圏内: 該当なし(直近14夜すべて対象)"
    elif msm_index == 0:
        msm_note = "精密予報(MSM)圏内: 今夜から"
    else:
        msm_note = f"精密予報(MSM)圏内まで: あと約{msm_index}日"

    cols = []
    for n in tier3_nights:
        icon = night_icons[n.night_date]
        day_outlooks = outlooks_by_date.get(n.night_date, [])[:2]
        if n.window_start is None:
            body = '<p class="cal-empty">この夜は無月時間帯が確保できず、候補地点の評価を省略しています。</p>'
        elif not day_outlooks:
            body = '<p class="cal-empty">条件(光害・地形)を満たす候補地点が見つかりませんでした。</p>'
        else:
            items = []
            for o in day_outlooks:
                origin_label = ORIGIN_LABELS.get(o.origin, o.origin)
                clear_note = f"参考晴天率 約{o.clear_sky_pct:.0f}%" if o.clear_sky_pct is not None else "晴天率データなし"
                items.append(f"""
                  <li>
                    <div class="cal-site-name">{html.escape(o.site_name)}<span class="cal-site-muni">（{html.escape(o.municipality)}）</span></div>
                    <div class="cal-site-badge">{html.escape(origin_label)} ・ スコア{o.score:.0f}</div>
                    <div class="cal-chance">→ 晴れれば {fmt_range(o.visible_start, o.visible_end)} にチャンス（{clear_note}）</div>
                  </li>""")
            body = f'<ul class="cal-list">{"".join(items)}</ul>'

        cols.append(f"""
          <div class="cal-col">
            <div class="cal-date">{n.night_date.strftime('%m/%d')}<span class="cal-weekday">({['月','火','水','木','金','土','日'][n.night_date.weekday()]})</span></div>
            <div class="cal-icon">{icon}</div>
            <div class="cal-moonfree">{f'無月{n.moon_free_hours:.1f}h' if n.window_start else '&mdash;'}</div>
            {body}
          </div>""")

    return f"""
    <section class="tier tier3">
      <div class="tier-label">3</div>
      <h2>計画用 &mdash; 見込み(ECMWF圏内)カレンダー</h2>
      <p class="msm-note">{html.escape(msm_note)}</p>
      <div class="calendar-scroll"><div class="calendar-row">{"".join(cols)}</div></div>
    </section>"""


def render_html(target, generated_at, all_nights, night_icons, regimes, msm_index, msm_nights_count,
                 tier2_casual, tier2_hardcore, casual_weather_note, sky_guide,
                 tier3_nights, outlooks_by_date, summary_text, weather_map_html: str = "",
                 night_view_items: list[dict] | None = None) -> str:
    tier1 = render_tier1(all_nights, night_icons, summary_text, sky_guide)
    tier2 = render_tier2(tier2_casual, tier2_hardcore, msm_index, msm_nights_count, casual_weather_note,
                          weather_map_html, night_view_items)
    tier3 = render_tier3(tier3_nights, outlooks_by_date, night_icons, msm_index)

    return f"""<!doctype html>
<html lang="ja" data-theme="light">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>星の日和 探索レポート</title>
<style>
{CSS}
</style>
</head>
<body>
<div class="wrap">
  <header class="page-header">
    <div class="eyebrow">hoshibiyori 探索モード</div>
    <h1>星の日和 探索レポート</h1>
    <p class="target-line">対象天体: {html.escape(target.name)} ・ 生成日時: {generated_at.strftime('%Y-%m-%d %H:%M')} JST</p>
  </header>
  {tier1}
  {tier2}
  {tier3}
  <footer class="page-footer">
    <p class="attribution">出典・データ提供:
    気象予報 <a href="https://open-meteo.com/">Open-Meteo.com</a>(CC BY 4.0、気象庁MSM・ECMWF IFSの数値予報を配信) ・
    地形 <a href="https://maps.gsi.go.jp/development/ichiran.html">国土地理院 地理院タイル(標高タイル)</a>を加工して作成 ・
    光害 David Lorenz, <a href="https://djlorenz.github.io/astronomy/lp/">Light Pollution Atlas</a>
    (ボートルスケール値は非公式の簡易近似) ・
    天気図 <a href="https://www.jma.go.jp/">気象庁ホームページ</a> ・
    候補地点・地名 © <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>(ODbL) ・
    天体位置 JPL DE421 暦(Skyfield経由)。</p>
    <p class="attribution">本レポートは数値予報データを個人の星景撮影計画のために整理・表示したものであり、
    気象庁その他の機関による予報・警報ではありません。気圧面別の雲量は相対湿度からの近似値です。</p>
  </footer>
</div>
</body>
</html>
"""


CSS = """
:root {
  --bg: #f5f2ea; --surface: #ffffff; --surface-alt: #ebe6d8;
  --text: #1c1e2e; --text-muted: #666a80; --border: #ddd6c4;
  --accent: #3d3178; --accent-soft: #ece8f9; --gold: #a8752e;
  --shadow: 0 1px 2px rgba(28,30,46,.06), 0 4px 14px rgba(28,30,46,.05);
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #0e0f1c; --surface: #171a2c; --surface-alt: #1f2340;
    --text: #eae8f3; --text-muted: #9a9dbb; --border: #2b2f4d;
    --accent: #ab9de6; --accent-soft: #262a4d; --gold: #dcae66;
    --shadow: 0 1px 2px rgba(0,0,0,.4), 0 6px 20px rgba(0,0,0,.35);
  }
}
* { box-sizing: border-box; }
html, body { margin: 0; background: var(--bg); }
body {
  color: var(--text);
  font-family: "Yu Gothic", "Hiragino Sans", "Meiryo", sans-serif;
  line-height: 1.6;
}
.mono { font-family: Consolas, "SF Mono", monospace; font-variant-numeric: tabular-nums; }
h1, h2, h3 { font-family: "Yu Mincho", "YuMincho", "Hiragino Mincho ProN", "MS Mincho", serif; }
.wrap { max-width: 1080px; margin: 0 auto; padding: 28px 20px 80px; }

.page-header { border-bottom: 1px solid var(--border); padding-bottom: 18px; margin-bottom: 24px; }
.page-header .eyebrow { font-size: .72rem; letter-spacing: .14em; color: var(--text-muted); text-transform: uppercase; }
.page-header h1 { font-size: clamp(1.6rem, 4vw, 2.1rem); margin: 4px 0; }
.target-line { color: var(--text-muted); font-size: .88rem; margin: 0; }

.tier { position: relative; margin: 0 0 40px; padding: 20px 20px 20px 56px;
  background: var(--surface); border: 1px solid var(--border); border-radius: 14px; box-shadow: var(--shadow); }
.tier-label {
  position: absolute; left: 14px; top: 20px; width: 30px; height: 30px; border-radius: 50%;
  background: var(--accent); color: #fff; display: flex; align-items: center; justify-content: center;
  font-family: Consolas, monospace; font-weight: 700; font-size: .95rem;
}
.tier h2 { font-size: 1.15rem; margin: 0 0 10px; }
.summary-text { color: var(--text); font-size: .92rem; background: var(--accent-soft); padding: 10px 14px; border-radius: 10px; }

.moon-timeline { display: flex; gap: 6px; overflow-x: auto; padding-bottom: 4px; margin-top: 14px; }
.moon-tick { flex: 0 0 62px; text-align: center; }
.moon-date { font-size: .68rem; color: var(--text-muted); font-family: Consolas, monospace; }
.moon-icon { font-size: 1.4rem; margin: 2px 0; }
.moon-bar-track { height: 5px; background: var(--surface-alt); border-radius: 3px; overflow: hidden; }
.moon-bar-fill { height: 100%; background: var(--gold); }
.moon-detail { font-size: .62rem; color: var(--text-muted); margin-top: 2px; }

.empty-note { color: var(--text-muted); background: var(--surface-alt); padding: 12px 16px; border-radius: 10px; font-size: .9rem; }

.wmap-block { margin-bottom: 24px; padding: 14px 16px; background: var(--surface-alt); border-radius: 10px; }
.wmap-block h3 { font-size: .95rem; margin: 0 0 10px; }
.wmap-row { display: flex; gap: 12px; overflow-x: auto; padding-bottom: 4px; }
.wmap-card { margin: 0; flex: 0 0 auto; text-align: center; }
.wmap-card img { display: block; width: 220px; max-width: 60vw; border: 1px solid var(--border); border-radius: 6px; background: #fff; }
.wmap-card figcaption { font-size: .72rem; color: var(--text-muted); margin-top: 4px; }
.wmap-commentary { font-size: .88rem; margin: 12px 0 6px; }
.wmap-caveat { font-size: .68rem; color: var(--text-muted); margin: 0; line-height: 1.5; }
.wmap-stale-warning {
  font-size: .82rem; font-weight: 700; margin: 0; padding: 8px 12px; line-height: 1.5;
  background: #fdecea; color: #8a2c1d; border: 1px solid #e5a79c; border-radius: 8px;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) .wmap-stale-warning { background: #402320; color: #f3b3a4; border-color: #7a3a30; }
}
:root[data-theme="dark"] .wmap-stale-warning { background: #402320; color: #f3b3a4; border-color: #7a3a30; }

.cand-group { margin-bottom: 28px; }
.cand-group:last-child { margin-bottom: 0; }
.group-title { font-size: 1.02rem; margin: 0 0 4px; }
.group-note { font-size: .78rem; color: var(--text-muted); margin: 0 0 12px; }
.weather-note { font-size: .85rem; color: var(--text); background: var(--accent-soft);
  padding: 8px 12px; border-radius: 8px; margin: 0 0 14px; }

.sky-guide { margin-bottom: 28px; padding-bottom: 24px; border-bottom: 1px solid var(--border); }
.sky-guide .guide-list { list-style: none; margin: 10px 0 0; padding: 14px 16px; display: grid; gap: 8px;
  font-size: .88rem; background: var(--surface-alt); border-radius: 10px; }
.guide-list b { color: var(--accent); }

.tier2-layout { display: grid; grid-template-columns: 1fr 340px; gap: 20px; }
.cand-grid { display: grid; gap: 10px; }
.cand-card { display: grid; grid-template-columns: auto 1fr; gap: 14px;
  background: var(--surface-alt); border-radius: 10px; padding: 12px 14px; }
.cand-rank { font-family: Consolas, monospace; font-weight: 700; font-size: 1.1rem; color: var(--accent); padding-top: 2px; }
.cand-body h3 { font-size: 1rem; margin: 0 0 4px; }
.cand-muni { font-size: .78rem; color: var(--text-muted); font-family: "Yu Gothic", sans-serif; font-weight: 400; }
.cand-badges { display: flex; gap: 6px; margin-bottom: 6px; flex-wrap: wrap; }
.badge { font-size: .68rem; padding: 2px 8px; border-radius: 999px; }
.badge.score { background: var(--accent); color: #fff; font-family: Consolas, monospace; }
.badge.origin { background: var(--surface); border: 1px solid var(--border); color: var(--text-muted); }
.badge.dist { background: var(--surface); border: 1px solid var(--border); color: var(--gold); font-family: Consolas, monospace; }
.badge.nv { background: var(--gold); color: #fff; }
.nv-group .cand-rank { font-size: 1.2rem; }
.cand-stats { display: grid; grid-template-columns: 1fr 1fr; gap: 4px 12px; margin: 0 0 8px; font-size: .8rem; }
.cand-stats dt { color: var(--text-muted); display: inline; }
.cand-stats dd { display: inline; margin: 0 0 0 4px; }
.cand-stats div { grid-column: span 1; }
.btn-maps { display: inline-block; font-size: .78rem; padding: 6px 12px; border-radius: 8px;
  background: var(--accent); color: #fff; text-decoration: none; }

.map-panel { display: flex; flex-direction: column; align-items: center; gap: 8px; }
.schema-map { width: 100%; max-width: 320px; border: 1px solid var(--border); border-radius: 10px; background: var(--surface-alt); }
.map-bg { fill: var(--surface-alt); }
.grid-line { stroke: var(--border); stroke-width: 1; }
.ref-dot { fill: var(--text-muted); }
.ref-label { font-size: 9px; fill: var(--text-muted); font-family: "Yu Gothic", sans-serif; }
.pin-link { cursor: pointer; }
.pin { fill: var(--accent); stroke: var(--surface); stroke-width: 1.5; }
.pin-num { font-size: 9px; fill: #fff; text-anchor: middle; font-family: Consolas, monospace; font-weight: 700; }
.map-caption { font-size: .7rem; color: var(--text-muted); text-align: center; margin: 0; }

.msm-note { font-size: .82rem; color: var(--accent); background: var(--accent-soft); display: inline-block;
  padding: 4px 12px; border-radius: 999px; margin: 0 0 14px; }
.calendar-scroll { overflow-x: auto; }
.calendar-row { display: flex; gap: 10px; min-width: max-content; padding-bottom: 8px; }
.cal-col { flex: 0 0 190px; background: var(--surface-alt); border-radius: 10px; padding: 12px; }
.cal-date { font-family: Consolas, monospace; font-weight: 700; font-size: .95rem; }
.cal-weekday { font-weight: 400; color: var(--text-muted); font-size: .75rem; margin-left: 4px; }
.cal-icon { font-size: 1.5rem; margin: 4px 0; }
.cal-moonfree { font-size: .7rem; color: var(--text-muted); margin-bottom: 8px; font-family: Consolas, monospace; }
.cal-list { list-style: none; margin: 0; padding: 0; display: grid; gap: 10px; }
.cal-list li { border-top: 1px solid var(--border); padding-top: 8px; }
.cal-site-name { font-size: .85rem; font-weight: 700; }
.cal-site-muni { font-size: .68rem; color: var(--text-muted); font-weight: 400; }
.cal-site-badge { font-size: .65rem; color: var(--accent); margin: 2px 0 4px; }
.cal-chance { font-size: .72rem; color: var(--text); }
.cal-empty { font-size: .78rem; color: var(--text-muted); }

.page-footer { margin-top: 30px; padding-top: 16px; border-top: 1px solid var(--border);
  font-size: .74rem; color: var(--text-muted); }

@media (max-width: 820px) {
  .tier2-layout { grid-template-columns: 1fr; }
  .map-panel { order: -1; }
}
"""


if __name__ == "__main__":
    main()
