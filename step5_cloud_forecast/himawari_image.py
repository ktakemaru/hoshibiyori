"""星の日和(hoshibiyori) 気象衛星ひまわり画像(日本域タイル)の取得とモザイク化。

「現況の雲の様子(参考)」として、レポートの直近セクションに広域の赤外画像を1枚表示するための
モジュール。数値予報(Open-Meteo)とは独立した**実況**であり、スコア・足切りには一切使わない。
赤外画像は夜間も使えるが、低層雲・霧は地面との温度差が小さく見分けにくい(表示側で注記する)。

移植元(2026-10-12、ユーザー承認済みの読み取り専用参照): 姉妹プロジェクトyamabiyoriの
mountain_weather_core.py のひまわりの節(himawari_latest_basetime / latlon_to_tile_xy /
fetch_himawari_tile / fetch_himawari_image / HIMAWARI_IMG_TYPES、origin/main 9a7567d 時点)。
そこから把握した仕様は次の3点のみで、コードはhoshibiyoriの流儀で書き直している:
  - 画像種別は ir→B13/TBB、strengthen→SND/ETC の2つだけが実通信で確認済み(他は追加しない)。
  - 日本域("jp")タイルはz=6固定、1タイル256pxで約5.6度四方。
  - 最新時刻は targetTimes_jp.json の basetime の最大値。
yamabiyoriとの違い: ①地点ごとの3x3ではなく、候補エリア全体を覆う広域1枚(areas.json基準)
②タイル単位のディスクキャッシュ(himawari_cache/) ③HTTP失敗の扱いはstep5の
cloud_forecast.pyと同じ方針(429は即中止、429以外の4xxはリトライしない、408/5xx/接続エラーは
リトライ) ④観測地点の十字マークは付けない(広域の雲の様子であり、地点ピンポイントではない)。

利用規約: 気象庁ホームページの利用規約に基づき出典表示が必須(ATTRIBUTION)。気象業務法により、
これを元にした独自の予報・警報の公表はしない。節度あるアクセスとして、1回の実行につき
targetTimes取得1回+モザイクのタイル数(2x2なら4枚)だけを取得し、同一basetimeのタイルは
ディスクキャッシュから再利用する(ループ処理はしない)。

basetimeのタイムゾーン: **UTC**(2026-10-12のスモークテストで確定)。targetTimes_jp.json の
最新basetime 20261012004000 を、取得時刻(2026-10-12 00:47 UTC = 09:47 JST、サーバーの
Dateヘッダーとも一致)と比べると、UTCとして読めば7.2分前、JSTとして読めば547分前(約9時間前)
となり、UTCだけが「数分前の最新画像」として成立する。yamabiyori側のdocstringは
JSTと記載しているが、実測はUTCだった(yamabiyoriは変更していない)。
"""
from __future__ import annotations

import io
import math
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

JST = timezone(timedelta(hours=9))
# basetimeを解釈するタイムゾーン。UTCで確定(2026-10-12のスモークテストで実測。モジュールdocstring参照)。
BASETIME_TZ = timezone.utc

BASE_URL = "https://www.jma.go.jp/bosai/himawari/data/satimg"
AREA = "jp"
ZOOM = 6  # 日本域は固定(JMAのタイルレイヤー設定でminZoom=maxZoom=6)
TILE_PX = 256
ATTRIBUTION = "出典：気象庁ホームページ (https://www.jma.go.jp/bosai/map.html)"

# 公開名 → タイルURL中の実パス。実通信で確認済みの2種のみ(他の種別は実URLを確認するまで追加しない)。
IMG_TYPES = {
    "ir": "B13/TBB",          # 赤外画像(夜間も使える)
    "strengthen": "SND/ETC",  # 雲頂強調画像
}

DEFAULT_CACHE_DIR = Path(__file__).parent / "himawari_cache"

_USER_AGENT = "hoshibiyori-himawari/0.1 (personal astrophotography tool; low-volume, tile-cached)"
_MAX_RETRIES = 3
_RETRY_BACKOFF_SEC = 2.0
_GRAY = (32, 32, 32)


class HimawariFetchError(RuntimeError):
    """ひまわりタイル/時刻一覧の取得失敗。status にHTTPステータス(接続エラー等はNone)。"""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class HimawariRateLimitError(HimawariFetchError):
    """HTTP 429。これ以降の取得は中止する。"""


@dataclass
class HimawariImage:
    path: Path
    basetime: str            # "YYYYMMDDHHMMSS"(JMAのパス中の表記のまま)
    basetime_jst: datetime   # 表示用(BASETIME_TZ として解釈してJSTに直したもの)
    imgtype: str
    span: int
    x0: int
    y0: int
    tiles_ok: int
    tiles_total: int
    attribution: str = ATTRIBUTION


# --- タイル座標(標準のWebメルカトル。Leaflet/OSM/JMAの地図と同じスキーム) -----------------

def tile_float(lat: float, lon: float, zoom: int = ZOOM) -> tuple[float, float]:
    """(lat, lon)のタイル座標(小数)。整数部がタイル番号、小数部がタイル内位置。"""
    n = 2 ** zoom
    lat_rad = math.radians(lat)
    fx = (lon + 180.0) / 360.0 * n
    fy = (1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * n
    return fx, fy


def latlon_to_tile_xy(lat: float, lon: float, zoom: int = ZOOM) -> tuple[int, int]:
    fx, fy = tile_float(lat, lon, zoom)
    return int(math.floor(fx)), int(math.floor(fy))


def window_origin(center_lat: float, center_lon: float, span: int) -> tuple[int, int]:
    """span x spanタイルの窓の左上タイル(x0, y0)。中心に最も近い位置に置く。
    奇数spanは中心を含むタイルが窓の中央、偶数spanは中心に最も近いタイル角が窓の中央になる。"""
    fx, fy = tile_float(center_lat, center_lon)
    if span % 2:
        return int(math.floor(fx)) - span // 2, int(math.floor(fy)) - span // 2
    return int(math.floor(fx + 0.5)) - span // 2, int(math.floor(fy + 0.5)) - span // 2


def window_covers(x0: int, y0: int, span: int,
                  lat_min: float, lat_max: float, lon_min: float, lon_max: float) -> bool:
    """窓(x0,y0,span)が緯度経度の矩形を完全に覆うか。"""
    fx_min, fy_top = tile_float(lat_max, lon_min)
    fx_max, fy_bottom = tile_float(lat_min, lon_max)
    return x0 <= fx_min and fx_max <= x0 + span and y0 <= fy_top and fy_bottom <= y0 + span


def regional_view(bboxes: list[tuple[float, float, float, float]],
                  candidate_spans: tuple[int, ...] = (2, 3)) -> tuple[float, float, int]:
    """矩形群(lat_min, lat_max, lon_min, lon_max)の全体を覆う最小の窓を決める。
    戻り値は(中心緯度, 中心経度, span)。candidate_spansの小さい順に、中心に置いた窓が
    全体を覆う最初のspanを採用し、どれも覆えなければ最大のspanを返す。"""
    lat_min = min(b[0] for b in bboxes)
    lat_max = max(b[1] for b in bboxes)
    lon_min = min(b[2] for b in bboxes)
    lon_max = max(b[3] for b in bboxes)
    center_lat, center_lon = (lat_min + lat_max) / 2, (lon_min + lon_max) / 2
    for span in sorted(candidate_spans):
        x0, y0 = window_origin(center_lat, center_lon, span)
        if window_covers(x0, y0, span, lat_min, lat_max, lon_min, lon_max):
            return center_lat, center_lon, span
    return center_lat, center_lon, max(candidate_spans)


def basetime_to_jst(basetime: str) -> datetime:
    return datetime.strptime(basetime, "%Y%m%d%H%M%S").replace(tzinfo=BASETIME_TZ).astimezone(JST)


# --- HTTP -----------------------------------------------------------------------------

def _http_get(url: str) -> requests.Response:
    """GET。429は即 HimawariRateLimitError、429以外の4xxは即 HimawariFetchError(リトライしない)。
    408・5xx・接続エラーは数回リトライする(cloud_forecast._fetch_hourly_detailed と同じ方針)。"""
    last: Exception | None = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            resp = requests.get(url, timeout=20, headers={"User-Agent": _USER_AGENT})
            status = resp.status_code
            if status == 429:
                raise HimawariRateLimitError(f"HTTP 429 (rate limit): {url}", status)
            if 400 <= status < 500 and status != 408:
                raise HimawariFetchError(f"HTTP {status}: {url}", status)
            resp.raise_for_status()
            return resp
        except HimawariFetchError:
            raise
        except requests.RequestException as e:
            last = e
            if attempt < _MAX_RETRIES:
                time.sleep(_RETRY_BACKOFF_SEC * attempt)
    raise HimawariFetchError(f"取得失敗({_MAX_RETRIES}回リトライ後): {url}: {last}")


def latest_basetime() -> str:
    """JMAが公開している最新のbasetime。1回の実行につき1回だけ呼び、結果を使い回すこと。"""
    resp = _http_get(f"{BASE_URL}/targetTimes_{AREA}.json")
    return max(t["basetime"] for t in resp.json())


def _tile_url(basetime: str, imgtype: str, x: int, y: int) -> str:
    return f"{BASE_URL}/{basetime}/{AREA}/{basetime}/{IMG_TYPES[imgtype]}/{ZOOM}/{x}/{y}.jpg"


def _tile_bytes(basetime: str, imgtype: str, x: int, y: int, cache_dir: Path) -> bytes:
    """タイルのJPEGバイト列。同一basetimeならディスクキャッシュを使う(basetimeが変われば別ファイル)。"""
    path = cache_dir / f"{basetime}_{imgtype}_{ZOOM}_{x}_{y}.jpg"
    if path.exists():
        return path.read_bytes()
    data = _http_get(_tile_url(basetime, imgtype, x, y)).content
    path.write_bytes(data)
    return data


# --- モザイク ---------------------------------------------------------------------------

def fetch_regional_image(center_lat: float, center_lon: float, imgtype: str = "ir", span: int = 2,
                         cache_dir: str | Path = DEFAULT_CACHE_DIR,
                         basetime: str | None = None) -> HimawariImage | None:
    """中心(center_lat, center_lon)を中心とする span x span タイルの広域画像を生成して返す。

    取得できなかったタイル(範囲外・一時的エラー)は灰色で埋めて続行する。1枚も取得できなかった
    場合は画像を保存せず None を返す。429を受けたら HimawariRateLimitError を送出して中止する。
    時刻一覧の取得失敗など、その他の HimawariFetchError も呼び出し側に伝わる(表示側で省略する)。
    Pillowは遅延importする。
    """
    if imgtype not in IMG_TYPES:
        raise ValueError(f"imgtype must be one of {list(IMG_TYPES)}, got {imgtype!r}")
    if span < 1:
        raise ValueError(f"span must be >= 1, got {span}")
    from PIL import Image

    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    basetime = basetime or latest_basetime()
    x0, y0 = window_origin(center_lat, center_lon, span)

    mosaic_path = cache_dir / f"mosaic_{imgtype}_{basetime}_{x0}_{y0}_{span}.jpg"
    mosaic = Image.new("RGB", (span * TILE_PX, span * TILE_PX), _GRAY)
    ok = 0
    for row in range(span):
        for col in range(span):
            try:
                tile = Image.open(io.BytesIO(_tile_bytes(basetime, imgtype, x0 + col, y0 + row, cache_dir)))
                mosaic.paste(tile.convert("RGB"), (col * TILE_PX, row * TILE_PX))
                ok += 1
            except HimawariRateLimitError:
                raise
            except (HimawariFetchError, OSError) as e:
                print(f"    [警告] ひまわりタイル取得失敗(x={x0 + col},y={y0 + row}): {e} -> 灰色で埋めます")
    if ok == 0:
        return None
    mosaic.save(mosaic_path, "JPEG", quality=90)
    return HimawariImage(
        path=mosaic_path, basetime=basetime, basetime_jst=basetime_to_jst(basetime), imgtype=imgtype,
        span=span, x0=x0, y0=y0, tiles_ok=ok, tiles_total=span * span,
    )
