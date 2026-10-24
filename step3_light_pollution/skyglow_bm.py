"""NASA Black Marble 起点の全天スカイグロー指数(段階LP1)。

手法は Duriscoe et al. 2018, J. Quant. Spectrosc. Radiat. Transf. 214, 133-145(CC BY)の
「距離で重み付けした上向き放射輝度の近傍和」(式9・式11)。式・係数の出典と本実装での
判断は METHOD.md に記録している。

    ALR = (1/C) * sum_i r_i * d_i^(-alpha(d_i)),   alpha(d) = 2.3 * (d/350)^0.28   (d は km)

    r_i : 画素の上向き放射輝度 [nW/cm^2/sr](0.5未満は0に切り捨て、論文§2.2.2)
    C   : 較正定数 562.72(論文§3.2。米国西部の24地点で得た値)
    ALR : 全天平均の人工スカイグロー / 自然の背景(250 uc d/m^2)の比

★ 出力は絶対値ではなく**相対的な暗さの指数**として扱う。理由:
  - Cは米国西部・VIIRS月次コンポジット(Garstang K=0.35、乾燥した低エアロゾルの空)で得た値。
    日本(湿潤・エアロゾル多め)・Black Marble年次コンポジット(別処理のデータ)へは未較正。
  - Black Marbleは地表の輝度で、空の明るさそのものではない。
  - 光源の分光特性(LEDへの置換など)による系統差が論文の限界(§4.3.1)に挙がっている。
  本モジュールの係数のうち、論文に無く本実装で決めたものは UNCALIBRATED を付けて区別する。

入力データの取得は fetch_black_marble.py、HDF5の読み込みと格子の作成は build_skyglow_bm.py。
本モジュールはnumpyだけで動き、ネットワークもトークンも使わない。
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent

# --- 論文由来(出典は METHOD.md) -------------------------------------------------
ALPHA_COEF = 2.3          # 式(11) 2.3
ALPHA_REF_KM = 350.0      # 式(11) (d/350)
ALPHA_EXP = 0.28          # 式(11) ^0.28
RADIUS_KM = 300.0         # 影響半径。論文§2.3・§2.5(300km、38リング)
NOISE_CLIP_NW = 0.5       # 0.5 nW/cm2/sr 未満は0(論文§2.2.2)
ALR_CALIBRATION_C = 562.72  # 式(9)のC。論文§3.2(米国西部の観測で得た値。日本では未較正)
PAPER_CELL_KM = 0.45      # 論文の等積画素(450m)。重みの面積正規化の基準

# --- 本実装で決めた値(論文に無い) ---------------------------------------------------
PLANE_PIXEL_KM = 1.0      # UNCALIBRATED: 計算用の平面格子の画素(km)。近傍和は1km画素へ集約してから畳み込む
D_MIN_KM = 0.4            # UNCALIBRATED: 距離0(同じ画素内)の光源に使う代表距離(1km画素内の平均距離≒0.38km)
EARTH_RADIUS_KM = 6371.0088  # 球近似(方位等距離図法の中心から700km以内の誤差は0.3%以下)

# --- 対象範囲(地点を足しても再生成だけで追従できるよう、スクリプトで算出する) -------
OUTPUT_PAD_DEG = 0.5      # 出力格子=地点の外接矩形+この余白(度)
INPUT_MARGIN_KM = RADIUS_KM  # 入力範囲=出力範囲+影響半径。指示書の「約200km」より、論文の影響距離300kmを優先
OUTPUT_STEP_DEG = 0.01    # 出力格子の間隔(約1km)
KM_PER_DEG_LAT = 111.195  # 球近似

SPOTS_PATH = REPO_ROOT / "stargazing_spots.json"


def alpha(d_km):
    """式(11): 距離 d [km] でのWalker則の指数。"""
    d = np.asarray(d_km, dtype=float)
    return ALPHA_COEF * (d / ALPHA_REF_KM) ** ALPHA_EXP


def weight(d_km, d_min_km: float = D_MIN_KM):
    """d^(-alpha(d))。d_min未満は d_min として扱う(UNCALIBRATED)。"""
    d = np.maximum(np.asarray(d_km, dtype=float), d_min_km)
    return d ** (-alpha(d))


# ----------------------------------------------------------------------------
# 対象範囲
# ----------------------------------------------------------------------------
def spot_bbox(spots_path: Path = SPOTS_PATH) -> dict:
    """`spots`(主軸)の外接矩形。viewpoint_referenceは含めない。"""
    spots = json.loads(Path(spots_path).read_text(encoding="utf-8"))["spots"]
    lats = [s["lat"] for s in spots]
    lons = [s["lon"] for s in spots]
    return {"lat_min": min(lats), "lat_max": max(lats), "lon_min": min(lons), "lon_max": max(lons),
            "n_spots": len(spots)}


def output_extent(spots_path: Path = SPOTS_PATH, pad_deg: float = OUTPUT_PAD_DEG) -> dict:
    b = spot_bbox(spots_path)
    return {"lat_min": b["lat_min"] - pad_deg, "lat_max": b["lat_max"] + pad_deg,
            "lon_min": b["lon_min"] - pad_deg, "lon_max": b["lon_max"] + pad_deg}


def input_extent(spots_path: Path = SPOTS_PATH, pad_deg: float = OUTPUT_PAD_DEG,
                 margin_km: float = INPUT_MARGIN_KM) -> dict:
    """出力範囲に影響半径ぶんの余白を足した、必要な入力(輝度)の範囲。"""
    o = output_extent(spots_path, pad_deg)
    dlat = margin_km / KM_PER_DEG_LAT
    worst_lat = max(abs(o["lat_min"] - dlat), abs(o["lat_max"] + dlat))  # cosが最小になる緯度
    dlon = margin_km / (KM_PER_DEG_LAT * math.cos(math.radians(worst_lat)))
    return {"lat_min": o["lat_min"] - dlat, "lat_max": o["lat_max"] + dlat,
            "lon_min": o["lon_min"] - dlon, "lon_max": o["lon_max"] + dlon}


def tiles_for_extent(ext: dict) -> list[str]:
    """Black Marbleのタイル名(hXXvYY、10度四方、h=経度、v=緯度[北から])。"""
    h0, h1 = int((ext["lon_min"] + 180) // 10), int((ext["lon_max"] + 180) // 10)
    v0, v1 = int((90 - ext["lat_max"]) // 10), int((90 - ext["lat_min"]) // 10)
    return [f"h{h:02d}v{v:02d}" for v in range(v0, v1 + 1) for h in range(h0, h1 + 1)]


# ----------------------------------------------------------------------------
# 方位等距離図法(中心からの距離が正しい平面)
# ----------------------------------------------------------------------------
@dataclass(frozen=True)
class PlaneGeometry:
    lat0: float
    lon0: float
    pixel_km: float
    x_min: float  # 平面左端(km、東が正)
    y_max: float  # 平面上端(km、北が正)
    nx: int
    ny: int


def project(lat, lon, lat0: float, lon0: float):
    """緯度経度[度] -> 平面(x東, y北)[km]。方位等距離図法(球)。"""
    phi, lam = np.radians(np.asarray(lat, float)), np.radians(np.asarray(lon, float))
    phi0, lam0 = math.radians(lat0), math.radians(lon0)
    dl = lam - lam0
    cos_c = math.sin(phi0) * np.sin(phi) + math.cos(phi0) * np.cos(phi) * np.cos(dl)
    c = np.arccos(np.clip(cos_c, -1.0, 1.0))
    with np.errstate(invalid="ignore", divide="ignore"):
        k = np.where(c < 1e-12, 1.0, c / np.sin(c))
    x = EARTH_RADIUS_KM * k * np.cos(phi) * np.sin(dl)
    y = EARTH_RADIUS_KM * k * (math.cos(phi0) * np.sin(phi) - math.sin(phi0) * np.cos(phi) * np.cos(dl))
    return x, y


def unproject(x, y, lat0: float, lon0: float):
    """平面(km) -> 緯度経度[度]。"""
    x, y = np.asarray(x, float), np.asarray(y, float)
    phi0, lam0 = math.radians(lat0), math.radians(lon0)
    rho = np.hypot(x, y)
    c = rho / EARTH_RADIUS_KM
    with np.errstate(invalid="ignore", divide="ignore"):
        sin_c, cos_c = np.sin(c), np.cos(c)
        ratio = np.where(rho < 1e-12, 0.0, y * sin_c / np.where(rho < 1e-12, 1.0, rho))
        phi = np.arcsin(np.clip(cos_c * math.sin(phi0) + ratio * math.cos(phi0), -1.0, 1.0))
        lam = lam0 + np.arctan2(x * sin_c,
                                np.where(rho < 1e-12, 1.0, rho) * math.cos(phi0) * cos_c
                                - y * math.sin(phi0) * sin_c)
    return np.degrees(phi), np.degrees(lam)


def plane_geometry_for_extent(ext: dict, pixel_km: float = PLANE_PIXEL_KM) -> PlaneGeometry:
    lat0 = (ext["lat_min"] + ext["lat_max"]) / 2
    lon0 = (ext["lon_min"] + ext["lon_max"]) / 2
    # 範囲の縁をたどって平面上の外接矩形を求める
    ls = np.linspace(ext["lat_min"], ext["lat_max"], 60)
    ms = np.linspace(ext["lon_min"], ext["lon_max"], 60)
    la = np.concatenate([ls, ls, np.full(60, ext["lat_min"]), np.full(60, ext["lat_max"])])
    lo = np.concatenate([np.full(60, ext["lon_min"]), np.full(60, ext["lon_max"]), ms, ms])
    x, y = project(la, lo, lat0, lon0)
    x_min, y_max = float(x.min()), float(y.max())
    nx = int(math.ceil((float(x.max()) - x_min) / pixel_km)) + 1
    ny = int(math.ceil((y_max - float(y.min())) / pixel_km)) + 1
    return PlaneGeometry(lat0, lon0, pixel_km, x_min, y_max, nx, ny)


def to_plane(radiance, lat_top: float, lon_left: float, dlat: float, dlon: float,
             geom: PlaneGeometry, clip_nw: float = NOISE_CLIP_NW) -> np.ndarray:
    """緯度経度格子(行が北→南)の輝度を、等距離平面の画素へ集約する。

    各画素の寄与は「輝度 × 画素の面積 / (0.45km)^2」(論文の等積450m画素に換算)。
    集約は前進投影(画素中心を平面へ写して足し込む)で、総量を保つ。
    欠損(NaN)と clip_nw 未満は0として扱う(論文§2.2.2)。
    """
    r = np.asarray(radiance, dtype=np.float64)
    ny_src, nx_src = r.shape
    lats = lat_top - (np.arange(ny_src) + 0.5) * dlat
    lons = lon_left + (np.arange(nx_src) + 0.5) * dlon
    r = np.where(np.isfinite(r) & (r >= clip_nw), r, 0.0)
    out = np.zeros(geom.ny * geom.nx, dtype=np.float64)
    cell_h_km = dlat * KM_PER_DEG_LAT
    for i in range(ny_src):  # 行ごと(メモリを抑える)
        row = r[i]
        nz = row > 0
        if not nz.any():
            continue
        lo = lons[nz]
        la = np.full(lo.shape, lats[i])
        x, y = project(la, lo, geom.lat0, geom.lon0)
        ix = np.floor((x - geom.x_min) / geom.pixel_km + 0.5).astype(np.int64)
        iy = np.floor((geom.y_max - y) / geom.pixel_km + 0.5).astype(np.int64)
        ok = (ix >= 0) & (ix < geom.nx) & (iy >= 0) & (iy < geom.ny)
        if not ok.any():
            continue
        area_km2 = cell_h_km * (dlon * KM_PER_DEG_LAT * math.cos(math.radians(lats[i])))
        w = row[nz][ok] * (area_km2 / PAPER_CELL_KM ** 2)
        np.add.at(out, iy[ok] * geom.nx + ix[ok], w)
    return out.reshape(geom.ny, geom.nx)


# ----------------------------------------------------------------------------
# 近傍和(式9)
# ----------------------------------------------------------------------------
def kernel(pixel_km: float, radius_km: float = RADIUS_KM) -> np.ndarray:
    """距離重み d^-alpha(d) の畳み込みカーネル(半径radius_km、円の外は0)。"""
    n = int(math.floor(radius_km / pixel_km))
    ax = np.arange(-n, n + 1) * pixel_km
    d = np.hypot(ax[None, :], ax[:, None])
    k = weight(d)
    k[d > radius_km] = 0.0
    return k


def neighborhood_sum(source: np.ndarray, pixel_km: float, radius_km: float = RADIUS_KM) -> np.ndarray:
    """各画素について、半径内の source[j] * d_ij^-alpha(d_ij) を足し合わせる(FFT畳み込み)。

    sourceの外側は光源が無いものとして扱うので、縁から radius_km 以内の画素は過小になる
    (`valid_mask`で除外できる)。自分自身の画素は D_MIN_KM の距離で数える。
    """
    k = kernel(pixel_km, radius_km)
    ny, nx = source.shape
    ky, kx = k.shape
    fy, fx = ny + ky - 1, nx + kx - 1
    # 速いサイズに丸める(numpyのFFTは任意サイズ可だが素因数が大きいと遅い)
    fy, fx = _fast_len(fy), _fast_len(fx)
    full = np.fft.irfft2(np.fft.rfft2(source, (fy, fx)) * np.fft.rfft2(k, (fy, fx)), (fy, fx))
    oy, ox = ky // 2, kx // 2
    out = full[oy:oy + ny, ox:ox + nx]
    return np.maximum(out, 0.0)  # FFTの丸め誤差で出る微小な負値を除く


def _fast_len(n: int) -> int:
    while True:
        m = n
        for p in (2, 3, 5):
            while m % p == 0:
                m //= p
        if m == 1:
            return n
        n += 1


def valid_mask(shape: tuple[int, int], pixel_km: float, radius_km: float = RADIUS_KM) -> np.ndarray:
    """影響半径が格子の外へはみ出さない画素(近傍和が欠けていない画素)。"""
    n = int(math.floor(radius_km / pixel_km))
    m = np.zeros(shape, dtype=bool)
    if shape[0] > 2 * n and shape[1] > 2 * n:
        m[n:shape[0] - n, n:shape[1] - n] = True
    return m


def alr_from_sum(weighted_sum: np.ndarray, calibration: float = ALR_CALIBRATION_C) -> np.ndarray:
    return weighted_sum / calibration


# ----------------------------------------------------------------------------
# 点・格子への取り出し
# ----------------------------------------------------------------------------
def sample_plane(values: np.ndarray, geom: PlaneGeometry, lat, lon) -> np.ndarray:
    """平面格子 values を緯度経度の点で双一次補間する。範囲外はNaN。"""
    x, y = project(lat, lon, geom.lat0, geom.lon0)
    fx = (x - geom.x_min) / geom.pixel_km
    fy = (geom.y_max - y) / geom.pixel_km
    x0, y0 = np.floor(fx).astype(int), np.floor(fy).astype(int)
    tx, ty = fx - x0, fy - y0
    ok = (x0 >= 0) & (y0 >= 0) & (x0 + 1 < values.shape[1]) & (y0 + 1 < values.shape[0])
    x0c, y0c = np.clip(x0, 0, values.shape[1] - 2), np.clip(y0, 0, values.shape[0] - 2)
    v = ((1 - tx) * (1 - ty) * values[y0c, x0c] + tx * (1 - ty) * values[y0c, x0c + 1]
         + (1 - tx) * ty * values[y0c + 1, x0c] + tx * ty * values[y0c + 1, x0c + 1])
    return np.where(ok, v, np.nan)


# ----------------------------------------------------------------------------
# 派生データ(実行時はこれだけを読む。トークンもネットワークも不要)
# ----------------------------------------------------------------------------
DATA_DIR = Path(__file__).resolve().parent / "data"


@dataclass
class DerivedGrid:
    """0.01度格子のALR(行が北→南)。`build_skyglow_bm.py`が作る。"""
    alr: np.ndarray
    lat_top: float
    lon_left: float
    step: float
    meta: dict

    @classmethod
    def load(cls, path: Path) -> "DerivedGrid":
        z = np.load(path, allow_pickle=False)
        return cls(z["alr"].astype(np.float64), float(z["lat_top"]), float(z["lon_left"]),
                   float(z["step"]), json.loads(str(z["meta"])))

    def at(self, lat, lon) -> np.ndarray:
        """緯度経度の点でALRを双一次補間する。範囲外・欠損はNaN。"""
        fx = (np.asarray(lon, float) - self.lon_left) / self.step
        fy = (self.lat_top - np.asarray(lat, float)) / self.step
        x0, y0 = np.floor(fx).astype(int), np.floor(fy).astype(int)
        tx, ty = fx - x0, fy - y0
        ok = (x0 >= 0) & (y0 >= 0) & (x0 + 1 < self.alr.shape[1]) & (y0 + 1 < self.alr.shape[0])
        x0c, y0c = np.clip(x0, 0, self.alr.shape[1] - 2), np.clip(y0, 0, self.alr.shape[0] - 2)
        a = self.alr
        v = ((1 - tx) * (1 - ty) * a[y0c, x0c] + tx * (1 - ty) * a[y0c, x0c + 1]
             + (1 - tx) * ty * a[y0c + 1, x0c] + tx * ty * a[y0c + 1, x0c + 1])
        return np.where(ok, v, np.nan)


def rank_pct(values) -> np.ndarray:
    """値が小さい(=暗い)ほど小さい百分位(0=最も暗い、100=最も明るい)。同値は平均順位。"""
    v = np.asarray(values, float)
    order = v.argsort(kind="stable")
    ranks = np.empty(len(v))
    ranks[order] = np.arange(len(v))
    for val in np.unique(v):
        m = v == val
        ranks[m] = ranks[m].mean()
    return 100.0 * ranks / max(len(v) - 1, 1)


def annotate_spots(spots: list[dict], grid: DerivedGrid) -> list[dict]:
    """各地点に `skyglow_bm_index`(ALR、小さいほど暗い)と `skyglow_bm_rank_pct` を付けた
    **新しいリスト**を返す(入力は変更しない)。範囲外の地点は両方None。"""
    alr = grid.at([s["lat"] for s in spots], [s["lon"] for s in spots])
    ok = np.isfinite(alr)
    pct = np.full(len(spots), np.nan)
    if ok.any():
        pct[ok] = rank_pct(alr[ok])
    out = []
    for s, a, p in zip(spots, alr, pct):
        d = dict(s)
        d["skyglow_bm_index"] = None if not np.isfinite(a) else round(float(a), 4)
        d["skyglow_bm_rank_pct"] = None if not np.isfinite(p) else round(float(p), 2)
        out.append(d)
    return out
