"""候補地点(検証済み地点 + viewpoint)をNominatimで逆ジオコーディングし、
市区町村名付きの静的DB(SQLite)を構築する。

一度実行して結果を永続化する設計。既にDBに存在するidはスキップするため、
中断しても再実行で続きから処理できる。
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from reverse_geocode import MIN_REQUEST_INTERVAL_SEC, reverse_geocode_municipality

DB_PATH = Path(__file__).parent / "candidate_sites.db"
VIEWPOINTS_PATH = Path(__file__).parent.parent / "step6_viewpoint_survey" / "viewpoints_kanto.json"

TEST_SITES = [
    ("富士山頂", 35.3606, 138.7274),
    ("須走口五合目", 35.364942, 138.777077),
    ("精進湖 他手合浜", 35.490824, 138.605076),
    ("八ヶ岳南麓天文台", 35.882707, 138.36435),
    ("石廊崎", 34.602778, 138.845278),
    ("いすみ鉄道踏切", 35.282583, 140.297250),
    ("阿智村 ヘブンスそのはら付近", 35.456090, 137.633603),
]


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS candidate_sites (
            id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            name TEXT,
            lat REAL NOT NULL,
            lon REAL NOT NULL,
            ele TEXT,
            description TEXT,
            municipality TEXT,
            display_name TEXT,
            geocode_error TEXT
        )
    """)
    conn.commit()


def load_candidates() -> list[dict]:
    candidates = []
    for name, lat, lon in TEST_SITES:
        candidates.append({
            "id": f"test:{name}", "source": "test_site", "name": name,
            "lat": lat, "lon": lon, "ele": None, "description": None,
        })

    with open(VIEWPOINTS_PATH, encoding="utf-8") as f:
        viewpoints = json.load(f)
    for v in viewpoints:
        if not v.get("name"):
            continue
        candidates.append({
            "id": f"viewpoint:{v['id']}", "source": "viewpoint", "name": v["name"],
            "lat": v["lat"], "lon": v["lon"], "ele": v.get("ele"), "description": v.get("description"),
        })
    return candidates


def main() -> None:
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    candidates = load_candidates()
    already_done = {row[0] for row in conn.execute("SELECT id FROM candidate_sites")}
    todo = [c for c in candidates if c["id"] not in already_done]

    print(f"総候補数: {len(candidates)}件 / 処理済み: {len(already_done)}件 / 残り: {len(todo)}件")
    est_minutes = len(todo) * MIN_REQUEST_INTERVAL_SEC / 60
    print(f"推定所要時間: 約{est_minutes:.1f}分\n")

    success_count = 0
    error_count = 0
    start_time = time.time()

    for i, c in enumerate(todo, 1):
        result = reverse_geocode_municipality(c["lat"], c["lon"])
        municipality = result.municipality
        display_name = f"{c['name']}（{municipality}）" if municipality else c["name"]

        if result.error:
            error_count += 1
        else:
            success_count += 1

        conn.execute(
            """INSERT OR REPLACE INTO candidate_sites
               (id, source, name, lat, lon, ele, description, municipality, display_name, geocode_error)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (c["id"], c["source"], c["name"], c["lat"], c["lon"], c["ele"], c["description"],
             municipality, display_name, result.error),
        )
        conn.commit()

        if i % 25 == 0 or i == len(todo):
            elapsed = time.time() - start_time
            print(f"  {i}/{len(todo)}件処理 (成功{success_count}/失敗{error_count}, 経過{elapsed/60:.1f}分)")

    conn.close()
    print(f"\n完了。成功{success_count}件 / 失敗{error_count}件。DB: {DB_PATH}")


if __name__ == "__main__":
    main()
