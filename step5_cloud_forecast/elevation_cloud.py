"""星の日和(hoshibiyori) ステップ5b: 観測者標高を考慮した雲量判定(見上げ型ハイブリッド)。

地表(または山上)の観測者が空を見上げたとき、空のどれだけが雲に覆われるか
(「視界遮蔽雲量」)と、観測者より下に広がる雲の量(「雲海指数」)を時刻ごとに算出する。

## 設計(2026-09-13、星空撮影者向けに再設計)

主指標は **モデル本来の雲量**(Open-Meteoの`cloud_cover`=全層、`cloud_cover_low/mid/high`=
下層0〜3km/中層3〜8km/上層8km以上。JMA MSM・ECMWF IFSともモデルが直接出力する値)である。
気圧面別雲量(`cloud_cover_XXXhPa`)は相対湿度からの近似値(Sundqvist型)で「空気の飽和度」の
代理指標に過ぎず、しかも隣接する気圧面にまたがる1枚の雲を複数の独立した層として重ね合わせると
雲量を大きく過大評価する(2026-09-13の検証: 低標高6地点×72時間で全層雲量に対し平均+15.6pt、
30%閾値で46/414時間を誤って「曇り」判定)。地表から見上げる星空撮影では、モデル自身が
重なりを考慮して算出した全層雲量がそのまま正解に最も近い。

気圧面別雲量(+各面のジオポテンシャル高度=実高度)は、**観測者より下にある雲を差し引く**
目的にだけ使う。手順:
1. 下層/中層/上層の各層について、その層に属する気圧面の(近似)雲量を、観測者標高より
   上にある割合で重み付けし、「層のうち観測者より上にある割合」w_layer(0〜1)を求める
   (層内に気圧面の雲が無ければ層の高度範囲と観測者標高の幾何的な割合で代用)。
2. 観測者より上の分 = 層雲量 × w_layer、下の分 = 層雲量 × (1 - w_layer)。
3. 視界遮蔽雲量 = 全層雲量 × (上の分の合成 / 元の3層の合成)。低標高地点では全てのw=1と
   なり**モデル本来の全層雲量に一致**する。高所では観測者より下の雲が抜けた分だけ下がる。
4. 雲海指数 = 下の分の3層合成。
層の合成は「隣接して雲のある層はmax(同じ雲塊)、雲の無い層で隔てられた塊同士は
ランダム重ね合わせ」(maximum-random overlap、気象モデルの放射計算で標準的な仮定)。
モデル本来の値が欠損している時刻だけ、従来どおり気圧面別雲量のみからの合成
(ただしランダム→maximum-random)にフォールバックする。

## 経緯

- 2026-09-06: 気圧面を500hPaまでしか見ておらず上層雲を丸ごと見落とす不具合を300hPaまで
  拡張して修正(弥彦山の事例)。
- 2026-09-13(朝): yamabiyoriの設計を取り込み、各面の高度を標準大気の固定値から毎時の
  ジオポテンシャル高度に変更、面ごとの欠損許容、900/800hPa追加(ユーザー承認のもと
  yamabiyori側を読み取り専用で参照。コードのコピーはしていない)。
- 2026-09-13(同日): 「星空撮影者は地表から見上げるので登山者と雲の見方が違う」というユーザーの
  指摘を受けて点検し、上記の過大評価を確認。モデル本来の雲量を主指標とする本設計に再構成した。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from cloud_forecast import ECMWF_MAX_FORECAST_DAYS, ECMWF_MODEL, JST, MSM_MAX_FORECAST_DAYS, MSM_MODEL

# 取得する気圧面(気圧の高い=低高度から)。300hPaがMSM・ECMWF双方から値が取れる上限
# (250hPa以上はjma_msmがnull)。900/800hPaはjma_msmのみ(ecmwf_ifs025はnull、面ごとに欠損許容)。
PRESSURE_LEVELS_HPA = [1000, 925, 900, 850, 800, 700, 600, 500, 400, 300]

# Open-Meteoの下層/中層/上層雲量の高度区分(海面からの高度、公式ドキュメントより)。
NATIVE_LAYER_BOUNDS_M: dict[str, tuple[float, float]] = {
    "low": (0.0, 3000.0),
    "mid": (3000.0, 8000.0),
    "high": (8000.0, 13000.0),  # 上端は幾何的な割合の計算用の便宜値(実際は上限なし)
}
_NATIVE_VARS = {"total": "cloud_cover", "low": "cloud_cover_low", "mid": "cloud_cover_mid", "high": "cloud_cover_high"}

_SEA_LEVEL_PRESSURE_HPA = 1013.25


def pressure_to_height_m(pressure_hpa: float) -> float:
    """標準大気近似(ICAO標準大気)で気圧(hPa)を高度(m)に変換する(ジオポテンシャル高度欠損時の代替)。"""
    return 44330.0 * (1.0 - (pressure_hpa / _SEA_LEVEL_PRESSURE_HPA) ** (1.0 / 5.255))


LEVEL_HEIGHTS_M = {p: pressure_to_height_m(p) for p in PRESSURE_LEVELS_HPA}


def _cloud_var(p: int) -> str:
    return f"cloud_cover_{p}hPa"


def _gph_var(p: int) -> str:
    return f"geopotential_height_{p}hPa"


def level_hourly_vars() -> str:
    """Open-Meteoへの要求変数文字列(モデル本来の全層/下層/中層/上層雲量+気圧面別雲量+各面の実高度)。

    area_prescreen.py など同じキャッシュキーを共有したい呼び出し側もこれを使うこと
    (変数文字列が違うとGridCloudCacheのキーが変わり、API呼び出しが重複する)。
    """
    return ",".join(
        list(_NATIVE_VARS.values())
        + [_cloud_var(p) for p in PRESSURE_LEVELS_HPA]
        + [_gph_var(p) for p in PRESSURE_LEVELS_HPA]
    )


def _pressure_hourly_vars() -> str:  # 後方互換の別名
    return level_hourly_vars()


@dataclass
class HourlyLevelCloud:
    dt_local: datetime
    cloud_by_height: dict[float, float]  # その時刻の各気圧面の実高度(m) -> 近似雲量(%)。欠損面は含まない
    source: str  # "MSM" / "ECMWF" / "N/A"(過半数の値を供給したモデル)
    cloud_total: float | None = None  # モデル本来の全層雲量(%)
    cloud_low: float | None = None
    cloud_mid: float | None = None
    cloud_high: float | None = None


@dataclass
class _HourRaw:
    levels: dict[int, tuple[float, float]] = field(default_factory=dict)  # hPa -> (高度m, 雲量%)
    native: dict[str, float] = field(default_factory=dict)  # "total"/"low"/"mid"/"high" -> 雲量%


def _to_dict_by_time(hourly: dict[str, list] | None) -> dict[datetime, _HourRaw]:
    """APIレスポンスを時刻ごとの生データに変換する。nullの値は含めない(欠損は面・変数ごとに落とす)。

    気圧面の高度はジオポテンシャル高度を優先し、それだけがnullなら標準大気値で補う。
    """
    if hourly is None:
        return {}
    result: dict[datetime, _HourRaw] = {}
    times = hourly["time"]

    def val(series_name: str, i: int):
        series = hourly.get(series_name)
        if not series or i >= len(series):
            return None
        return series[i]

    for i, t_str in enumerate(times):
        raw = _HourRaw()
        for p in PRESSURE_LEVELS_HPA:
            cc = val(_cloud_var(p), i)
            if cc is None:
                continue
            gph = val(_gph_var(p), i)
            raw.levels[p] = (float(gph) if gph is not None else LEVEL_HEIGHTS_M[p], float(cc))
        for key, var in _NATIVE_VARS.items():
            v = val(var, i)
            if v is not None:
                raw.native[key] = float(v)
        if raw.levels or raw.native:
            result[datetime.fromisoformat(t_str).replace(tzinfo=JST)] = raw
    return result


def _merge_hour(msm: _HourRaw | None, ecmwf: _HourRaw | None, dt_local: datetime) -> HourlyLevelCloud:
    """ある時刻について、面・変数ごとに「MSMの値があればMSM、なければECMWF」で埋める。

    sourceは有効な値(気圧面+本来の雲量4変数)の過半数を供給したモデル。MSM圏内は全てMSM、
    圏外は全てECMWFになるのが通常で、混在はECMWFがnullを返す900/800hPaの補完など限定的。
    """
    msm = msm or _HourRaw()
    ecmwf = ecmwf or _HourRaw()
    n_msm = n_ecmwf = 0
    cloud_by_height: dict[float, float] = {}
    for p in PRESSURE_LEVELS_HPA:
        if p in msm.levels:
            h, c = msm.levels[p]
            n_msm += 1
        elif p in ecmwf.levels:
            h, c = ecmwf.levels[p]
            n_ecmwf += 1
        else:
            continue
        cloud_by_height[h] = c
    native: dict[str, float | None] = {}
    for key in _NATIVE_VARS:
        if key in msm.native:
            native[key] = msm.native[key]
            n_msm += 1
        elif key in ecmwf.native:
            native[key] = ecmwf.native[key]
            n_ecmwf += 1
        else:
            native[key] = None
    if n_msm + n_ecmwf == 0:
        source = "N/A"
    else:
        source = "MSM" if n_msm >= n_ecmwf else "ECMWF"
    return HourlyLevelCloud(
        dt_local=dt_local, cloud_by_height=cloud_by_height, source=source,
        cloud_total=native["total"], cloud_low=native["low"], cloud_mid=native["mid"], cloud_high=native["high"],
    )


def get_level_cloud_forecast(lat: float, lon: float, start_dt_local: datetime, end_dt_local: datetime,
                              cache: "GridCloudCache | None" = None) -> list[HourlyLevelCloud]:
    """モデル本来の雲量(全層/下層/中層/上層)と気圧面別雲量(+実高度)の時系列を取得する(MSM近距離+ECMWF遠距離)。

    cache: grid_cache.GridCloudCache を渡すと格子セル単位でAPI呼び出しを共有する。
    forecast_daysは常に最大値で固定し、呼び出し時刻に依存させない
    (異なる夜への問い合わせでも同一セルなら同一キャッシュキーになるようにするため)。
    """
    from grid_cache import GridCloudCache

    if cache is None:
        cache = GridCloudCache()

    variables = level_hourly_vars()
    msm_by_time = _to_dict_by_time(cache.get_hourly(lat, lon, MSM_MODEL, MSM_MAX_FORECAST_DAYS, variables))
    ecmwf_by_time = _to_dict_by_time(cache.get_hourly(lat, lon, ECMWF_MODEL, ECMWF_MAX_FORECAST_DAYS, variables))

    results = []
    t = start_dt_local.replace(minute=0, second=0, microsecond=0)
    while t <= end_dt_local:
        results.append(_merge_hour(msm_by_time.get(t), ecmwf_by_time.get(t), t))
        t += timedelta(hours=1)
    return results


# ---------------------------------------------------------------------------
# 合成ロジック
# ---------------------------------------------------------------------------

def _slab_bounds(heights_asc: list[float]) -> list[tuple[float, float]]:
    """各気圧面の高度を中心とする「層」の上下境界(隣接面の中点)。両端は内側の間隔を外側にも適用。

    最下層の下端は海面(0m)より下にはしない(地面より下に雲は無いため)。面が1つなら上下1000m。
    """
    n = len(heights_asc)
    if n == 1:
        return [(max(0.0, heights_asc[0] - 1000.0), heights_asc[0] + 1000.0)]
    midpoints = [(heights_asc[i] + heights_asc[i + 1]) / 2.0 for i in range(n - 1)]
    bounds = []
    for i in range(n):
        lower = midpoints[i - 1] if i > 0 else max(0.0, 2 * heights_asc[0] - midpoints[0])
        upper = midpoints[i] if i < n - 1 else 2 * heights_asc[-1] - midpoints[-1]
        bounds.append((lower, upper))
    return bounds


def _above_weight(height_m: float, upper: float, elevation_m: float) -> float:
    """高度height_mを中心とし上端upperまで広がる層の雲のうち、観測者(elevation_m)より上にある割合(0〜1)。

    観測者が面の中心高度以下なら全て上(1.0)。中心より上にいる場合は、中心から層の上端までの間で
    線形に減らす(上端以上なら0)。面の中心以下にいる観測者にその面の雲を割り引かないのは、
    地表付近の観測者が「1000hPa(約100〜200m)の霧・層雲」を全て頭上に見るため。
    """
    if elevation_m <= height_m:
        return 1.0
    if elevation_m >= upper:
        return 0.0
    return (upper - elevation_m) / (upper - height_m)


def _level_weights(cloud_by_height: dict[float, float], elevation_m: float) -> list[tuple[float, float, float]]:
    """[(高度m, 雲量%, 観測者より上の割合)] を高度昇順で返す。"""
    heights_asc = sorted(cloud_by_height)
    bounds = _slab_bounds(heights_asc)
    return [(h, cloud_by_height[h], _above_weight(h, upper, elevation_m)) for h, (_lower, upper) in zip(heights_asc, bounds)]


def max_random_overlap(values: list[float]) -> float:
    """高度順に並んだ層の雲量(%)を maximum-random overlap で合成した「空が覆われる割合」(%)。

    隣接して雲のある層は同じ雲塊とみなしてmaxを取り、雲量0の層で隔てられた塊同士は
    独立とみなしてランダムに重ね合わせる(1 - Π(1 - c_k))。
    従来の全層ランダム重ね合わせは、1枚の雲が複数の気圧面にまたがるだけで雲量を
    大きく過大評価していた(2026-09-13検証: 全層雲量に対し平均+15.6pt → max-randomで-0.4pt)。
    """
    groups: list[float] = []
    cur: list[float] = []
    for v in values:
        if v > 0.0:
            cur.append(v)
        elif cur:
            groups.append(max(cur))
            cur = []
    if cur:
        groups.append(max(cur))
    clear = 1.0
    for g in groups:
        clear *= (1.0 - min(g, 100.0) / 100.0)
    return (1.0 - clear) * 100.0


def _weighted_average(cloud_by_height: dict[float, float], elevation_m: float, above: bool) -> float | None:
    """気圧面別(近似)雲量のみから、観測者より上(above=True)/下(above=False)の雲を合成する(%)。

    モデル本来の雲量が欠損している時刻のフォールバック専用。合成はmax_random_overlap。
    関数名は後方互換のため維持。
    """
    if not cloud_by_height:
        return None
    rows = _level_weights(cloud_by_height, elevation_m)
    weights = [w if above else 1.0 - w for _h, _c, w in rows]
    if sum(weights) <= 1e-9:
        return None
    return max_random_overlap([c * w for (_h, c, _w), w in zip(rows, weights)])


def _layer_above_fraction(rows: list[tuple[float, float, float]], elevation_m: float, layer: str) -> float:
    """下層/中層/上層のうち観測者より上にある割合(0〜1)。

    その層の高度範囲に属する気圧面の(近似)雲量を重みとして、「層内の雲のうち観測者より上にある割合」
    を求める(雲がどの高さにあるかを気圧面プロファイルから読む)。層内に雲のある気圧面が無い、
    または気圧面データ自体が無い場合は、層の高度範囲と観測者標高の幾何的な割合で代用する。
    """
    lo, hi = NATIVE_LAYER_BOUNDS_M[layer]
    mass_total = mass_above = 0.0
    for h, c, w in rows:
        if lo <= h < hi and c > 0.0:
            mass_total += c
            mass_above += c * w
    if mass_total > 1e-9:
        return mass_above / mass_total
    if elevation_m <= lo:
        return 1.0
    if elevation_m >= hi:
        return 0.0
    return (hi - elevation_m) / (hi - lo)


def sky_obstruction_and_cloud_sea(h: HourlyLevelCloud, elevation_m: float) -> tuple[float | None, float | None]:
    """1時刻分の(視界遮蔽雲量%, 雲海指数%)。モジュールdocstringの手順1〜4を実装する。"""
    native_ok = all(v is not None for v in (h.cloud_total, h.cloud_low, h.cloud_mid, h.cloud_high))
    if not native_ok:
        if not h.cloud_by_height:
            return None, None
        return (_weighted_average(h.cloud_by_height, elevation_m, above=True),
                _weighted_average(h.cloud_by_height, elevation_m, above=False))

    rows = _level_weights(h.cloud_by_height, elevation_m) if h.cloud_by_height else []
    layers = [("low", h.cloud_low), ("mid", h.cloud_mid), ("high", h.cloud_high)]
    fractions = [_layer_above_fraction(rows, elevation_m, name) for name, _c in layers]
    raw = [c for _name, c in layers]
    above = [c * w for c, w in zip(raw, fractions)]
    below = [c * (1.0 - w) for c, w in zip(raw, fractions)]

    cloud_sea = max_random_overlap(below)
    comp_raw = max_random_overlap(raw)
    if comp_raw <= 1e-9:
        # 3層とも0だが全層値が非0という稀なケース: 観測者が全層の下にいる限りは全層値をそのまま使う
        obstruction = h.cloud_total if min(fractions) >= 1.0 - 1e-9 else h.cloud_total * max(fractions)
    else:
        obstruction = h.cloud_total * (max_random_overlap(above) / comp_raw)
    return max(0.0, min(100.0, obstruction)), max(0.0, min(100.0, cloud_sea))


def hourly_sky_obstruction_and_cloud_sea(hourly_levels: list[HourlyLevelCloud], elevation_m: float) -> list[dict]:
    """時刻ごとの視界遮蔽雲量(観測者より上の雲)と雲海指数(観測者より下の雲)を計算する。"""
    results = []
    for h in hourly_levels:
        obstruction, cloud_sea = sky_obstruction_and_cloud_sea(h, elevation_m)
        results.append({
            "dt_local": h.dt_local, "sky_obstruction": obstruction, "cloud_sea_index": cloud_sea, "source": h.source,
        })
    return results


def sky_obstruction_cloud_cover(lat: float, lon: float, elevation_m: float, dt_local: datetime,
                                 cache: "GridCloudCache | None" = None) -> float | None:
    """指定地点・標高・日時における「視界遮蔽雲量」(%)を返す。"""
    hourly_levels = get_level_cloud_forecast(lat, lon, dt_local, dt_local, cache=cache)
    if not hourly_levels:
        return None
    return sky_obstruction_and_cloud_sea(hourly_levels[0], elevation_m)[0]


def cloud_sea_index(lat: float, lon: float, elevation_m: float, dt_local: datetime,
                     cache: "GridCloudCache | None" = None) -> float | None:
    """指定地点・標高・日時における「雲海指数」(観測者より下の雲の合成、%)を返す。

    副産物としての診断指標。今回はログ出力用途のみ(本格活用は将来検討)。
    """
    hourly_levels = get_level_cloud_forecast(lat, lon, dt_local, dt_local, cache=cache)
    if not hourly_levels:
        return None
    value = sky_obstruction_and_cloud_sea(hourly_levels[0], elevation_m)[1]
    print(f"[雲海指数ログ] {dt_local.strftime('%Y-%m-%d %H:%M')} JST, 標高{elevation_m:.0f}m: "
          f"雲海指数={value if value is None else f'{value:.1f}%'}")
    return value
