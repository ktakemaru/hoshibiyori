"""scripts/report_courses.py・weekend_page.py の --lp-source bm 対応(段階LP2)のテスト。合成データのみ・通信なし。

bmのレポートは generate_report.render_html(lp_source="bm") の実際の描画関数で作り、legacyの既定の挙動が
変わっていないことも併せて確認する。
"""
from __future__ import annotations

import io
import os
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


def card(name, score, lat, lon, mpsas=None, alr=None, rank=None, night=D17):
    return SimpleNamespace(
        site_name=name, municipality="市", score=score, origin="curated", site_lat=lat, site_lon=lon,
        window_start=datetime(2026, 10, night.day, 21, 15, tzinfo=JST),
        window_end=datetime(2026, 10, night.day + 1, 4, 15, tzinfo=JST),
        best_time=datetime(2026, 10, night.day, 23, 0, tzinfo=JST), night_date=night,
        mean_obstruction=12.4, effective_mpsas=mpsas, alr=alr, alr_rank_pct=rank)


def build(lp_source: str) -> str:
    if lp_source == "bm":
        casual = [card("奥只見ダム", 119.4, 37.2, 139.3, alr=2.34, rank=41.0), card("白州", 100.0, 35.8, 138.3, alr=3.1, rank=55.0)]
        hard = casual + [card("白米千枚田", 118.6, 37.3, 136.8, alr=0.71, rank=3.0)]
    else:
        casual = [card("奥只見ダム", 119.4, 37.2, 139.3, mpsas=21.806), card("白州", 100.0, 35.8, 138.3, mpsas=21.65)]
        hard = casual + [card("白米千枚田", 118.6, 37.3, 136.8, mpsas=21.9)]
    nights = [SimpleNamespace(night_date=D17, moon_free_hours=6.8, window_start=datetime(2026, 10, 17, 21, tzinfo=JST))]
    return gr.render_html(SimpleNamespace(name="天の川銀河中心"), GEN, nights, {D17: "🌓"}, {}, 0, 3, casual, hard,
                          "首都圏は晴れ間が多い見込みです。", {}, [], {}, "概況", lp_source=lp_source)


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


class ReportCoursesBmTests(unittest.TestCase):
    def test_bm_parse_fields(self):
        res = rc.build_result(build("bm"), Path("report_bm.html"), 3, False, "bm")
        k = res["courses"][0]["candidates"][0]
        self.assertEqual((k["alr"], k["alr_rank_pct"]), (2.34, 41))
        self.assertNotIn("effective_mpsas", k)
        self.assertEqual(res["lp_source"], "bm")
        self.assertIn("相対指数", res["lp_note"])

    def test_legacy_result_unchanged(self):
        res = rc.build_result(build("legacy"), Path("report_legacy.html"), 3, False, "legacy")
        self.assertNotIn("lp_source", res)
        k = res["courses"][0]["candidates"][0]
        self.assertNotIn("alr", k)
        # 項目の並び(JSONの順)は従来どおり
        self.assertEqual(list(k), ["rank", "name", "municipality", "score", "distance_km", "origin", "date", "window",
                                   "best_time", "obstruction_pct", "effective_mpsas", "maps_url"])
        self.assertEqual(k["effective_mpsas"], 21.81)

    def test_wrong_source_is_rejected_with_hint(self):
        with self.assertRaises(rc.ParseError) as e:
            rc.build_result(build("bm"), Path("x"), 3, False, "legacy")
        self.assertIn("--lp-source bm", str(e.exception))
        with self.assertRaises(rc.ParseError) as e:
            rc.build_result(build("legacy"), Path("x"), 3, False, "bm")
        self.assertIn("--lp-source legacy", str(e.exception))

    def test_text_output(self):
        text = rc.format_text(rc.build_result(build("bm"), Path("r"), 3, False, "bm"), "2026-10-17")
        self.assertIn("相対指数", text)
        self.assertIn("ALR 2.34(主軸の地点のうち暗い方から41%)", text)
        self.assertNotIn("mag/arcsec", text)
        legacy = rc.format_text(rc.build_result(build("legacy"), Path("r"), 3, False, "legacy"), "2026-10-17")
        self.assertIn("mag/arcsec²", legacy)
        self.assertNotIn("ALR", legacy)

    def test_cli_default_path_and_missing_message(self):
        with _DataDir() as d:
            err = io.StringIO()
            with redirect_stderr(err), redirect_stdout(io.StringIO()):
                code = rc.main(["--lp-source", "bm"], now=NOW)
            self.assertEqual(code, rc.EXIT_STALE)
            self.assertIn("report.html", err.getvalue())
            self.assertNotIn("--lp-source", err.getvalue())  # 既定(bm)の再生成コマンドに引数は要らない
            (d / "report.html").write_text(build("bm"), encoding="utf-8")
            out = io.StringIO()
            with redirect_stdout(out):
                code = rc.main(["--lp-source", "bm"], now=NOW)
            self.assertEqual(code, rc.EXIT_OK)
            self.assertIn("ALR 2.34", out.getvalue())

    def test_cli_default_reads_report_html_as_bm(self):
        with _DataDir() as d:
            (d / "report.html").write_text(build("bm"), encoding="utf-8")
            out = io.StringIO()
            with redirect_stdout(out):
                code = rc.main([], now=NOW)
            self.assertEqual(code, rc.EXIT_OK)
            self.assertIn("ALR 2.34", out.getvalue())
            self.assertNotIn("mag/arcsec²", out.getvalue())

    def test_cli_legacy_reads_report_legacy_html(self):
        with _DataDir() as d:
            err = io.StringIO()
            with redirect_stderr(err), redirect_stdout(io.StringIO()):
                self.assertEqual(rc.main(["--lp-source", "legacy"], now=NOW), rc.EXIT_STALE)
            self.assertIn("report_legacy.html", err.getvalue())
            self.assertIn("--lp-source legacy", err.getvalue())
            (d / "report_legacy.html").write_text(build("legacy"), encoding="utf-8")
            out = io.StringIO()
            with redirect_stdout(out):
                code = rc.main(["--lp-source", "legacy"], now=NOW)
            self.assertEqual(code, rc.EXIT_OK)
            self.assertIn("mag/arcsec²", out.getvalue())


class WeekendPageBmTests(unittest.TestCase):
    nights = [D17, date(2026, 10, 18)]

    def test_bm_page_shows_alr_not_mpsas(self):
        page = wp.render_page(wp.load_report(build("bm"), "bm"), self.nights, 6, None, {})
        self.assertIn("光害(相対指数)", page)
        self.assertIn("ALR 2.34", page)
        self.assertNotIn("<dt>空の明るさ</dt>", page)       # カードに等級の欄が無い
        self.assertNotIn("空の明るさ<br>mag/arcsec²", page)  # 一覧表の見出しにも無い
        self.assertNotIn("(大きいほど暗い)", page)
        self.assertIn("相対指数です", page)
        self.assertIn("10.5067/VIIRS/VNP46A4.002", page)  # フッターはレポートの出典(Black Marble)を引く

    def test_legacy_page_has_no_bm_parts(self):
        report = wp.load_report(build("legacy"), "legacy")
        self.assertNotIn("lp_source", report)
        page = wp.render_page(report, self.nights, 6, None, {})
        self.assertIn("mag/arcsec²", page)
        self.assertNotIn("ALR", page)
        self.assertNotIn("相対指数", page)

    def test_verdict_check_alr_and_mag(self):
        report = wp.load_report(build("bm"), "bm")

        def commentary(body):
            return {"schema": wp.COMMENTARY_SCHEMA, "verdict": [{"title": "t", "body": body, "tone": "good"}], "extra_notes": []}
        wp.check_verdict(commentary("奥只見ダムはALR 2.34で暗い方です。"), report, [])  # 一致する値は通る
        with self.assertRaises(wp.CommentaryError) as e:
            wp.check_verdict(commentary("ALR 9.99です。"), report, [])
        self.assertIn("ALR 9.99", str(e.exception))
        with self.assertRaises(wp.CommentaryError) as e:
            wp.check_verdict(commentary("空の明るさ 21.80 mag です。"), report, [])
        self.assertIn("等級が無い", str(e.exception))
        with self.assertRaises(wp.CommentaryError) as e:
            wp.check_verdict(commentary("ALR 2.34です。"), wp.load_report(build("legacy"), "legacy"), [])
        self.assertIn("legacyのレポートにはALRが無い", str(e.exception))

    def test_cli_bm_output_name_and_default_report(self):
        with _DataDir() as d:
            (d / "report.html").write_text(build("bm"), encoding="utf-8")
            out = d / "page.html"
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                code = wp.main(["--lp-source", "bm", "--out", str(out), "--dates", "2026-10-17"], now=NOW)
            self.assertEqual(code, wp.EXIT_OK)
            self.assertIn("ALR", out.read_text(encoding="utf-8"))
            so = io.StringIO()  # 出力先を省略すると既定(bm)のページ名。legacyは別名(_legacy)になる
            with redirect_stdout(so), redirect_stderr(io.StringIO()):
                code = wp.main(["--dates", "2026-10-17"], now=NOW)
            self.assertEqual(code, wp.EXIT_OK)
            self.assertIn("weekend_stargazing_20261017.html", so.getvalue())
            self.assertNotIn("_legacy", so.getvalue())
            (d / "report_legacy.html").write_text(build("legacy"), encoding="utf-8")
            so = io.StringIO()
            with redirect_stdout(so), redirect_stderr(io.StringIO()):
                code = wp.main(["--lp-source", "legacy", "--dates", "2026-10-17"], now=NOW)
            self.assertEqual(code, wp.EXIT_OK)
            self.assertIn("weekend_stargazing_20261017_legacy.html", so.getvalue())

    def test_cli_wrong_source_exits_with_parse_error(self):
        with _DataDir() as d:
            (d / "report.html").write_text(build("legacy"), encoding="utf-8")  # 形式の食い違い
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                code = wp.main(["--lp-source", "bm", "--dates", "2026-10-17"], now=NOW)
            self.assertEqual(code, wp.EXIT_PARSE)


if __name__ == "__main__":
    unittest.main()
