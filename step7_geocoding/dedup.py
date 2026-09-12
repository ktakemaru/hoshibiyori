"""候補地点DB(candidate_sites.db)の重複検出・判断案の作成。

検出基準:
- 近接重複: 緯度経度の距離が既定200m以内の2件以上
- 同名重複: name正規化後の完全一致、または類似度(difflib)が閾値以上
  (全角半角統一・空白除去・「岬」「灯台」等の一般的な接尾辞を外した比較を含む)

削除は行わず、グループ化と「残す/削除する」の判断案の作成までを行う。
実際の削除は apply_dedup.py で別途、判断案を確認した後に実行する。
"""
from __future__ import annotations

import difflib
import math
import sqlite3
import unicodedata
from dataclasses import dataclass
from pathlib import Path

DB_PATH = Path(__file__).parent / "candidate_sites.db"

DISTANCE_THRESHOLD_M = 200.0
NAME_SIMILARITY_THRESHOLD = 0.8
# これ未満の距離なら、名前が全く違っても同一物理地点とみなして良いほど近いと判断する閾値。
# 例: 「いすみ鉄道踏切」(検証済みテスト地点の仮称)と「第二五之町踏切」(OSM上の正式名称)は
# 名前は無関係だが距離6mで、明らかに同じ踏切を指している。
VERY_CLOSE_THRESHOLD_M = 50.0

# 地名によく付く一般的な接尾辞(比較時に取り除いて表記ゆれを吸収する)
_COMMON_SUFFIXES = ["灯台", "展望台", "展望広場", "テラス", "見晴らし台", "見晴台", "岬"]

# 地形地平線プロファイル・光害の両方を検証済みのレコード(名前で判定)
VERIFIED_NAMES = {
    "富士山頂", "須走口五合目", "精進湖 他手合浜", "八ヶ岳南麓天文台",
    "石廊崎", "いすみ鉄道踏切", "阿智村 ヘブンスそのはら付近",
}


@dataclass
class Record:
    id: str
    source: str
    name: str
    lat: float
    lon: float
    municipality: str


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def normalize_name(name: str) -> str:
    """NFKC正規化(全角半角統一)・空白除去・一般的な接尾辞の除去を行う。"""
    n = unicodedata.normalize("NFKC", name).strip()
    n = n.replace(" ", "").replace("　", "")
    for suffix in _COMMON_SUFFIXES:
        if n.endswith(suffix) and len(n) > len(suffix):
            n = n[: -len(suffix)]
            break
    return n


def name_similarity(a: str, b: str) -> float:
    """参考表示用の類似度(0-1)。グループ化の判定には使わない(下記の理由を参照)。"""
    na, nb = normalize_name(a), normalize_name(b)
    if na == nb:
        return 1.0
    return difflib.SequenceMatcher(None, na, nb).ratio()


def _names_match(a: str, b: str) -> tuple[bool, str]:
    """名前の一致判定。厳密な基準のみを用いる。

    注意: difflib的な緩い類似度(比率)は使わない。761件規模だと「富士見台」
    「富士見峠台」「富士見展望台」のように、全く無関係な地点同士が部分文字列を
    共有するだけで類似度が閾値を超えてしまい、かつUnion-Findの推移性によって
    無関係な地点が芋づる式に1つの巨大グループへ誤って統合される事故が実際に
    発生した(検証時に確認済み)。そのため「完全一致」または「厳密な部分文字列
    包含」のみを同名判定の根拠とする。
    """
    na, nb = normalize_name(a), normalize_name(b)
    if na == nb:
        return True, "正規化後に完全一致"
    if len(na) >= 2 and len(nb) >= 2:
        if na in nb or nb in na:
            return True, "正規化後に一方がもう一方を完全に含む(部分文字列包含)"
    return False, ""


def is_verified(name: str) -> bool:
    return name in VERIFIED_NAMES


def load_records(conn: sqlite3.Connection) -> list[Record]:
    rows = conn.execute("SELECT id, source, name, lat, lon, municipality FROM candidate_sites").fetchall()
    return [Record(id=r[0], source=r[1], name=r[2] or "", lat=r[3], lon=r[4], municipality=r[5] or "") for r in rows]


class UnionFind:
    def __init__(self, items):
        self.parent = {i: i for i in items}

    def find(self, x):
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


def find_proximity_only_pairs(records: list[Record], distance_threshold_m: float = DISTANCE_THRESHOLD_M) -> list[tuple[Record, Record, float]]:
    """名前に関連が無いが distance_threshold_m 以内にある地点のペアを報告する(情報提供のみ)。

    推移的なグループ化はしない(単純にペア単位で報告する)。理由: 公園・展望施設のように
    小さなエリアに多数の異なる見どころが密集していると、Union-Findで推移的にまとめた
    場合に無関係な地点が数珠つなぎに1つの巨大グループへ誤統合されるリスクがあるため、
    ここでは安全側に倒してペア単位の報告に留める(削除は一切推奨しない)。
    """
    pairs = []
    n = len(records)
    for i in range(n):
        for j in range(i + 1, n):
            r1, r2 = records[i], records[j]
            dist = haversine_m(r1.lat, r1.lon, r2.lat, r2.lon)
            if dist > distance_threshold_m or dist <= VERY_CLOSE_THRESHOLD_M:
                continue  # 50m以下はfind_name_related_duplicate_groups側(名前問わず統合)で扱う
            name_match, _ = _names_match(r1.name, r2.name)
            if name_match:
                continue  # 名前関連があるものはfind_name_related_duplicate_groups側で扱う
            pairs.append((r1, r2, dist))
    return pairs


def find_name_related_duplicate_groups(
    records: list[Record],
    distance_threshold_m: float = DISTANCE_THRESHOLD_M,
    name_sim_threshold: float = NAME_SIMILARITY_THRESHOLD,
) -> list[list[Record]]:
    """名前の関連(完全一致または部分文字列包含)がある地点をグループ化する(推移的にまとめる)。

    削除を推奨する主対象。名前の関連を必須条件とすることで、単に近接しているだけの
    別地点(公園内の複数の見どころ等)を誤って統合しないようにしている。
    """
    uf = UnionFind([r.id for r in records])

    # 判定基準: 名前の関連(完全一致または部分文字列包含)を必須条件とし、そのうえで
    #   (2) 完全一致 かつ 距離 <= 300m、または (3) 包含関係 かつ 距離 <= 1000m
    #   の場合のみ重複候補として統合する。
    #
    # 注意: 当初は「距離が近ければ名前を問わず統合」というルールも入れていたが、
    # 実際に検証したところ、公園・展望施設内にある名前の異なる複数の見どころ
    # (例: 「黒船展望台」と「寝姿展望台」が116m以内)まで大量に「重複候補」として
    # 拾ってしまい、69グループ中45グループが実際には別地点だった。また完全一致の
    # 許容距離を5000mにしていた際は、「つつじ」「桜」「臘梅」のような花の種類を表す
    # 汎用的な名前が同じ公園内の複数の異なる観賞ポイントで使い回されており、
    # Union-Findの推移性も相まって25件もの無関係な地点が1グループに誤統合される
    # 事故も発生した。そのため名前の関連性を必須とし、距離も実際の真の重複事例
    # (石廊崎116m・妙音沢80m・華厳の滝51m等)に基づいて絞り込んでいる。
    n = len(records)
    for i in range(n):
        for j in range(i + 1, n):
            r1, r2 = records[i], records[j]
            dist = haversine_m(r1.lat, r1.lon, r2.lat, r2.lon)

            if dist <= VERY_CLOSE_THRESHOLD_M:
                uf.union(r1.id, r2.id)  # 名前を問わず、物理的に同一地点とみなせるほど近い
                continue

            name_match, _ = _names_match(r1.name, r2.name)
            if not name_match:
                continue

            same_name_nearby = normalize_name(r1.name) == normalize_name(r2.name) and dist <= 300.0
            contained_nearby = dist <= 1000.0

            if same_name_nearby or contained_nearby:
                uf.union(r1.id, r2.id)

    groups: dict[str, list[Record]] = {}
    by_id = {r.id: r for r in records}
    for r in records:
        root = uf.find(r.id)
        groups.setdefault(root, []).append(r)

    return [g for g in groups.values() if len(g) > 1]


def recommend_keep(group: list[Record]) -> tuple[Record, list[Record], str]:
    """グループ内でどれを残すかの判断案を返す: (残す候補, 削除候補群, 理由)。"""
    verified = [r for r in group if is_verified(r.name)]
    if verified:
        keep = verified[0]
        reason = "地形地平線・光害を検証済みのレコードのため優先"
    else:
        # 情報量(名前の長さ)がより具体的なものを優先(簡易ヒューリスティック)
        keep = max(group, key=lambda r: len(normalize_name(r.name)))
        reason = "検証済みレコードが無いため、より具体的な名称のレコードを優先(簡易判定、要目視確認)"

    remove = [r for r in group if r.id != keep.id]
    return keep, remove, reason


def check_new_candidate(
    name: str, lat: float, lon: float, conn: sqlite3.Connection,
    distance_threshold_m: float = DISTANCE_THRESHOLD_M,
    name_sim_threshold: float = NAME_SIMILARITY_THRESHOLD,
) -> list[dict]:
    """新規地点を登録する前に、既存DBとの近接・同名重複が無いか確認する(登録用の簡易関数)。

    戻り値: 重複の疑いがある既存レコードのリスト(空なら重複無し)。
    """
    records = load_records(conn)
    hits = []
    for r in records:
        dist = haversine_m(lat, lon, r.lat, r.lon)
        sim = name_similarity(name, r.name)
        if dist <= distance_threshold_m or sim >= name_sim_threshold:
            hits.append({"id": r.id, "name": r.name, "distance_m": round(dist, 1), "name_similarity": round(sim, 2)})
    return hits


def _group_has_name_relation(group: list[Record]) -> bool:
    for i in range(len(group)):
        for j in range(i + 1, len(group)):
            matched, _ = _names_match(group[i].name, group[j].name)
            if matched:
                return True
    return False


def main() -> None:
    conn = sqlite3.connect(DB_PATH)
    records = load_records(conn)
    print(f"総レコード数: {len(records)}")

    name_related_groups = find_name_related_duplicate_groups(records)
    proximity_pairs = find_proximity_only_pairs(records)

    verified_group_count = sum(1 for g in name_related_groups if any(is_verified(r.name) for r in g))

    print(f"【削除推奨】名前的関連(完全一致/包含)がある重複グループ: {len(name_related_groups)}件"
          f"(うち検証済み8地点が絡むもの: {verified_group_count}件)")
    print(f"【参考情報のみ】名前は無関係だが200m以内に近接しているペア: {len(proximity_pairs)}件"
          f"(削除は推奨しません。公園・展望施設内の別々の見どころである可能性が高いため)\n")

    print("=" * 70)
    print("【削除推奨】名前的関連があるグループ(同一地点の重複である可能性が高い)")
    print("=" * 70)
    for i, group in enumerate(name_related_groups, 1):
        keep, remove, reason = recommend_keep(group)
        caution = " ※要目視確認(生成的/汎用的な名称・件数が多い)" if len(group) > 3 else ""
        print(f"\n--- グループ{i} ({len(group)}件){caution} ---")
        for r in group:
            verified_note = "[検証済み8地点由来]" if is_verified(r.name) else "[viewpoint由来]"
            mark = "残す候補" if r.id == keep.id else "削除候補"
            print(f"  [{mark}] {verified_note} id={r.id}  name={r.name!r}  "
                  f"({r.lat:.5f},{r.lon:.5f})  {r.municipality}")
        if len(group) == 2:
            d = haversine_m(group[0].lat, group[0].lon, group[1].lat, group[1].lon)
            print(f"  距離: {d:.0f}m")
        print(f"  判断理由: {reason}")

    print(f"\n{'='*70}")
    print(f"【削除非推奨・参考情報のみ】名前が無関係で単に近接(200m以内)しているペア: "
          f"{len(proximity_pairs)}件")
    print("(公園・展望施設内の複数の異なる見どころ等、別地点である可能性が高いため一覧のみ表示し、削除は提案しません)")
    print("=" * 70)
    for i, (r1, r2, dist) in enumerate(proximity_pairs, 1):
        print(f"  {i}. {r1.name!r} <-> {r2.name!r}  ({r1.municipality}, {dist:.0f}m)")

    conn.close()


if __name__ == "__main__":
    main()
