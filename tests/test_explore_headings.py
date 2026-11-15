"""探索の一覧の見出し(print_final_report / print_outlook_report)のテスト。2026-11-16 追加。通信しない。

- 天の川モードの見出しは従来の文のまま(文字列をそのまま固定する)。
- 星空・星座モードの見出しは「天の川銀河中心」「スコア順」を使わず、並び順は final_rank_key / outlook_rank_key の順。
- 見出し以外の行は、モードの切り替えで変わらない範囲だけを確かめる(各候補の中身は既存のテストのとおり)。
"""
from __future__ import annotations

import contextlib
import io
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import explore_hoshibiyori as ex  # noqa: E402
from test_explore_json import make_final, make_outlook  # noqa: E402

MW_FINAL_PRIMARY = "探索モード 最終候補一覧・主要候補(対象: 天の川銀河中心、星空撮影名所ベース、スコア順、上位20件)"
MW_FINAL_REFERENCE = "探索モード 最終候補一覧・参考候補(対象: 天の川銀河中心、OSM展望データ由来・星空適性は未検証、上位10件)"
MW_OUTLOOK_PRIMARY = "見込み一覧・主要候補(対象: 天の川銀河中心、星空撮影名所ベース、月・地形・光害による決定論的スコア順、上位20件)"
MW_OUTLOOK_REFERENCE = "見込み一覧・参考候補(対象: 天の川銀河中心、OSM展望データ由来・星空適性は未検証、上位10件)"

ST_FINAL_PRIMARY = ("探索モード 最終候補一覧・主要候補(対象: 星空・星座モード・天の川は対象外、星空撮影名所ベース、"
                    "晴れ時間が長い→平均雲量が低い→光害(ALR)が小さい→月の影響が小さい時間が長い順、上位20件)")
ST_FINAL_REFERENCE = ("探索モード 最終候補一覧・参考候補(対象: 星空・星座モード・天の川は対象外、OSM展望データ由来・星空適性は未検証、"
                      "晴れ時間が長い→平均雲量が低い→光害(ALR)が小さい→月の影響が小さい時間が長い順、上位10件)")
ST_OUTLOOK_PRIMARY = ("見込み一覧・主要候補(対象: 星空・星座モード・天の川は対象外、星空撮影名所ベース、"
                      "光害(ALR)が小さい→月の影響が小さい時間が長い順、上位20件)")
ST_OUTLOOK_REFERENCE = ("見込み一覧・参考候補(対象: 星空・星座モード・天の川は対象外、OSM展望データ由来・星空適性は未検証、"
                        "光害(ALR)が小さい→月の影響が小さい時間が長い順、上位10件)")


def capture(fn, *args, **kw) -> list[str]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        fn(*args, **kw)
    return out.getvalue().splitlines()


def headings(lines: list[str]) -> list[str]:
    return [ln for ln in lines if ln.startswith("探索モード 最終候補一覧") or ln.startswith("見込み一覧")]


class HeadingTests(unittest.TestCase):
    def test_milkyway_headings_unchanged(self):
        finals = [make_final("A"), make_final("B", origin="viewpoint")]
        outlooks = [make_outlook("C"), make_outlook("D", origin="viewpoint")]
        self.assertEqual(headings(capture(ex.print_final_report, finals, target_mode="milkyway")),
                         [MW_FINAL_PRIMARY, MW_FINAL_REFERENCE])
        self.assertEqual(headings(capture(ex.print_outlook_report, outlooks, target_mode="milkyway")),
                         [MW_OUTLOOK_PRIMARY, MW_OUTLOOK_REFERENCE])
        # 既定(target_mode を渡さない)も天の川モード
        self.assertEqual(headings(capture(ex.print_final_report, finals)), [MW_FINAL_PRIMARY, MW_FINAL_REFERENCE])

    def test_stars_headings(self):
        finals = [make_final("A", stars=True), make_final("B", origin="viewpoint", stars=True)]
        outlooks = [make_outlook("C", stars=True), make_outlook("D", origin="viewpoint", stars=True)]
        fh = headings(capture(ex.print_final_report, finals, target_mode="stars"))
        oh = headings(capture(ex.print_outlook_report, outlooks, target_mode="stars"))
        self.assertEqual(fh, [ST_FINAL_PRIMARY, ST_FINAL_REFERENCE])
        self.assertEqual(oh, [ST_OUTLOOK_PRIMARY, ST_OUTLOOK_REFERENCE])
        for h in fh + oh:
            self.assertNotIn("天の川銀河中心", h)
            self.assertNotIn("スコア順", h)

    def test_stars_only_heading_lines_differ_from_old_text(self):
        # 星空・星座モードで、見出し以外の行は従来と同じ(従来の見出しの文に置き換えると全行が一致する)
        finals = [make_final("A", stars=True), make_final("B", origin="viewpoint", stars=True)]
        outlooks = [make_outlook("C", stars=True), make_outlook("D", origin="viewpoint", stars=True)]
        swap = {ST_FINAL_PRIMARY: MW_FINAL_PRIMARY, ST_FINAL_REFERENCE: MW_FINAL_REFERENCE,
                ST_OUTLOOK_PRIMARY: MW_OUTLOOK_PRIMARY, ST_OUTLOOK_REFERENCE: MW_OUTLOOK_REFERENCE}
        for fn, items in ((ex.print_final_report, finals), (ex.print_outlook_report, outlooks)):
            lines = capture(fn, items, target_mode="stars")
            changed = [ln for ln in lines if ln in swap]
            self.assertEqual(len(changed), 2)
            self.assertNotIn("[1位] スコア", "\n".join(lines))   # 候補の中身(星空・星座モードはスコアを出さない)は従来どおり

    def test_order_text_matches_rank_keys(self):
        # 見出しの並び順の説明と、順位キーの実際の順が合っていること(近日中)
        a = make_final("長い晴れ", stars=True, clear_hours=6.0, mean_obstruction=50.0)
        b = make_final("短い晴れ・雲少", stars=True, clear_hours=3.0, mean_obstruction=5.0)
        c = make_final("同じ晴れ・雲少", stars=True, clear_hours=6.0, mean_obstruction=10.0)
        d = make_final("同じ晴れ・雲少・暗い", stars=True, clear_hours=6.0, mean_obstruction=10.0, alr=0.5)
        e = make_final("同じ・暗い・月長い", stars=True, clear_hours=6.0, mean_obstruction=10.0, alr=0.5, moon_free_hours=9.0)
        got = sorted([a, b, c, d, e], key=lambda f: ex.final_rank_key(f, "stars"), reverse=True)
        self.assertEqual([f.site_name for f in got],
                         ["同じ・暗い・月長い", "同じ晴れ・雲少・暗い", "同じ晴れ・雲少", "長い晴れ", "短い晴れ・雲少"])
        o1 = make_outlook("明るい", stars=True, alr=3.0, moon_free_hours=9.0)
        o2 = make_outlook("暗い", stars=True, alr=0.5, moon_free_hours=2.0)
        o3 = make_outlook("暗い・月長い", stars=True, alr=0.5, moon_free_hours=8.0)
        got = sorted([o1, o2, o3], key=lambda o: ex.outlook_rank_key(o, "stars"), reverse=True)
        self.assertEqual([o.site_name for o in got], ["暗い・月長い", "暗い", "明るい"])


    def test_stars_reference_heading_has_same_order_text(self):
        # 星空・星座モードの参考候補の見出しにも、主要候補と同じ並び順の説明が入る(2026-11-16)。並びも同じ順位キー
        self.assertIn(ex.STARS_FINAL_ORDER, ST_FINAL_REFERENCE)
        self.assertIn(ex.STARS_OUTLOOK_ORDER, ST_OUTLOOK_REFERENCE)
        refs = [make_final("短い", origin="viewpoint", stars=True, clear_hours=2.0),
                make_final("長い", origin="viewpoint", stars=True, clear_hours=6.0)]
        lines = capture(ex.print_final_report, refs, target_mode="stars")
        sites = [ln.split(":", 1)[1].strip().split("（")[0] for ln in lines if ln.startswith("  地点")]
        self.assertEqual(sites, ["長い", "短い"])


if __name__ == "__main__":
    unittest.main()
