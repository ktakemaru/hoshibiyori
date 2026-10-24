"""scripts/report_courses.py・weekend_page.py の光害(相対指数ALR)の扱いのテスト。合成データのみ・通信なし。

レポートは generate_report.render_html の実際の描画関数で作る(段階LP2で作り、段階LP3bで ALR だけの形に直した)。
"""
from __future__ import annotations

import io
import os
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
for sub in ("", "scripts", "step1_astronomy", "step2_terrain", "step3_light_pollution", "step4_moonlight", "step5_cloud_forecast"):
    sys.path.insert(0, str(ROOT / sub) if sub else str(ROOT))

import generate_report as gr  # noqa: E402
import report_courses as rc  # noqa: E402
import weekend_page as wp  # noqa: E402

JST = timezone(timedelta(hours=9))
D17 = date(2026, 10, 17)
GEN = datetime(2026, 10, 17, 11, 20)
NOW = GEN.replace(tzinfo=JST)


def card(name, score, lat, lon, alr, rank, night=D17):
    return SimpleNamespace(
        site_name=name, municipality="市", score=score, origin="curated", site_lat=lat, site_lon=lon,
        window_start=datetime(2026, 10, night.day, 21, 15, tzinfo=JST),
        window_end=datetime(2026, 10, night.day + 1, 4, 15, tzinfo=JST),
        best_time=datetime(2026, 10, night.day, 23, 0, tzinfo=JST), night_date=night,
        mean_obstruction=12.4, alr=alr, alr_rank_pct=rank)


def build() -> str:
    casual = [card("奥只見ダム", 119.4, 37.2, 139.3, 2.34, 41.0), card("白州", 100.0, 35.8, 138.3, 3.1, 55.0)]
    hard = casual + [card("白米千枚田", 118.6, 37.3, 136.8, 0.71, 3.0)]
    nights = [SimpleNamespace(night_date=D17, moon_free_hours=6.8, window_start=datetime(2026, 10, 17, 21, tzinfo=JST))]
    return gr.render_html(SimpleNamespace(name="天の川銀河中心"), GEN, nights, {D17: "🌓"}, {}, 0, 3, casual, hard,
                          "首都圏は晴れ間が多い見込みです。", {}, [], {}, "概況")


def build_old_format() -> str:
    """光害を等級で表示していた旧形式のレポート(カードの光害の欄だけを差し替えて作る)。"""
    return re.sub(r"<dt>光害\(相対指数\)</dt><dd>[^<]*</dd>", "<dt>実効的な空の明るさ</dt><dd>21.81 mag/arcsec&sup2;</dd>",
                  build())


class _DataDir:
    """HOSHIBIYORI_DATA_DIR を一時フォルダにする(読み書き先の既定をテスト用に切り替える)。"""

    def __enter__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old = os.environ.get("HOSHIBIYORI_DATA_DIR")
        os.environ["HOSHIBIYORI_DATA_DIR"] = self._tmp.name
        return Path(self._tmp.name)

    def __exit__(self, *exc):
        if self._old is None:
            os.environ.pop("HOSHIBIYORI_DATA_DIR", None)
        else:
            os.environ["HOSHIBIYORI_DATA_DIR"] = self._old
        self._tmp.cleanup()


class ReportCoursesTests(unittest.TestCase):
    def test_parse_fields(self):
        res = rc.build_result(build(), Path("report.html"), 3, False)
        k = res["courses"][0]["candidates"][0]
        self.assertEqual((k["alr"], k["alr_rank_pct"]), (2.34, 41))
        self.assertNotIn("lp_source", res)
        self.assertIn("相対指数", res["lp_note"])
        self.assertEqual(list(k), ["rank", "name", "municipality", "score", "distance_km", "origin", "date", "window",
                                   "best_time", "obstruction_pct", "alr", "alr_rank_pct", "maps_url"])

    def test_old_format_is_rejected_with_hint(self):
        with self.assertRaises(rc.ParseError) as e:
            rc.build_result(build_old_format(), Path("x"), 3, False)
        self.assertIn("旧形式", str(e.exception))

    def test_text_output(self):
        text = rc.format_text(rc.build_result(build(), Path("r"), 3, False), "2026-10-17")
        self.assertIn("相対指数", text)
        self.assertIn("ALR 2.34(主軸の地点のうち暗い方から41%)", text)
        self.assertNotIn("mag/arcsec", text)

    def test_cli_has_no_lp_source_option(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            rc.main(["--lp-source", "bm"], now=NOW)

    def test_cli_default_path_and_missing_message(self):
        with _DataDir() as d:
            err = io.StringIO()
            with redirect_stderr(err), redirect_stdout(io.StringIO()):
                code = rc.main([], now=NOW)
            self.assertEqual(code, rc.EXIT_STALE)
            self.assertIn("report.html", err.getvalue())
            self.assertNotIn("--lp-source", err.getvalue())
            (d / "report.html").write_text(build(), encoding="utf-8")
            out = io.StringIO()
            with redirect_stdout(out):
                code = rc.main([], now=NOW)
            self.assertEqual(code, rc.EXIT_OK)
            self.assertIn("ALR 2.34", out.getvalue())
            self.assertNotIn("mag/arcsec²", out.getvalue())


class WeekendPageTests(unittest.TestCase):
    nights = [D17, date(2026, 10, 18)]

    def test_page_shows_alr_not_magnitude(self):
        page = wp.render_page(wp.load_report(build()), self.nights, 6, None, {})
        self.assertIn("光害(相対指数)", page)
        self.assertIn("ALR 2.34", page)
        self.assertNotIn("<dt>空の明るさ</dt>", page)       # カードに等級の欄が無い
        self.assertNotIn("空の明るさ<br>mag/arcsec²", page)  # 一覧表の見出しにも無い
        self.assertNotIn("(大きいほど暗い)", page)
        self.assertIn("相対指数です", page)
        self.assertIn("10.5067/VIIRS/VNP46A4.002", page)  # フッターはレポートの出典(Black Marble)を引く

    def test_verdict_check_alr_and_mag(self):
        report = wp.load_report(build())

        def commentary(body):
            return {"schema": wp.COMMENTARY_SCHEMA, "verdict": [{"title": "t", "body": body, "tone": "good"}], "extra_notes": []}
        wp.check_verdict(commentary("奥只見ダムはALR 2.34で暗い方です。"), report, [])  # 一致する値は通る
        with self.assertRaises(wp.CommentaryError) as e:
            wp.check_verdict(commentary("ALR 9.99です。"), report, [])
        self.assertIn("ALR 9.99", str(e.exception))
        with self.assertRaises(wp.CommentaryError) as e:
            wp.check_verdict(commentary("空の明るさ 21.80 mag です。"), report, [])
        self.assertIn("等級は無い", str(e.exception))

    def test_cli_output_name_and_default_report(self):
        with _DataDir() as d:
            (d / "report.html").write_text(build(), encoding="utf-8")
            out = d / "page.html"
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                code = wp.main(["--out", str(out), "--dates", "2026-10-17"], now=NOW)
            self.assertEqual(code, wp.EXIT_OK)
            self.assertIn("ALR", out.read_text(encoding="utf-8"))
            so = io.StringIO()
            with redirect_stdout(so), redirect_stderr(io.StringIO()):
                code = wp.main(["--dates", "2026-10-17"], now=NOW)
            self.assertEqual(code, wp.EXIT_OK)
            self.assertIn("weekend_stargazing_20261017.html", so.getvalue())

    def test_cli_old_format_exits_with_parse_error(self):
        with _DataDir() as d:
            (d / "report.html").write_text(build_old_format(), encoding="utf-8")
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                code = wp.main(["--dates", "2026-10-17"], now=NOW)
            self.assertEqual(code, wp.EXIT_PARSE)


if __name__ == "__main__":
    unittest.main()
