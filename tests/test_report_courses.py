"""scripts/report_courses.py の単体テスト(通信しない)。

テスト用の report.html は、generate_report.py の render_tier2 / render_candidate_group に合成データを渡して作る。
generate_report.py 側のHTML構造が変わると、このテストが落ちて気づける。
"""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import generate_report as gr  # noqa: E402
import report_courses as rc  # noqa: E402

JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 17, 15, 0, tzinfo=JST)


def card(name, muni, score, lat, lon, night=date(2026, 10, 17), start=(21, 15), end=(4, 15), best=(23, 0),
         obstruction=12.4, mpsas=21.806, origin="curated"):
    ws = datetime(2026, 10, night.day, *start, tzinfo=JST)
    we = datetime(2026, 10, night.day + (1 if end < start else 0), *end, tzinfo=JST)
    return SimpleNamespace(
        site_name=name, municipality=muni, score=score, origin=origin, site_lat=lat, site_lon=lon,
        window_start=ws, window_end=we, best_time=datetime(2026, 10, night.day, *best, tzinfo=JST),
        night_date=night, mean_obstruction=obstruction, effective_mpsas=mpsas)


CASUAL = [card("奥只見ダム", "魚沼市", 119.4, 37.2, 139.3), card("枝折峠", "魚沼市", 117.2, 37.1, 139.2, mpsas=21.65),
          card("白州", "北杜市", 100.0, 35.8, 138.3, obstruction=3.0), card("四番目", "どこか市", 90.0, 36.0, 139.0)]
HARDCORE = [card("白米千枚田", "輪島市", 118.6, 37.3, 136.8), card("白木峰展望台", "佐渡市", 118.0, 38.0, 138.3),
            card("三番目", "県内市", 99.0, 36.5, 137.5)]


def build_html(casual=CASUAL, hardcore=HARDCORE, generated="2026-10-17 11:20", weather_note="首都圏は晴れ間が多い見込みです。",
               msm_index=None, msm_nights=3):
    tier2 = gr.render_tier2(casual, hardcore, msm_index, msm_nights if (casual or hardcore) else 0, weather_note)
    return ("<!doctype html><html><head><meta charset=\"utf-8\"></head><body>"
            f"<p class=\"target-line\">対象天体: 天の川銀河中心 ・ 生成日時: {generated} JST</p>{tier2}</body></html>")


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def write_report(self, html_text, name="report.html"):
        p = self.dir / name
        p.write_text(html_text, encoding="utf-8")
        return p

    def run_cli(self, *argv, now=NOW):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = rc.main(list(argv), now=now)
        return code, out.getvalue(), err.getvalue()


class NormalTest(Base):
    def test_both_courses_top3_and_fields(self):
        p = self.write_report(build_html())
        code, out, _ = self.run_cli("--report", str(p))
        self.assertEqual(code, 0)
        self.assertIn("レポート生成日時: 2026-10-17 11:20 JST", out)
        self.assertLess(out.index("気軽コース"), out.index("硬派コース"))
        self.assertIn("1. 奥只見ダム(魚沼市) スコア119 / 東京から直線", out)
        self.assertIn("日付 2026-10-17 / 見頃 21:15〜04:15(翌)(狙い目 23:00) / 視界遮蔽雲量 平均12% / "
                      "実効的な空の明るさ 21.81 mag/arcsec²", out)
        self.assertIn("平均3%", out)  # 3件目
        self.assertNotIn("四番目", out)  # 気軽は上位3件まで
        self.assertIn("3. 三番目(県内市)", out)  # 硬派は3件しか無い
        self.assertIn("上位3件 / レポート内4件", out)
        self.assertIn("条件: 東京から直線距離250km圏内", out)
        self.assertIn("条件: 距離・アクセス方法を問わず", out)
        self.assertIn("気象メモ: 首都圏は晴れ間が多い見込みです。", out)

    def test_distance_matches_generate_report(self):
        p = self.write_report(build_html())
        _, out, _ = self.run_cli("--report", str(p))
        self.assertIn(f"東京から直線{gr.distance_from_tokyo_km(37.2, 139.3):.0f}km", out)

    def test_top_option(self):
        p = self.write_report(build_html())
        _, out, _ = self.run_cli("--report", str(p), "--top", "1")
        self.assertIn("上位1件 / レポート内4件", out)
        self.assertNotIn("2. 枝折峠", out)
        _, out, _ = self.run_cli("--report", str(p), "--top", "4")
        self.assertIn("4. 四番目", out)

    def test_header_format_still_matches_generate_report(self):
        src = (ROOT / "generate_report.py").read_text(encoding="utf-8")
        self.assertIn("生成日時: {generated_at.strftime('%Y-%m-%d %H:%M')} JST", src)


class EmptyAndNoteTest(Base):
    def test_course_without_candidates_shows_report_reason(self):
        p = self.write_report(build_html(casual=[], hardcore=HARDCORE, msm_index=2, msm_nights=0))
        code, out, _ = self.run_cli("--report", str(p))
        self.assertEqual(code, 0)
        self.assertIn("候補なし: 精密予報(MSM)圏内の候補夜まであと約2日です。", out)
        self.assertIn("1. 白米千枚田", out)  # 硬派は出る

    def test_both_empty(self):
        p = self.write_report(build_html(casual=[], hardcore=[], msm_index=None, msm_nights=0))
        code, out, _ = self.run_cli("--report", str(p))
        self.assertEqual(code, 0)
        self.assertEqual(out.count("候補なし:"), 2)
        self.assertIn("MSM", out)

    def test_weather_note_absent(self):
        p = self.write_report(build_html(weather_note=""))
        _, out, _ = self.run_cli("--report", str(p))
        self.assertNotIn("気象メモ", out)


class FreshnessTest(Base):
    def test_today_ok(self):
        p = self.write_report(build_html(generated="2026-10-17 00:05"))
        self.assertEqual(self.run_cli("--report", str(p))[0], 0)

    def test_yesterday_stops_with_2(self):
        p = self.write_report(build_html(generated="2026-10-16 23:59"))
        code, out, err = self.run_cli("--report", str(p))
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("今日(2026-10-17)ではない", err)

    def test_allow_stale_prints_with_warning(self):
        p = self.write_report(build_html(generated="2026-10-16 23:59"))
        code, out, _ = self.run_cli("--report", str(p), "--allow-stale")
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("【古いレポートです】"))
        self.assertIn("1. 奥只見ダム", out)

    def test_missing_file(self):
        code, out, err = self.run_cli("--report", str(self.dir / "none.html"))
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("がありません", err)

    def test_jst_date_boundary(self):
        p = self.write_report(build_html(generated="2026-10-17 08:00"))
        utc_late = datetime(2026, 10, 16, 23, 30, tzinfo=timezone.utc)  # JSTでは10/17 08:30
        self.assertEqual(self.run_cli("--report", str(p), now=utc_late)[0], 0)


class BadStructureTest(Base):
    def assert_exit3(self, html_text):
        p = self.write_report(html_text)
        code, out, err = self.run_cli("--report", str(p))
        self.assertEqual(code, 3)
        self.assertEqual(out, "")
        self.assertIn("解析失敗", err)
        return err

    def test_no_courses(self):
        self.assert_exit3("<html><body><p class=\"target-line\">対象天体: x ・ 生成日時: 2026-10-17 11:20 JST</p></body></html>")

    def test_renamed_card_class(self):
        self.assert_exit3(build_html().replace("cand-card", "candidate-card"))

    def test_missing_stat(self):
        err = self.assert_exit3(build_html().replace("<dt>視界遮蔽雲量</dt>", "<dt>雲量</dt>"))
        self.assertIn("視界遮蔽雲量", err)

    def test_changed_value_format(self):
        err = self.assert_exit3(build_html().replace("mag/arcsec&sup2;", "等級"))
        self.assertIn("空の明るさ", err)

    def test_no_generated_at(self):
        p = self.write_report(build_html().replace("生成日時", "作成"))
        code, _, err = self.run_cli("--report", str(p))
        self.assertEqual(code, 3)
        self.assertIn("生成日時", err)

    def test_missing_hardcore_course(self):
        self.assert_exit3(build_html().replace("硬派コース", "その他"))


class JsonOutTest(Base):
    def test_schema(self):
        p = self.write_report(build_html())
        jp = self.dir / "out" / "c.json"
        txt = self.dir / "out" / "c.txt"
        code, out, _ = self.run_cli("--report", str(p), "--top", "2", "--json-out", str(jp), "--out", str(txt))
        self.assertEqual(code, 0)
        data = json.loads(jp.read_text(encoding="utf-8"))
        self.assertEqual(data["schema"], "hoshibiyori-course-report/1")
        self.assertEqual(data["generated_at"], "2026-10-17T11:20+09:00")
        self.assertFalse(data["stale"])
        self.assertEqual(data["top"], 2)
        self.assertEqual([c["id"] for c in data["courses"]], ["casual", "hardcore"])
        casual = data["courses"][0]
        self.assertEqual(casual["total_candidates"], 4)
        self.assertEqual(len(casual["candidates"]), 2)
        self.assertEqual(casual["weather_note"], "首都圏は晴れ間が多い見込みです。")
        self.assertIsNone(casual["empty_note"])
        k = casual["candidates"][0]
        self.assertEqual(set(k), {"rank", "name", "municipality", "score", "distance_km", "origin", "date", "window",
                                  "best_time", "obstruction_pct", "effective_mpsas", "maps_url"})
        self.assertEqual((k["rank"], k["name"], k["municipality"], k["score"]), (1, "奥只見ダム", "魚沼市", 119))
        self.assertEqual((k["date"], k["window"], k["best_time"]), ("2026-10-17", "21:15〜04:15(翌)", "23:00"))
        self.assertEqual((k["obstruction_pct"], k["effective_mpsas"]), (12, 21.81))
        self.assertTrue(k["maps_url"].startswith("https://www.google.com/maps?q="))
        self.assertEqual(txt.read_text(encoding="utf-8"), out)

    def test_stale_flag_in_json(self):
        p = self.write_report(build_html(generated="2026-10-15 10:00"))
        jp = self.dir / "c.json"
        self.run_cli("--report", str(p), "--allow-stale", "--json-out", str(jp))
        self.assertTrue(json.loads(jp.read_text(encoding="utf-8"))["stale"])

    def test_empty_course_in_json(self):
        p = self.write_report(build_html(casual=[], msm_index=1, msm_nights=0))
        jp = self.dir / "c.json"
        self.run_cli("--report", str(p), "--json-out", str(jp))
        casual = json.loads(jp.read_text(encoding="utf-8"))["courses"][0]
        self.assertEqual(casual["candidates"], [])
        self.assertIn("あと約1日", casual["empty_note"])


if __name__ == "__main__":
    unittest.main()
