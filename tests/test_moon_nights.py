"""scripts/moon_nights.py(月の条件だけで夜を絞る)のテスト。通信しない。

整形・上位の選び方・JSONは暦なしでテストする(純粋な関数)。天文計算を使うテストは de421.bsp(初回自動ダウンロード=通信)が
無い環境ではスキップする(tests/test_sky_guide.py と同じやり方)。
"""
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import moon_nights as mn  # noqa: E402

JST = timezone(timedelta(hours=9))
HAS_BSP = (ROOT / "step1_astronomy" / "de421.bsp").exists()


def _row(d, hours, w=True, phase=90.0, rise=None, set_=None):
    day = datetime(d.year, d.month, d.day, tzinfo=JST)
    return mn.NightRow(
        night_date=d, moon_icon="🌓", moon_phase_deg=phase,
        dark_start=day + timedelta(hours=18, minutes=30), dark_end=day + timedelta(days=1, hours=4, minutes=30),
        window_start=(day + timedelta(hours=22)) if w else None,
        window_end=(day + timedelta(days=1, hours=4, minutes=30)) if w else None,
        moon_free_hours=hours if w else 0.0, moonrise=rise, moonset=set_)


def _rows():
    return [_row(date(2026, 10, 17), 6.8), _row(date(2026, 10, 18), 3.0), _row(date(2026, 10, 19), 6.8),
            _row(date(2026, 10, 24), 0.0, w=False, phase=180.0), _row(date(2026, 10, 20), 5.0)]


class PureFunctionTest(unittest.TestCase):
    def test_weekday_and_date_format(self):
        self.assertEqual(mn.fmt_date(date(2026, 10, 17)), "10/17(土)")
        self.assertEqual(mn.fmt_date(date(2026, 11, 1)), "11/01(日)")

    def test_range_marks_next_day(self):
        r = _row(date(2026, 10, 17), 6.0)
        self.assertEqual(mn.fmt_range(r.window_start, r.window_end, r.night_date), "22:00〜04:30(翌)")
        self.assertEqual(mn.fmt_range(None, None, r.night_date), "なし")
        self.assertEqual(mn.fmt_event(None, r.night_date), "-")

    def test_top_rows_sorted_by_length_then_date_and_skips_no_window(self):
        top = mn.top_rows(_rows(), 3)
        self.assertEqual([r.night_date.day for r in top], [17, 19, 20])  # 6.8(17) 6.8(19) 5.0(20)。窓の無い24日は入らない
        self.assertEqual(len(mn.top_rows(_rows(), 99)), 4)
        self.assertEqual(mn.top_rows([_row(date(2026, 10, 24), 0.0, w=False)], 5), [])

    def test_illum_from_phase(self):
        self.assertAlmostEqual(_row(date(2026, 10, 17), 1, phase=0.0).illum, 0.0)
        self.assertAlmostEqual(_row(date(2026, 10, 17), 1, phase=90.0).illum, 0.5)
        self.assertAlmostEqual(_row(date(2026, 10, 17), 1, phase=180.0).illum, 1.0)

    def test_table_has_required_parts(self):
        text = mn.format_table(_rows(), "テスト基準", 2)
        self.assertIn("基準: テスト基準", text)
        self.assertIn("雲量は未評価", text)
        self.assertGreaterEqual(text.count(mn.NOTE), 2)  # 見出しと末尾
        self.assertIn("generate_report.py の探索を実行する(AGENTS.md 第5節、実行前に承認)", text)
        self.assertIn("10/17(土)", text)
        self.assertIn("6.8時間", text)
        self.assertIn("なし", text)  # 窓の無い夜
        self.assertIn("上位2夜", text)
        self.assertIn("  1. 10/17(土) 6.8時間 22:00〜04:30(翌)", text)

    def test_table_columns_are_aligned(self):
        lines = mn.format_table(_rows(), "x").splitlines()
        sep = next(l for l in lines if set(l) <= {"-", " "} and "--" in l)
        data = [l for l in lines if l.startswith("10/")]
        self.assertTrue(data)
        first = lambda l: mn._w(l[:l.index("  ")])  # noqa: E731  全角は幅2で数える
        self.assertEqual(first(sep), first(data[0]))  # 最初の列の幅がそろっている

    def test_json_schema(self):
        rows = _rows()
        rows[0].moonset = rows[0].dark_start + timedelta(hours=3)
        j = mn.to_json(rows, {"name": "石廊崎", "lat": 34.6, "lon": 138.8, "kind": "default"}, date(2026, 10, 17), 5, 2)
        self.assertEqual(j["schema"], "hoshibiyori-moon-nights/1")
        self.assertEqual(j["cloud"], "not_evaluated")
        self.assertEqual(j["note"], mn.NOTE)
        self.assertEqual(j["start_date"], "2026-10-17")
        self.assertEqual(j["days"], 5)
        self.assertEqual(j["top"], ["2026-10-17", "2026-10-19"])
        n0, n3 = j["nights"][0], j["nights"][3]
        self.assertEqual(set(n0), {"date", "weekday", "moon_icon", "moon_phase_deg", "illum", "dark_start", "dark_end", "window_start",
                                   "window_end", "moon_free_hours", "moonrise", "moonset"})
        self.assertEqual(n0["weekday"], "土")
        self.assertEqual(n0["window_start"], "2026-10-17T22:00+09:00")
        self.assertEqual(n0["moonset"], "2026-10-17T21:30+09:00")
        self.assertIsNone(n0["moonrise"])
        self.assertIsNone(n3["window_start"])
        self.assertEqual(n3["moon_free_hours"], 0.0)
        json.dumps(j, ensure_ascii=False)


class CliWithoutEphemerisTest(unittest.TestCase):
    def _run(self, argv, ephemeris_exists):
        fake_path = mock.Mock()
        fake_path.exists.return_value = ephemeris_exists
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(mn, "EPHEMERIS_PATH", fake_path), mock.patch.object(mn, "load") as load, \
                mock.patch.object(mn, "compute_rows", return_value=[]) as rows, redirect_stdout(out), redirect_stderr(err):
            rc = mn.main(argv)
        return rc, out.getvalue(), err.getvalue(), load, rows

    def test_missing_ephemeris_does_not_download(self):
        rc, _, err, load, rows = self._run(["--start-date", "2026-10-17"], ephemeris_exists=False)
        self.assertNotEqual(rc, 0)
        self.assertIn("de421.bsp", err)
        self.assertIn("--allow-network", err)
        load.timescale.assert_not_called()
        load.assert_not_called()  # 暦の読み込み(=自動ダウンロード)をしない
        rows.assert_not_called()

    def test_allow_network_permits_loading(self):
        rc, out, _, load, rows = self._run(["--start-date", "2026-10-17", "--allow-network"], ephemeris_exists=False)
        self.assertEqual(rc, 0)
        load.assert_called_once()
        rows.assert_called_once()
        self.assertIn("雲量は未評価", out)

    def test_unknown_spot_is_an_error_without_guessing(self):
        rc, _, err, load, _ = self._run(["--spot", "存在しない地点"], ephemeris_exists=True)
        self.assertNotEqual(rc, 0)
        self.assertIn("存在しない地点", err)
        load.assert_not_called()

    def test_bad_start_date_and_days(self):
        self.assertNotEqual(self._run(["--start-date", "2026/10/17"], True)[0], 0)
        self.assertNotEqual(self._run(["--days", "0"], True)[0], 0)


@unittest.skipUnless(HAS_BSP, "step1_astronomy/de421.bsp が無い環境(通信を避けるためスキップ)")
class EphemerisTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from skyfield.api import load
        import explore_hoshibiyori as ex
        cls.ex = ex
        cls.ts = load.timescale()
        cls.eph = load(str(mn.EPHEMERIS_PATH))
        cls.ref = mn.resolve_reference(None)

    def test_default_reference_is_irozaki_like_the_report(self):
        self.assertEqual(self.ref["name"], "石廊崎")
        self.assertEqual(self.ref["kind"], "default")

    def test_same_moon_free_hours_as_all_nights_timeline(self):
        """all_nights_timeline は今日固定なので、現在時刻を 2026-10-17 に固定して同じ呼び出しと比べる。"""
        ex = self.ex
        real_dt = ex.datetime

        class FixedDT(real_dt):
            @classmethod
            def now(cls, tz=None):
                return real_dt(2026, 10, 17, 9, 30, tzinfo=tz or JST)

        with mock.patch.object(ex, "datetime", FixedDT):
            expected = ex.all_nights_timeline(self.ts, self.eph, self.ref["lat"], self.ref["lon"], 14)
        got = mn.compute_rows(self.ts, self.eph, self.ref["lat"], self.ref["lon"], date(2026, 10, 17), 14)
        self.assertEqual(len(got), len(expected))
        self.assertEqual(len(got), 14)
        for g, e in zip(got, expected):
            self.assertEqual(g.night_date, e.night_date)
            self.assertEqual(g.dark_start, e.dark_start)
            self.assertEqual(g.dark_end, e.dark_end)
            self.assertEqual(g.window_start, e.window_start)
            self.assertEqual(g.window_end, e.window_end)
            self.assertEqual(g.moon_free_hours, e.moon_free_hours)

    def test_spot_matches_compute_site_night_window(self):
        spot = mn.resolve_reference("戦場ヶ原")
        got = mn.compute_rows(self.ts, self.eph, spot["lat"], spot["lon"], date(2026, 10, 17), 3)
        for g in got:
            w = self.ex.compute_site_night_window(self.ts, self.eph, {"lat": spot["lat"], "lon": spot["lon"]}, g.night_date)
            self.assertEqual((g.window_start, g.window_end, g.moon_free_hours), w)

    def test_moon_events_fall_inside_the_night(self):
        got = mn.compute_rows(self.ts, self.eph, self.ref["lat"], self.ref["lon"], date(2026, 10, 17), 14)
        self.assertTrue(any(r.moonset for r in got))
        self.assertTrue(any(r.moonrise for r in got))
        for r in got:
            for t in (r.moonrise, r.moonset):
                if t is not None:
                    self.assertGreaterEqual(t.date(), r.night_date)

    def test_cli_end_to_end_writes_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_json = Path(tmp) / "sub" / "m.json"
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                rc = mn.main(["--start-date", "2026-10-17", "--days", "14", "--json-out", str(out_json)])
            self.assertEqual(rc, 0, err.getvalue())
            j = json.loads(out_json.read_text(encoding="utf-8"))
            self.assertEqual(j["schema"], "hoshibiyori-moon-nights/1")
            self.assertEqual(len(j["nights"]), 14)
            self.assertEqual(len(j["top"]), 5)
            self.assertEqual(j["top"][0], "2026-10-17")  # この期間は新月側ではなく上弦前の10/17が最長
            self.assertIn("雲量は未評価", out.getvalue())


if __name__ == "__main__":
    unittest.main()
