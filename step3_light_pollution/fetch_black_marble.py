"""NASA Black Marble 年次コンポジット(VNP46A4 / VJ146A4)の取得(段階LP1)。

粒度(タイル)の一覧は認証不要のNASA CMRで引き、実ファイルはLAADSから
`Authorization: Bearer $EARTHDATA_TOKEN` で取得する。トークンは環境変数から読むだけで、
ログ・出力・PROVENANCEには書かない。

節度: 逐次取得・取得済みファイルは再取得しない・識別可能なUser-Agent。HTTP 429は即中止。
生HDF5は git 管理外の `blackmarble_cache/` に置く(.gitignore済み)。

使い方:
    py -X utf8 step3_light_pollution/fetch_black_marble.py --product VNP46A4 --year 2025
    py -X utf8 step3_light_pollution/fetch_black_marble.py --list-only ...   # 一覧だけ(通信はCMRのみ)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import date
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
CACHE_DIR = HERE / "blackmarble_cache"
PROVENANCE_PATH = HERE / "data" / "PROVENANCE.json"

CMR_COLLECTIONS = "https://cmr.earthdata.nasa.gov/search/collections.json"
CMR_GRANULES = "https://cmr.earthdata.nasa.gov/search/granules.json"
USER_AGENT = "hoshibiyori-lp1/0.1 (personal astrophotography tool; low-volume, cached)"
POLITE_DELAY_SEC = 2.0
TIMEOUT_SEC = 120


class DownloadAborted(RuntimeError):
    pass


def _session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    return s


def find_collection(session: requests.Session, short_name: str) -> dict:
    r = session.get(CMR_COLLECTIONS, params={"short_name": short_name}, timeout=30)
    r.raise_for_status()
    entries = r.json()["feed"]["entry"]
    if not entries:
        raise RuntimeError(f"CMRに{short_name}が見つからない")
    # バージョンが複数あれば最新(数値が大きいもの)
    return max(entries, key=lambda e: e["version_id"])


def list_granules(session: requests.Session, collection_id: str, year: int,
                  bbox: tuple[float, float, float, float]) -> list[dict]:
    """bbox=(西, 南, 東, 北)。年次コンポジットは time_start がその年の1/1。"""
    params = {
        "collection_concept_id": collection_id,
        "temporal": f"{year}-01-01T00:00:00Z,{year}-12-31T23:59:59Z",
        "bounding_box": ",".join(f"{v}" for v in bbox),
        "page_size": 100,
    }
    r = session.get(CMR_GRANULES, params=params, timeout=30)
    r.raise_for_status()
    out = []
    for e in r.json()["feed"]["entry"]:
        if not e["time_start"].startswith(f"{year}-01-01"):
            continue  # temporal指定は前年の粒度も拾うことがあるので年で絞る
        url = next((l["href"] for l in e["links"] if l["href"].endswith(".h5")), None)
        if url:
            out.append({"title": e["title"], "url": url, "name": url.rsplit("/", 1)[-1]})
    return sorted(out, key=lambda g: g["name"])


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(session: requests.Session, url: str, dest: Path, token: str) -> bool:
    """取得済みなら何もしない(Trueを返すのは実際に取得したとき)。"""
    if dest.exists() and dest.stat().st_size > 0:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with session.get(url, headers={"Authorization": f"Bearer {token}"}, stream=True,
                     timeout=TIMEOUT_SEC) as r:
        if r.status_code == 429:
            raise DownloadAborted("HTTP 429(利用上限)。即中止する")
        if r.status_code in (401, 403):
            raise DownloadAborted(f"HTTP {r.status_code}(認証エラー)。トークンの有効期限・権限を確認")
        r.raise_for_status()
        ctype = r.headers.get("Content-Type", "")
        if "html" in ctype:
            raise DownloadAborted("HDF5ではなくHTMLが返った(ログイン画面へのリダイレクトの可能性)")
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    tmp.replace(dest)
    return True


def update_provenance(entry: dict) -> None:
    PROVENANCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = {"schema": "hoshibiyori-blackmarble-provenance/1", "inputs": []}
    if PROVENANCE_PATH.exists():
        data = json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))
    key = (entry["product"], entry["year"], entry["tile_file"])
    data["inputs"] = [e for e in data["inputs"]
                      if (e["product"], e["year"], e["tile_file"]) != key] + [entry]
    data["inputs"].sort(key=lambda e: (e["product"], e["year"], e["tile_file"]))
    PROVENANCE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--product", default="VNP46A4")
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--bbox", type=float, nargs=4, metavar=("W", "S", "E", "N"),
                    help="省略時は skyglow_bm.input_extent() から算出")
    ap.add_argument("--list-only", action="store_true")
    args = ap.parse_args()

    if args.bbox:
        bbox = tuple(args.bbox)
    else:
        sys.path.insert(0, str(HERE))
        import skyglow_bm
        e = skyglow_bm.input_extent()
        bbox = (e["lon_min"], e["lat_min"], e["lon_max"], e["lat_max"])
    s = _session()
    coll = find_collection(s, args.product)
    granules = list_granules(s, coll["id"], args.year, bbox)
    print(f"{args.product} collection={coll['id']} version={coll['version_id']} 年={args.year} 粒度={len(granules)}")
    for g in granules:
        print("  ", g["name"])
    if args.list_only or not granules:
        return 0

    token = os.environ.get("EARTHDATA_TOKEN", "")
    if not token:
        print("EARTHDATA_TOKEN が未設定。取得工程は未実施。", file=sys.stderr)
        return 3
    for g in granules:
        dest = CACHE_DIR / args.product / str(args.year) / g["name"]
        try:
            fetched = download(s, g["url"], dest, token)
        except DownloadAborted as e:
            print(f"中止: {e}", file=sys.stderr)
            return 2
        print(("取得 " if fetched else "既存 ") + g["name"], f"{dest.stat().st_size/1e6:.1f}MB")
        update_provenance({
            "product": args.product,
            "collection_concept_id": coll["id"],
            "version": coll["version_id"],
            "year": args.year,
            "tile_file": g["name"],
            "source_url": g["url"],
            "sha256": sha256_of(dest),
            "size_bytes": dest.stat().st_size,
            "retrieved": date.today().isoformat(),
        })
        if fetched:
            time.sleep(POLITE_DELAY_SEC)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
