"""星の日和(hoshibiyori) ステップ7拡張: curated_spots_source.json(Web調査で得た
関東甲信越・中部地方の星空撮影名所の名称リスト)をNominatimで順ジオコーディングし、
緯度経度を付与したcurated_spots_geocoded.jsonを構築する。

areas.json(bboxベースの広域エリア)やcandidate_sites.db(OSM viewpoint由来の候補地)
とは独立したファイルとして出力する。既存データへの書き込みは一切行わない。

一度実行して結果を永続化する設計。既に出力ファイルに存在するidはスキップするため、
中断しても再実行で続きから処理できる(build_candidate_db.pyと同じ方針)。

地名だけでは同名の別施設にマッチしたり該当なしになったりしうるため、
Nominatim側の都道府県(state)が期待値と一致するかを機械的に検証し、
一致しない/該当なしの場所は location_confirmed=false としてフラグを立てる。
このデータをareas.jsonや候補地DBに組み込む前に、location_confirmed=falseの項目は
人手で確認すること。
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from reverse_geocode import MIN_REQUEST_INTERVAL_SEC, search_place

SOURCE_PATH = Path(__file__).parent / "curated_spots_source.json"
OUTPUT_PATH = Path(__file__).parent / "curated_spots_geocoded.json"

# 標準の簡略化ロジック(接尾語除去・先頭区切りのみ)では見つからなかったidに対する
# 手動調査済みの追加クエリ候補。id -> クエリ文字列のリスト(優先順)。
# 通常のクエリ全てが失敗した場合にのみ、これらを追加で試す。
MANUAL_QUERY_OVERRIDES: dict[str, list[str]] = {
    "curated:003": ["さくら宇宙公園, 高萩市, 茨城県, Japan"],
    "curated:004": ["高戸小浜海水浴場, 北茨城市, 茨城県, Japan"],
    "curated:010": ["星野, 那珂川町, 栃木県, Japan"],
    "curated:012": ["くらぶちこども天文台, 高崎市, 群馬県, Japan"],
    "curated:013": ["大沼, 前橋市, 群馬県, Japan"],
    "curated:015": ["群馬県立ぐんま天文台, 高山村, 群馬県, Japan"],
    "curated:020": ["栃本, 秩父市, 埼玉県, Japan"],
    "curated:025": ["釣ヶ崎海岸, 一宮町, 千葉県, Japan"],
    "curated:028": ["小河内ダム, 奥多摩町, 東京都, Japan"],
    "curated:033": ["伊ケ谷灯台, 三宅村, 東京都, Japan"],
    "curated:042": ["パノラマ台, 山中湖村, 山梨県, Japan"],
    "curated:045": ["乙女高原, 山梨市牧丘町, 山梨県, Japan"],
    "curated:050": ["平沢峠, 南牧村, 長野県, Japan"],
    "curated:057": ["高峰高原, 小諸市, 長野県, Japan"],
    "curated:059": ["妙高サンシャインランド, 妙高市, 新潟県, Japan"],
    "curated:060": ["光ケ原高原, 上越市, 新潟県, Japan"],
    "curated:064": ["ドンデン山, 佐渡市, 新潟県, Japan"],
    "curated:066": ["室堂, 立山町, 富山県, Japan"],
    "curated:067": ["弥陀ヶ原, 立山町, 富山県, Japan"],
    "curated:070": ["相倉, 南砺市, 富山県, Japan"],
    "curated:072": ["満天星, 能登町, 石川県, Japan"],
    "curated:076": ["キゴ山, 金沢市, 石川県, Japan"],
    "curated:079": ["さかだにスキー場, 大野市, 福井県, Japan"],
    "curated:081": ["道の駅池田, 池田町, 福井県, Japan"],
    "curated:085": ["大平大橋, 下呂市, 岐阜県, Japan"],
    "curated:091": ["天城高原ゴルフコース, 伊豆市, 静岡県, Japan"],
    "curated:096": ["茶臼山, 豊根村, 愛知県, Japan"],
    "curated:099": ["面ノ木峠, 豊田市, 愛知県, Japan"],
}

# 都道府県名の末尾表記ゆれ("県""都""道""府")を取り除いて比較するための正規化
_PREF_SUFFIX_RE = re.compile(r"(都|道|府|県)$")

# municipality内の補足説明(括弧書き)はクエリを曖昧にするため検索時のみ取り除く
_PAREN_RE = re.compile(r"[\(（][^\)）]*[\)）]")


def _normalize_pref(pref: str) -> str:
    return _PREF_SUFFIX_RE.sub("", pref)


def _clean_municipality(municipality: str) -> str:
    # "秩父市・小鹿野町" のような複数併記は先頭のみ使う(検索クエリの曖昧さを避けるため)
    municipality = _PAREN_RE.sub("", municipality)
    for sep in ("・", "〜", "、"):
        if sep in municipality:
            municipality = municipality.split(sep)[0]
    return municipality.strip()


# 施設種別を表す一般的な接尾語。組み合わせ名(例:「戦場ヶ原・大間々台駐車場」)や
# あまり知られていない愛称(例:「三方五湖レインボーライン山頂公園」)はNominatimで
# ヒットしないことが多いため、簡略化した名前も候補として試す。
_GENERIC_SUFFIXES = [
    "駐車場", "パーキング", "第二駐車場", "展望台", "記念公園", "山頂公園",
    "ビーチタワー", "海水浴場", "海岸", "自然公園", "自然保護センター", "緑地公園",
]


def _simplify_name(name: str) -> str | None:
    """複合名/愛称から検索に強い簡略名を作る。単純化できなければNoneを返す。"""
    simplified = name
    for sep in ("・", "、", " "):
        if sep in simplified:
            simplified = simplified.split(sep)[0]
    for suffix in _GENERIC_SUFFIXES:
        if simplified.endswith(suffix) and len(simplified) > len(suffix):
            simplified = simplified[: -len(suffix)]
            break
    simplified = simplified.strip()
    if simplified and simplified != name:
        return simplified
    return None


def _prefecture_in_display_name(prefecture: str, display_name: str | None) -> bool:
    if not display_name:
        return False
    return _normalize_pref(prefecture) in display_name


def _load_source() -> list[dict]:
    with open(SOURCE_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return data["spots"]


def _load_existing() -> dict[str, dict]:
    if not OUTPUT_PATH.exists():
        return {}
    with open(OUTPUT_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return {item["id"]: item for item in data.get("spots", [])}


def _geocode_one(spot: dict) -> dict:
    name = spot["name"]
    prefecture = spot["prefecture"]
    municipality = _clean_municipality(spot["municipality"])
    simplified = _simplify_name(name)

    queries = [f"{name}, {municipality}, {prefecture}, Japan", f"{name}, {prefecture}, Japan"]
    if simplified:
        queries.append(f"{simplified}, {municipality}, {prefecture}, Japan")
        queries.append(f"{simplified}, {prefecture}, Japan")
    queries.extend(MANUAL_QUERY_OVERRIDES.get(spot["id"], []))

    result = None
    used_query = None
    confirmed = False
    for i, q in enumerate(queries):
        if i > 0:
            time.sleep(MIN_REQUEST_INTERVAL_SEC)  # フォールバック再検索の間も間隔を空ける
        result = search_place(q)
        used_query = q
        if result.error is None and _prefecture_in_display_name(prefecture, result.display_name):
            confirmed = True
            break
        # 該当なし、または都道府県不一致の場合は次のクエリ候補を試す

    out = dict(spot)
    out["query_used"] = used_query

    if result is None or result.error is not None:
        out["lat"] = None
        out["lon"] = None
        out["display_name"] = None
        out["location_confirmed"] = False
        out["geocode_error"] = result.error if result else "unknown"
        return out

    out["lat"] = result.lat
    out["lon"] = result.lon
    out["display_name"] = result.display_name
    out["geocode_error"] = None
    out["location_confirmed"] = confirmed
    return out


def main() -> None:
    spots = _load_source()
    existing = _load_existing()

    todo = [s for s in spots if s["id"] not in existing]
    print(f"総件数: {len(spots)}件 / 処理済み: {len(existing)}件 / 残り: {len(todo)}件")
    est_minutes = len(todo) * MIN_REQUEST_INTERVAL_SEC / 60
    print(f"推定所要時間: 約{est_minutes:.1f}分(フォールバック再検索が発生した場合はこれより長くなる)\n")

    results = list(existing.values())
    confirmed_count = sum(1 for r in results if r.get("location_confirmed"))
    unconfirmed_count = len(results) - confirmed_count

    for i, spot in enumerate(todo, 1):
        geocoded = _geocode_one(spot)
        results.append(geocoded)

        if geocoded["location_confirmed"]:
            confirmed_count += 1
        else:
            unconfirmed_count += 1

        # 1件ごとに永続化(中断しても続きから再開できるように)
        with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
            json.dump({"spots": results}, f, ensure_ascii=False, indent=2)

        status = "OK" if geocoded["location_confirmed"] else "要確認"
        print(f"  [{i}/{len(todo)}] {spot['name']} -> {status}")

    print(f"\n完了。確認OK {confirmed_count}件 / 要確認・失敗 {unconfirmed_count}件。")
    print(f"出力先: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
