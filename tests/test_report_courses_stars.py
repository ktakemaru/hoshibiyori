"""report_courses.py・weekend_page.py が星空・星座モードのレポート(report_stars.html)を読めることのテスト(通信しない)。

テスト用のレポートは、generate_report.render_html に合成データの候補を渡し、target_mode="stars" で作る
(星空・星座モードの実際の描画関数を使うので、generate_report.py 側の構造が変わればこのテストが落ちる)。
天の川モードの動きは既存の tests/test_report_courses.py・tests/test_weekend_page.py が確かめる(ここでは変えない)。
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
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import generate_report as gr  # noqa: E402
import report_courses as rc  # noqa: E402
import weekend_page as wp  # noqa: E402

JST = timezone(timedelta(hours=9))
SAT = datetime(2026, 10, 17, 15, 0, tzinfo=JST)  # 2026-10-17 は土曜
D17, D18 = date(2026, 10, 17), date(2026, 10, 18)


def card(name, muni, lat, lon, night=D17, start=(21, 15), end=(4, 15), clear_hours=5.5, obstruction=12.4,
         alr=2.34, rank=41.0, origin="curated", score=0.0):
    """星空・星座モードの FinalCandidate 相当(score は 0.0、best_time は window_start。探索と同じ)。"""
    ws = datetime(2026, 10, night.day, *start, tzinfo=JST)
    we = datetime(2026, 10, night.day + (1 if end < start else 0), *end, tzinfo=JST)
    return SimpleNamespace(
        site_name=name, municipality=muni, score=score, origin=origin, site_lat=lat, site_lon=lon,
        window_start=ws, window_end=we, best_time=ws, night_date=night, mean_obstruction=obstruction,
        alr=alr, alr_rank_pct=rank, clear_hours=clear_hours)


CASUAL = [card("奥只見ダム", "魚沼市", 37.2, 139.3, clear_hours=7.0),
          card("枝折峠", "魚沼市", 37.1, 139.2, clear_hours=5.5, alr=3.1, rank=55.0),
          card("奥只見ダム", "魚沼市", 37.2, 139.3, night=D18, start=(22, 30), clear_hours=4.5)]
HARDCORE = [card("白米千枚田", "輪島市", 37.3, 136.8, start=(20, 0), clear_hours=8.2),
            card("白木峰展望台", "佐渡市", 38.0, 138.3, clear_hours=6.0)]


def moon_nights(days=(17, 18, 19), hours=(6.8, 5.8, 0.0)):
    return [SimpleNamespace(night_date=date(2026, 10, d), moon_free_hours=h,
                            window_start=(datetime(2026, 10, d, 21, tzinfo=JST) if h else None))
            for d, h in zip(days, hours)]


def build_html(target_mode="stars", casual=CASUAL, hardcore=HARDCORE, generated="2026-10-17 11:20"):
    nights = moon_nights()
    icons = {n.night_date: "🌓" for n in nights}
    gen = datetime.strptime(generated, "%Y-%m-%d %H:%M")
    return gr.render_html(SimpleNamespace(name="天の川銀河中心"), gen, nights, icons, {}, 0, 3, casual, hardcore,
                          "首都圏は晴れ間が多い見込みです。", {}, [], {}, "概況", target_mode=target_mode)


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.report = self.dir / "report_stars.html"
        self.report.write_text(build_html(), encoding="utf-8")

    def run_rc(self, *argv, now=SAT):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = rc.main(list(argv), now=now)
        return code, out.getvalue(), err.getvalue()

    def run_wp(self, *argv, now=SAT, report=None):
        args = ["--access-notes", str(self.dir / "no_notes.json"), "--weather-commentary", str(self.dir / "no_wc.json"),
                "--spots", str(self.dir / "no_spots.json")]
        if report is not False:
            args = ["--report", str(report or self.report)] + args
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = wp.main(args + list(argv), now=now)
        return code, out.getvalue(), err.getvalue()


class ReportCoursesStarsTest(Base):
    def test_fixture_is_stars_mode_without_score_badge(self):
        html_text = self.report.read_text(encoding="utf-8")
        self.assertIn("星空・星座モード", html_text)
        self.assertNotIn('class="badge score"', html_text)
        self.assertNotIn("狙い目", html_text)

    def test_parses_stars_report(self):
        js = self.dir / "c.json"
        code, out, err = self.run_rc("--report", str(self.report), "--top", "5", "--json-out", str(js))
        self.assertEqual(code, 0, err)
        result = json.loads(js.read_text(encoding="utf-8"))
        self.assertEqual(result["target"], "stars")
        casual = result["courses"][0]["candidates"]
        self.assertEqual([c["name"] for c in casual], ["奥只見ダム", "枝折峠", "奥只見ダム"])
        for c in casual + result["courses"][1]["candidates"]:
            self.assertIsNone(c["score"])        # 0 や推測で埋めない
            self.assertIsNone(c["best_time"])
        self.assertEqual([c["clear_hours"] for c in casual], [7.0, 5.5, 4.5])
        self.assertEqual(casual[0]["window"], "21:15〜04:15(翌)")
        self.assertEqual(casual[1]["alr"], 3.1)
        self.assertIn(rc.STARS_MODE_LABEL, out)
        self.assertNotIn("スコア", out.replace("スコアと狙い目はレポートにありません", ""))
        self.assertIn("(晴れ間 7.0時間)", out)
        self.assertNotIn("None", out)

    def test_target_stars_uses_report_stars_html_by_default(self):
        with mock.patch.object(rc, "resolve_data_root", lambda root: self.dir):
            code, out, err = self.run_rc("--target", "stars")
        self.assertEqual(code, 0, err)
        self.assertIn("晴れ間", out)

    def test_target_stars_missing_file_mentions_stars_command(self):
        with mock.patch.object(rc, "resolve_data_root", lambda root: self.dir / "empty"):
            code, _, err = self.run_rc("--target", "stars")
        self.assertEqual(code, rc.EXIT_STALE)
        self.assertIn("report_stars.html", err)
        self.assertIn("generate_report.py --target stars", err)

    def test_target_mismatch_is_parse_error(self):
        code, _, err = self.run_rc("--report", str(self.report), "--target", "milkyway")
        self.assertEqual(code, rc.EXIT_PARSE)
        self.assertIn("星空・星座モード(stars)", err)
        mw = self.dir / "report.html"
        mw.write_text(build_html("milkyway", casual=[card("奥只見ダム", "魚沼市", 37.2, 139.3, score=119.4)],
                                 hardcore=[]), encoding="utf-8")
        code, _, err = self.run_rc("--report", str(mw), "--target", "stars")
        self.assertEqual(code, rc.EXIT_PARSE)
        self.assertIn("天の川モード(milkyway)", err)

    def test_stars_header_with_score_badge_is_not_guessed(self):
        mw_text = build_html("milkyway", casual=[card("奥只見ダム", "魚沼市", 37.2, 139.3, score=119.4)], hardcore=[])
        mixed = mw_text.replace('<p class="target-line">対象天体: ', '<p class="target-line">星空・星座モード ・ ')
        self.assertNotEqual(mixed, mw_text)
        p = self.dir / "mixed.html"
        p.write_text(mixed, encoding="utf-8")
        code, _, err = self.run_rc("--report", str(p))
        self.assertEqual(code, rc.EXIT_PARSE)
        self.assertIn("スコアのバッジがある", err)

    def test_stale_stars_report_still_stops(self):
        code, _, err = self.run_rc("--report", str(self.report), now=SAT + timedelta(days=1))
        self.assertEqual(code, rc.EXIT_STALE)
        self.assertIn("report_stars.html の生成日時", err)

    def test_milkyway_result_has_no_target_key(self):
        mw = self.dir / "report.html"
        mw.write_text(build_html("milkyway", casual=[card("奥只見ダム", "魚沼市", 37.2, 139.3, score=119.4)],
                                 hardcore=[]), encoding="utf-8")
        js = self.dir / "m.json"
        code, out, err = self.run_rc("--report", str(mw), "--json-out", str(js))
        self.assertEqual(code, 0, err)
        result = json.loads(js.read_text(encoding="utf-8"))
        self.assertNotIn("target", result)
        self.assertEqual(result["courses"][0]["candidates"][0]["score"], 119)
        self.assertNotIn("clear_hours", result["courses"][0]["candidates"][0])
        self.assertNotIn("星空・星座モード", out)


class WeekendPageStarsTest(Base):
    def test_page_from_stars_report(self):
        out = self.dir / "w.html"
        code, _, err = self.run_wp("--out", str(out))
        self.assertEqual(code, 0, err)
        page = out.read_text(encoding="utf-8")
        self.assertIn(rc.STARS_MODE_LABEL, page)
        self.assertIn("(晴れ間 7.0時間)", page)
        body = page.replace("スコアと狙い目はありません", "")   # モードの注記の文を除いて確かめる
        self.assertNotIn("狙い目", body)
        self.assertNotIn("スコア ", body)            # カードのスコアのタグが無い
        self.assertNotIn("<th>スコア</th>", page)    # 一覧表のスコアの列が無い
        self.assertNotIn("None", page)
        self.assertIn("白米千枚田", page)
        self.assertIn("日曜の夜", page)

    def test_target_stars_default_path(self):
        out = self.dir / "w2.html"
        with mock.patch.object(wp, "resolve_data_root", lambda root: self.dir):
            code, _, err = self.run_wp("--target", "stars", "--out", str(out), report=False)
        self.assertEqual(code, 0, err)
        self.assertTrue(out.exists())

    def test_target_mismatch(self):
        code, _, err = self.run_wp("--target", "milkyway", "--out", str(self.dir / "w3.html"))
        self.assertEqual(code, wp.EXIT_PARSE)
        self.assertIn("星空・星座モード(stars)", err)
        self.assertFalse((self.dir / "w3.html").exists())

    def commentary(self, body):
        p = self.dir / "cm.json"
        p.write_text(json.dumps({"schema": wp.COMMENTARY_SCHEMA, "extra_notes": [],
                                 "verdict": [{"title": "土曜が本命", "body": body, "tone": "good"}]},
                                ensure_ascii=False), encoding="utf-8")
        return p

    def test_verdict_accepts_window_times_and_clear_hours(self):
        out = self.dir / "w4.html"
        code, _, err = self.run_wp("--out", str(out), "--commentary",
                                   str(self.commentary("奥只見ダムは21:15から晴れ間7.0時間の見込みです。")))
        self.assertEqual(code, 0, err)

    def test_verdict_rejects_unknown_time_and_hours(self):
        code, _, err = self.run_wp("--out", str(self.dir / "w5.html"), "--commentary",
                                   str(self.commentary("奥只見ダムは23:00が狙い目で9.9時間晴れます。")))
        self.assertEqual(code, wp.EXIT_COMMENTARY)
        self.assertIn("23:00", err)
        self.assertIn("9.9時間", err)
        self.assertFalse((self.dir / "w5.html").exists())

    def test_stale_stars_report_still_stops(self):
        code, _, err = self.run_wp("--out", str(self.dir / "w6.html"), now=SAT + timedelta(days=1))
        self.assertEqual(code, wp.EXIT_STALE)
        self.assertIn("report_stars.html の生成日時", err)


if __name__ == "__main__":
    unittest.main()
