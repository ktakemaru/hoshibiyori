"""星の日和(hoshibiyori) ステップ7: Nominatimによる逆ジオコーディング(座標→市区町村)
および順ジオコーディング(地名→座標)。

Nominatim利用規約(https://operations.osmfoundation.org/policies/nominatim/)の要点:
- 識別可能なUser-Agent(またはRefererヘッダー)を送信すること
- 1秒あたり1リクエスト以下に抑えること(バルク利用は非推奨)
- 結果をキャッシュし、同じ問い合わせを繰り返さないこと

本モジュールはこれらを踏まえ、
- リクエスト間隔を明示的に1.1秒(既定)確保するレートリミッタを内蔵し(逆/順ジオコーディングで共有)、
- 結果は一度だけ取得してSQLite/JSONに永続化し(build_candidate_db.py, forward_geocode_curated.py)、
  以後は再問い合わせしない設計とする。
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import requests

NOMINATIM_REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"
NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"
# 個人の非商用検証プロジェクトであることが分かる識別情報を含める(規約要件)。
# 第三者サービスへの送信のため、個人の連絡先(メールアドレス等)は含めない。
USER_AGENT = "hoshibiyori-research/0.1 (personal, non-commercial astrophotography site-recommendation project)"
MIN_REQUEST_INTERVAL_SEC = 1.1

# 日本の行政区分に対応する優先順位(市 > 町 > 村 > その他)
_MUNICIPALITY_KEYS = ["city", "town", "village", "municipality", "suburb", "county"]

_last_request_time: float = 0.0


@dataclass
class GeocodeResult:
    municipality: str | None
    raw_address: dict | None
    error: str | None


def _wait_for_rate_limit() -> None:
    global _last_request_time
    elapsed = time.monotonic() - _last_request_time
    if elapsed < MIN_REQUEST_INTERVAL_SEC:
        time.sleep(MIN_REQUEST_INTERVAL_SEC - elapsed)
    _last_request_time = time.monotonic()


def reverse_geocode_municipality(lat: float, lon: float, timeout: float = 15.0) -> GeocodeResult:
    """指定した緯度経度の市区町村名を取得する。呼び出しごとにレート制限(既定1.1秒)を守る。"""
    _wait_for_rate_limit()
    try:
        resp = requests.get(
            NOMINATIM_REVERSE_URL,
            params={"format": "jsonv2", "lat": lat, "lon": lon, "accept-language": "ja"},
            headers={"User-Agent": USER_AGENT},
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        return GeocodeResult(municipality=None, raw_address=None, error=f"リクエスト失敗: {e}")

    if "error" in data:
        return GeocodeResult(municipality=None, raw_address=None, error=f"Nominatimエラー: {data['error']}")

    address = data.get("address", {})
    municipality = None
    for key in _MUNICIPALITY_KEYS:
        if key in address:
            municipality = address[key]
            break

    if municipality is None:
        return GeocodeResult(municipality=None, raw_address=address, error="住所情報に市区町村レベルのキーが無い")

    return GeocodeResult(municipality=municipality, raw_address=address, error=None)


@dataclass
class SearchResult:
    lat: float | None
    lon: float | None
    display_name: str | None
    raw_address: dict | None
    error: str | None


def search_place(query: str, timeout: float = 15.0) -> SearchResult:
    """地名クエリから緯度経度を検索する(順ジオコーディング)。呼び出しごとにレート制限(既定1.1秒)を守る。

    日本国内(countrycodes=jp)の最上位1件のみを返す。曖昧な地名は誤った場所にマッチしうるため、
    呼び出し側でdisplay_name/raw_addressを見て確からしさを検証すること。
    """
    _wait_for_rate_limit()
    try:
        resp = requests.get(
            NOMINATIM_SEARCH_URL,
            params={
                "q": query,
                "format": "jsonv2",
                "addressdetails": 1,
                "limit": 1,
                "countrycodes": "jp",
                "accept-language": "ja",
            },
            headers={"User-Agent": USER_AGENT},
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        return SearchResult(lat=None, lon=None, display_name=None, raw_address=None, error=f"リクエスト失敗: {e}")

    if not data:
        return SearchResult(lat=None, lon=None, display_name=None, raw_address=None, error="該当なし")

    top = data[0]
    return SearchResult(
        lat=float(top["lat"]),
        lon=float(top["lon"]),
        display_name=top.get("display_name"),
        raw_address=top.get("address"),
        error=None,
    )
