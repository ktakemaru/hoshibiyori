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
import sys
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

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.append(str(_ROOT))  # リポジトリ直下の hb_paths を見つけるため
from hb_paths import DATA_ROOT  # noqa: E402

DEFAULT_CACHE_DIR = DATA_ROOT / "step5_cloud_forecast" / "himawari_cache"

_USER_AGENT = "hoshibiyori-himawari/1.0.0 (personal astrophotography tool; low-volume, tile-cached)"
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


def recent_basetimes(offsets_min: tuple[int, ...] = (0, 60, 120)) -> list[str]:
    """最新のbasetimeと、そこから offsets_min 分前に最も近い(かつそれ以前の)basetimeを、古い順に返す。

    targetTimes_jp.json を1回だけ取得する。offset 0 が最新。一覧に該当が無いoffsetは省き(得られた分だけ返す)、
    同じbasetimeに当たったものは1つにまとめる。
    """
    resp = _http_get(f"{BASE_URL}/targetTimes_{AREA}.json")
    times = sorted({t["basetime"] for t in resp.json()})
    if not times:
        return []
    latest = datetime.strptime(times[-1], "%Y%m%d%H%M%S")
    picked: set[str] = set()
    for off in offsets_min:
        target = latest - timedelta(minutes=off)
        cands = [t for t in times if datetime.strptime(t, "%Y%m%d%H%M%S") <= target]
        if cands:
            picked.add(cands[-1])
    return sorted(picked)


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


# --- 「高い雲の割合」(参考表示用の純関数。通信しない。スコア・足切りには使わない) -----------

# 赤外画像(B13/TBB)は雲頂が高い(冷たい)ほど白く映る。グレースケールの明るさ(0〜255)がこの値以上の
# 画素を「雲域(赤外で明るく写る範囲)」の目安とみなす。**昼間の実画像に基づく暫定値。夜は冷えた地面が
# 明るく写る恐れがあり、夜のコマで要確認**(2026-10-12 01:50 UTCのモザイクで中央値47・90%点84・95%点113、
# 目で見える雲の筋は80〜150。初期値170ではほぼ拾えず、100を経て、2026-10-17の昼間3コマの目視確認で80にした)。
# 季節・時刻・地面の温度で意味が変わりうる。気象庁の公式の雲量ではない。
HIGH_CLOUD_BRIGHTNESS_THRESHOLD = 80

# タイルに含まれる純白(255)の塗りつぶし長方形(雲ではない)を除外する条件。面積と、外接矩形の充填率。
FILL_MIN_AREA_PX = 2000
FILL_MIN_RECT_FILL = 0.95


def bbox_to_px(lat_min: float, lat_max: float, lon_min: float, lon_max: float,
               x0: int, y0: int, span: int) -> tuple[int, int, int, int] | None:
    """緯度経度の矩形を、モザイク(左上タイル(x0,y0)、span x spanタイル)上のピクセル矩形
    (left, top, right, bottom。rightとbottomは含まない)に直す。窓外にはみ出す分は切る。
    窓と重ならない(面積が0になる)ときは None。"""
    fx_min, fy_top = tile_float(lat_max, lon_min)
    fx_max, fy_bottom = tile_float(lat_min, lon_max)
    size = span * TILE_PX
    left = max(0, math.floor((fx_min - x0) * TILE_PX))
    top = max(0, math.floor((fy_top - y0) * TILE_PX))
    right = min(size, math.ceil((fx_max - x0) * TILE_PX))
    bottom = min(size, math.ceil((fy_bottom - y0) * TILE_PX))
    if right <= left or bottom <= top:
        return None
    return left, top, right, bottom


def _solid_fill_mask(gray) -> bytearray:
    """純白(255)の連結成分(4近傍)のうち、面積がFILL_MIN_AREA_PX以上で外接矩形の充填率が
    FILL_MIN_RECT_FILL以上のものを「塗りつぶし」とみなし、その画素を1にした画像と同じ大きさのマスクを返す。
    通常の雲(不定形で充填率が低い)や小さな白い塊は対象外。"""
    w, h = gray.size
    data = gray.tobytes()
    mask = bytearray(w * h)
    seen = bytearray(w * h)
    for start in range(w * h):
        if data[start] != 255 or seen[start]:
            continue
        seen[start] = 1
        stack, comp = [start], []
        while stack:
            i = stack.pop()
            comp.append(i)
            x, y = i % w, i // w
            for j, ok in ((i - 1, x > 0), (i + 1, x < w - 1), (i - w, y > 0), (i + w, y < h - 1)):
                if ok and data[j] == 255 and not seen[j]:
                    seen[j] = 1
                    stack.append(j)
        if len(comp) < FILL_MIN_AREA_PX:
            continue
        xs = [i % w for i in comp]
        ys = [i // w for i in comp]
        rect = (max(xs) - min(xs) + 1) * (max(ys) - min(ys) + 1)
        if len(comp) / rect >= FILL_MIN_RECT_FILL:
            for i in comp:
                mask[i] = 1
    return mask


def high_cloud_fraction(image_path_or_pil, bbox_px: tuple[int, int, int, int],
                        threshold: int = HIGH_CLOUD_BRIGHTNESS_THRESHOLD) -> float | None:
    """画像の bbox_px(left, top, right, bottom)内で、グレースケールの明るさが threshold 以上の画素の割合(0〜1)。
    threshold ちょうどの画素は雲域に数える。bboxが画像の外にはみ出す分は切り、画像と重ならなければ ValueError。
    純白の塗りつぶし長方形(_solid_fill_mask)は雲ではないため、分母・分子の両方から除く。
    除外後に画素が残らないときは None。"""
    from PIL import Image

    if isinstance(image_path_or_pil, (str, Path)):
        with Image.open(image_path_or_pil) as im:
            gray = im.convert("L")
    else:
        gray = image_path_or_pil.convert("L")
    left, top, right, bottom = bbox_px
    left, top = max(0, left), max(0, top)
    right, bottom = min(gray.width, right), min(gray.height, bottom)
    if right <= left or bottom <= top:
        raise ValueError(f"bbox {bbox_px} が画像(幅{gray.width},高さ{gray.height})と重なりません")
    fill = _solid_fill_mask(gray)
    data = gray.tobytes()
    thr = max(0, int(math.ceil(threshold)))
    total = bright = 0
    for y in range(top, bottom):
        base = y * gray.width
        for i in range(base + left, base + right):
            if fill[i]:
                continue
            total += 1
            if data[i] >= thr:
                bright += 1
    return bright / total if total else None


def draw_outline(image_path: Path, bbox_px: tuple[int, int, int, int], out_path: Path) -> Path:
    """画像に矩形の細い外枠を重ね書きして out_path に保存する(元の画像ファイルは変えない)。"""
    from PIL import Image, ImageDraw

    with Image.open(image_path) as im:
        canvas = im.convert("RGB")
    left, top, right, bottom = bbox_px
    ImageDraw.Draw(canvas).rectangle((left, top, right - 1, bottom - 1), outline=(255, 214, 0), width=1)
    canvas.save(out_path, "PNG")
    return out_path
