"""dedup.pyで検出・提示した判断案のうち、ユーザーが承認した削除を実行する。

このスクリプトは無条件に全重複を削除するものではなく、実行の都度、
承認済みの削除対象IDを明示的にリストしたうえで実行する(誤操作防止)。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "candidate_sites.db"

# 承認済み: 検証済み8地点(実質7地点+重複)が絡む4グループについて、
# 検証済みレコードを残し、対応するviewpointレコードを削除する。
APPROVED_DELETIONS = [
    ("viewpoint:6371840327", "山頂", "富士山頂と重複(362m)"),
    ("viewpoint:11953177732", "他手合浜", "精進湖 他手合浜と重複(139m)"),
    ("viewpoint:5156420649", "石廊崎", "石廊崎(検証済み)と重複(116m)"),
    ("viewpoint:12966853290", "第二五之町踏切", "いすみ鉄道踏切と重複(6m)"),
]


def main() -> None:
    conn = sqlite3.connect(DB_PATH)

    before_count = conn.execute("SELECT COUNT(*) FROM candidate_sites").fetchone()[0]
    print(f"削除前の総件数: {before_count}")

    for id_, name, reason in APPROVED_DELETIONS:
        row = conn.execute("SELECT name FROM candidate_sites WHERE id = ?", (id_,)).fetchone()
        if row is None:
            print(f"  [スキップ] id={id_} は既に存在しません")
            continue
        conn.execute("DELETE FROM candidate_sites WHERE id = ?", (id_,))
        print(f"  [削除] id={id_}  name={row[0]!r}  理由: {reason}")

    conn.commit()

    after_count = conn.execute("SELECT COUNT(*) FROM candidate_sites").fetchone()[0]
    print(f"\n削除後の総件数: {after_count}  (差分: {before_count - after_count}件削除)")

    conn.close()


if __name__ == "__main__":
    main()
