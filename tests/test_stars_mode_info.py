"""星空・星座モードの情報の追加(予報の端の印・空の開け具合・冬の天の川の帯)のテスト。2026-11-24 追加。通信しない。

どれも情報を足すだけで、候補の選び方・順位・スコアは変わらないことも確かめる。
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import explore_hoshibiyori as ex  # noqa: E402
import explore_json as ej  # noqa: E402
import generate_report as gr  # noqa: E402
import winter_milkyway as wm  # noqa: E402
from test_explore_json import SCHEMA_PATH, build, make_final, make_night, make_outlook, t, validate  # noqa: E402
from test_explore_scanned_nights import scan_fixture  # noqa: E402

JST = timezone(timedelta(hours=9))
BSP = ex.DATA_ROOT / "step1_astronomy" / "de421.bsp"
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
FLAT = {az: 3.0 for az in range(360)}
VALLEY = {az: (35.0 if 90 <= az < 270 else 25.0) for az in range(360)}
HALF = {az: (30.0 if az < 180 else 20.0) for az in range(360)}     # 20°ちょうどは「開けている」


class SkyOpennessTests(unittest.TestCase):
    def test_flat_ridge(self):
        self.assertEqual(ex.sky_openness_of(FLAT), {"ridge_mean_deg": 3.0, "ridge_max_deg": 3.0, "open_fraction": 1.0,
                                                    "open_alt_deg": 20.0})

    def test_valley(self):
        o = ex.sky_openness_of(VALLEY)
        self.assertEqual((o["ridge_mean_deg"], o["ridge_max_deg"], o["open_fraction"]), (30.0, 35.0, 0.0))

    def test_boundary(self):
        self.assertEqual(ex.sky_openness_of(HALF)["open_fraction"], 0.5)

    def test_no_data_is_none(self):
        self.assertIsNone(ex.sky_openness({"horizon_csv": None}))
        self.assertIsNone(ex.sky_openness({}))

    def test_real_site(self):
        site = next(s for s in ex.load_candidate_sites() if s["horizon_csv"])
        o = ex.sky_openness(site)
        self.assertGreaterEqual(o["ridge_max_deg"], o["ridge_mean_deg"])
        self.assertTrue(0.0 <= o["open_fraction"] <= 1.0)

    def test_text(self):
        self.assertEqual(ex.sky_openness_text(ex.sky_openness_of(VALLEY)), "稜線の平均 30°・最大 35°")
        self.assertEqual(ex.sky_openness_text({"ridge_mean_deg": -0.2, "ridge_max_deg": 24.4}), "稜線の平均 0°・最大 24°")
        self.assertIsNone(ex.sky_openness_text(None))

    def test_rank_key_ignores_it(self):
        a, b = make_final("A", stars=True), make_final("A", stars=True, sky_openness=ex.sky_openness_of(VALLEY))
        self.assertEqual(ex.final_rank_key(a, "stars"), ex.final_rank_key(b, "stars"))
        c, d = make_outlook("A", stars=True), make_outlook("A", stars=True, sky_openness=ex.sky_openness_of(VALLEY))
        self.assertEqual(ex.outlook_rank_key(c, "stars"), ex.outlook_rank_key(d, "stars"))

    def test_json(self):
        doc = build([make_final("A", sky_openness=ex.sky_openness_of(VALLEY))], [make_outlook("B")])
        self.assertEqual(doc["finals"][0]["sky_openness"]["ridge_max_deg"], 35.0)
        self.assertIsNone(doc["outlooks"][0]["sky_openness"])
        self.assertEqual(validate(doc, SCHEMA, SCHEMA), [])

    def printed(self, fn, items, mode):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            fn(items, SimpleNamespace(name="天の川銀河中心"), 10, mode)
        return out.getvalue()

    def test_screen_only_in_stars_mode(self):
        o = ex.sky_openness_of(VALLEY)
        for fn, make in ((ex._print_final_items, make_final), (ex._print_outlook_items, make_outlook)):
            self.assertIn("空の開け  : 稜線の平均 30°・最大 35°", self.printed(fn, [make("A", stars=True, sky_openness=o)], "stars"))
            self.assertNotIn("空の開け", self.printed(fn, [make("A", sky_openness=o)], "milkyway"))
            self.assertNotIn("空の開け", self.printed(fn, [make("A", stars=True)], "stars"))     # データの無い地点は出さない

    def test_report_card_only_in_stars_mode(self):
        card = make_final("A", stars=True, sky_openness=ex.sky_openness_of(VALLEY))
        self.assertIn("<dt>空の開け</dt><dd>稜線の平均 30°・最大 35°</dd>", gr.render_candidate_group([card], "t", "n", "e", stars_mode=True))
        self.assertNotIn("空の開け", gr.render_candidate_group([make_final("A")], "t", "n", "e"))
        self.assertNotIn("空の開け", gr.render_candidate_group([make_final("A", stars=True)], "t", "n", "e", stars_mode=True))


class EcmwfOnlyNoteTests(unittest.TestCase):
    def test_outlook_rows_carry_the_note(self):
        for mode, stars in (("milkyway", False), ("stars", True)):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                ex._print_outlook_items([make_outlook("A", stars=stars)], SimpleNamespace(name="x"), 10, mode)
            self.assertIn("日付      : 2026-11-20 ECMWFだけの予報(目安)", out.getvalue())
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            ex._print_final_items([make_final("A")], SimpleNamespace(name="x"), 10, "milkyway")
        self.assertNotIn("ECMWFだけ", out.getvalue())      # 精密予報の夜には付けない

    def test_calendar(self):
        nights = [make_night(20), make_night(21)]
        html = gr.render_tier3(nights, {}, {n.night_date: "🌑" for n in nights}, None,
                               regimes={date(2026, 11, 20): "ECMWF"})
        self.assertEqual(html.count("ECMWFだけの予報(目安)"), 1)
        self.assertNotIn("ECMWFだけ", gr.render_tier3(nights, {}, {n.night_date: "🌑" for n in nights}, None))


class BandSummaryTests(unittest.TestCase):
    """高度を手で与える(天文計算をしない)。"""
    TIMES = [t(20, 18) + timedelta(minutes=30 * i) for i in range(6)]

    def alts(self, high_counts):
        n = len(wm.BAND_L_DEG)
        return [[(180.0, 40.0)] * c + [(180.0, 5.0)] * (n - c) for c in high_counts]

    def test_half_or_more(self):
        self.assertEqual(len(wm.BAND_L_DEG), 11)
        s = wm.summarize(self.TIMES, self.alts([5, 6, 8, 7, 5, 0]))      # 11点の半分以上 = 6点
        self.assertEqual((s["high_start"], s["high_end"], s["peak_time"]), (self.TIMES[1], self.TIMES[3], self.TIMES[2]))
        self.assertEqual((s["peak_point_alt_deg"], s["peak_point_az_deg"]), (40.0, 180.0))

    def test_never(self):
        s = wm.summarize(self.TIMES, self.alts([5] * 6))
        self.assertEqual(set(s.values()), {None})
        self.assertEqual(wm.band_text(date(2026, 11, 20), dict(s, moon_up_intervals=[])), "冬の天の川の帯: この夜は高く出ません")

    def test_exactly_20_is_high(self):
        pts = [[(0.0, 20.0)] * 11]
        self.assertEqual(wm.summarize(self.TIMES[:1], pts)["high_start"], self.TIMES[0])

    def test_text(self):
        band = dict(wm.summarize(self.TIMES, self.alts([11] * 6)), moon_up_intervals=[{"start": t(20, 22, 10), "end": t(21, 1, 20)}])
        self.assertEqual(wm.band_text(date(2026, 11, 20), band),
                         "冬の天の川の帯: 18:00〜20:30に高く、18:00ごろ最も高い(帯のいちばん高い所は南の高度40°)。月は22:00〜翌01:30に出ている")


class ScannedNightTests(unittest.TestCase):
    def test_json_item(self):
        nights, scan = scan_fixture()
        band = dict(wm.summarize([t(17, 20)], [[(0.0, 30.0)] * 11]), moon_up_intervals=[])
        recs = ej.scanned_night_records(scan, [n.night_date for n in nights], [], {date(2026, 11, 17): band})
        self.assertEqual(recs[0]["winter_milky_way"]["high_start"], "2026-11-17T20:00:00+09:00")
        self.assertIsNone(recs[1]["winter_milky_way"])
        for r in recs:
            self.assertEqual(validate(r, SCHEMA["$defs"]["scanned_night"], SCHEMA), [])
        # 今ある項目は変わらない
        before = ej.scanned_night_records(scan, [n.night_date for n in nights], [])
        self.assertEqual([{k: v for k, v in r.items() if k != "winter_milky_way"} for r in recs], before)

    def test_report_lines(self):
        nights = [make_night(17), make_night(18)]
        band = dict(wm.summarize([t(17, 20)], [[(0.0, 30.0)] * 11]), moon_up_intervals=[])
        html = gr.render_winter_bands(nights, {date(2026, 11, 17): band, date(2026, 11, 18): None})
        self.assertEqual(html.count("<li>"), 2)
        self.assertIn("この夜は高く出ません", html)
        self.assertEqual(gr.render_winter_bands(nights, {}), "")


@unittest.skipUnless(BSP.exists(), "de421.bsp が無い環境では天文計算のテストをスキップ")
class BandAstronomyTests(unittest.TestCase):
    LAT, LON = 34.602778, 138.845278     # 基準地点(石廊崎)

    @classmethod
    def setUpClass(cls):
        cls.ts = ex.load.timescale()
        cls.eph = ex.load(str(BSP))
        cls.addClassCleanup(cls.eph.close)

    def band(self, y, m, d):
        start, end = ex.find_astro_dark_events(self.ts, self.eph, self.LAT, self.LON, datetime(y, m, d, tzinfo=JST))
        return wm.night_band(self.ts, self.eph, self.LAT, self.LON, start, end)

    def test_galactic_conversion_matches_galactic_center(self):
        from skyguide.astro import galactic_to_radec
        ra, dec = galactic_to_radec(0.0, 0.0)
        gc = ex.get_target(ex.TARGET_ID)
        self.assertLess(abs(ra - gc.ra_hours) * 15, 0.12)      # 銀経0°と Sgr A* は約0.07°離れている
        self.assertLess(abs(dec - gc.dec_deg), 0.12)

    def test_winter_nights_are_high(self):
        for y, m, d in ((2026, 11, 20), (2026, 12, 15), (2027, 1, 15)):
            b = self.band(y, m, d)
            self.assertIsNotNone(b["high_start"], (y, m, d))
            self.assertGreater((b["high_end"] - b["high_start"]).total_seconds() / 3600, 5.0)
            self.assertGreater(b["peak_point_alt_deg"], 60.0)

    def test_june_nights_are_not(self):
        for d in (1, 15, 28):
            self.assertIsNone(self.band(2027, 6, d)["high_start"], d)

    def test_moon_intervals_match_moon_position(self):
        start, end = datetime(2026, 11, 20, 18, tzinfo=JST), datetime(2026, 11, 21, 4, tzinfo=JST)
        intervals = wm.moon_up_intervals(self.ts, self.eph, self.LAT, self.LON, start, end)
        x = start
        while x <= end:
            up = ex.compute_moon_position(self.ts, self.eph, self.LAT, self.LON, 0.0, x).alt_deg > 0
            self.assertEqual(up, any(a <= x < b or x == b == end for a, b in intervals), x)
            x += timedelta(minutes=15)

    def test_no_darkness_is_none(self):
        self.assertIsNone(wm.night_band(self.ts, self.eph, self.LAT, self.LON, None, None))


if __name__ == "__main__":
    unittest.main()
