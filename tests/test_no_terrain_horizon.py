"""地形データの無い地点の、天の川モードでの地平線の判定(2026-11-16、利用者の承認)のテスト。通信しない。

地形地平線のデータ(horizon CSV)が無い地点は、地平線を水平(高度0°)として判定する。
altaz_at_time を差し替えて、時刻ごとの銀河中心の高度を手で与える(天文計算をしない)。
"""
from __future__ import annotations

import contextlib
import io
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import explore_hoshibiyori as ex  # noqa: E402

JST = timezone(timedelta(hours=9))
START = datetime(2026, 11, 20, 19, 0, tzinfo=JST)
END = datetime(2026, 11, 20, 23, 0, tzinfo=JST)   # 15分おきに17点
SITE = {"name": "テスト高原", "municipality": "テスト村", "origin": "curated", "lat": 35.5, "lon": 138.5,
        "elevation_m": 1000.0, "horizon_csv": None, "requires_lift_access": False}


class FakeTs:
    def from_datetime(self, dt):
        return dt


def altitude_fn(f):
    """時刻(START からの分)→ 高度 の関数から、altaz_at_time の代わりを作る。方位は 180°固定。"""
    def fake(t_sf, eph, lat, lon, elev, target):
        minutes = (t_sf - START.astimezone(timezone.utc)).total_seconds() / 60.0
        return 180.0, f(minutes)
    return fake


def window(f, profile=None):
    with mock.patch.object(ex, "altaz_at_time", altitude_fn(f)):
        return ex.compute_target_window(FakeTs(), None, SITE, object(), START, END, profile)


class FakeLp:
    alr_threshold = 10.66

    def get(self, lat, lon):
        return SimpleNamespace(brightness_ratio=ex.LP_INDEX_LIMIT * 0.2, alr=2.0, rank_pct=20.0)


def survivor(site):
    return {"night": SimpleNamespace(night_date=START.date()), "site": site, "window_start": START, "window_end": END,
            "moon_free_hours": 4.0, "mean_obstruction": 10.0, "clear_hours": 4.0}


def stage3(f, sites, mode="milkyway", profiles=None):
    out = io.StringIO()
    with mock.patch.object(ex, "altaz_at_time", altitude_fn(f)), \
            mock.patch.object(ex, "get_target", lambda tid: SimpleNamespace(name="天の川銀河中心")), \
            mock.patch.object(ex, "load_horizon_profile", lambda p: (profiles or {})[p]), \
            contextlib.redirect_stdout(out):
        finals = ex.stage3_direction_filter(FakeTs(), None, [survivor(s) for s in sites], FakeLp(), mode)
    return finals, out.getvalue()


class ComputeTargetWindowNoTerrainTests(unittest.TestCase):
    def test_below_zero_all_night_is_not_visible(self):
        self.assertEqual(window(lambda m: -5.0 + m / 100.0), (None, None, None, None, None))
        self.assertEqual(window(lambda m: 0.0), (None, None, None, None, None))   # ちょうど0°は見えない

    def test_rises_above_zero_midway(self):
        # 20:30(90分)に0°を超える(90分では0.0、105分から正)
        start, end, peak_t, peak_az, peak_alt = window(lambda m: (m - 90.0) / 10.0)
        self.assertEqual(start, START + timedelta(minutes=105))
        self.assertEqual(end, END)
        self.assertEqual(peak_t, END)
        self.assertAlmostEqual(peak_alt, 15.0)

    def test_above_zero_all_night_same_as_before(self):
        start, end, peak_t, peak_az, peak_alt = window(lambda m: 10.0 + m / 60.0)
        self.assertEqual((start, end), (START, END))
        self.assertEqual(peak_t, END)
        self.assertAlmostEqual(peak_alt, 14.0)
        self.assertEqual(peak_az, 180.0)

    def test_with_terrain_unchanged(self):
        # 地形あり(稜線5°): 5°を超えている区間だけ。0°の判定は使わない
        profile = {az: 5.0 for az in range(360)}
        start, end, _, _, _ = window(lambda m: (m - 90.0) / 10.0, profile)
        self.assertEqual(start, START + timedelta(minutes=150))   # (150-90)/10 = 6.0 > 5
        self.assertEqual(end, END)
        # 地形あり・稜線が負(海の見える岬など)なら、0°未満でも見える(従来どおり)
        low = {az: -2.0 for az in range(360)}
        self.assertEqual(window(lambda m: -1.0, low)[:2], (START, END))


class Stage3NoTerrainTests(unittest.TestCase):
    def test_no_terrain_below_zero_dropped(self):
        finals, out = stage3(lambda m: -3.0, [SITE])
        self.assertEqual(finals, [])
        self.assertIn("うち地形データなし(地平線を高度0°として判定して通過): 0件", out)

    def test_no_terrain_above_zero_kept(self):
        finals, out = stage3(lambda m: -3.0 + m / 30.0, [SITE])   # 最高 5.0°
        self.assertEqual(len(finals), 1)
        f = finals[0]
        self.assertFalse(f.terrain_available)
        self.assertIsNone(f.horizon_alt)        # 0 を入れない
        self.assertAlmostEqual(f.target_alt, 5.0)
        self.assertIn("うち地形データなし(地平線を高度0°として判定して通過): 1件", out)
        # スコア式は従来どおり(h_alt が None なら 0 として高度の項を足す)
        self.assertAlmostEqual(f.score, (100.0 - 10.0) + 5.0 * 0.5 + 4.0 * 3.0 - ex.LP_INDEX_LIMIT * 0.2 * 10.0)

    def test_with_terrain_unchanged(self):
        site = dict(SITE, horizon_csv="ridge.csv")
        profiles = {"ridge.csv": {az: 6.0 for az in range(360)}}
        self.assertEqual(stage3(lambda m: 5.0, [site], profiles=profiles)[0], [])
        kept = stage3(lambda m: 7.0, [site], profiles=profiles)[0]
        self.assertEqual(len(kept), 1)
        self.assertTrue(kept[0].terrain_available)
        self.assertEqual(kept[0].horizon_alt, 6.0)

    def test_stars_mode_unchanged(self):
        # 星空・星座モードは銀河中心を評価しない(高度が負でも残る。altaz_at_time は呼ばれない)
        with mock.patch.object(ex, "altaz_at_time", side_effect=AssertionError("呼ばない")), \
                contextlib.redirect_stdout(io.StringIO()):
            finals = ex.stage3_direction_filter(FakeTs(), None, [survivor(SITE)], FakeLp(), "stars")
        self.assertEqual(len(finals), 1)
        self.assertIsNone(finals[0].target_alt)


class OutlookNoTerrainTests(unittest.TestCase):
    def run_outlook(self, f, mode="milkyway"):
        night = SimpleNamespace(night_date=START.date())
        with mock.patch.object(ex, "altaz_at_time", altitude_fn(f)), \
                mock.patch.object(ex, "get_target", lambda tid: SimpleNamespace(name="天の川銀河中心")), \
                mock.patch.object(ex, "compute_site_night_window", return_value=(START, END, 4.0)), \
                mock.patch.object(ex, "get_level_cloud_forecast", return_value=[]), \
                mock.patch.object(ex, "hourly_sky_obstruction_and_cloud_sea", return_value=[]), \
                contextlib.redirect_stdout(io.StringIO()):
            return ex.stage_outlook(FakeTs(), None, [night], [SITE], FakeLp(), cache=None, target_mode=mode)

    def test_outlook_below_zero_not_candidate(self):
        self.assertEqual(self.run_outlook(lambda m: -10.0), [])

    def test_outlook_above_zero_candidate(self):
        res = self.run_outlook(lambda m: (m - 90.0) / 10.0)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0].visible_start, START + timedelta(minutes=105))
        self.assertFalse(res[0].terrain_available)
        self.assertIsNone(res[0].horizon_alt)

    def test_outlook_stars_mode_unchanged(self):
        res = self.run_outlook(None, "stars")   # altaz_at_time は呼ばれない
        self.assertEqual(len(res), 1)
        self.assertEqual((res[0].visible_start, res[0].visible_end), (START, END))


class CandidateLineNoteTests(unittest.TestCase):
    """各候補の行の地形の注記(天の川モードだけ)。地形データが無ければ「地平線を高度0°として判定」と書く。"""
    TARGET = SimpleNamespace(name="天の川銀河中心")

    def final(self, terrain):
        return ex.FinalCandidate(
            night_date=START.date(), site_name="テスト高原", municipality="テスト村", origin="curated",
            site_lat=35.5, site_lon=138.5, requires_lift_access=False, window_start=START, window_end=END,
            best_time=START, target_az=180.0, target_alt=12.0, horizon_alt=(5.0 if terrain else None),
            terrain_available=terrain, mean_obstruction=10.0, lp_index=1.0, moon_free_hours=4.0,
            clear_hours=4.0, score=100.0)

    def outlook(self, terrain):
        return ex.OutlookCandidate(
            night_date=START.date(), site_name="テスト高原", municipality="テスト村", origin="curated",
            site_lat=35.5, site_lon=138.5, requires_lift_access=False, visible_start=START, visible_end=END,
            target_az=180.0, target_alt=12.0, horizon_alt=(5.0 if terrain else None), terrain_available=terrain,
            lp_index=1.0, clear_sky_pct=50.0, moon_free_hours=4.0, score=100.0)

    def printed(self, fn, items, mode):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            fn(items, self.TARGET, 10, mode)
        return out.getvalue()

    def test_milkyway_no_terrain_note(self):
        for fn, make in ((ex._print_final_items, self.final), (ex._print_outlook_items, self.outlook)):
            out = self.printed(fn, [make(False)], "milkyway")
            self.assertIn("地形データなし(地平線を高度0°として判定)", out)
            self.assertNotIn("地形データなし(未評価)", out)

    def test_milkyway_with_terrain_unchanged(self):
        out = self.printed(ex._print_final_items, [self.final(True)], "milkyway")
        self.assertIn("地形地平線 5.0°を7.0°上回る", out)
        out = self.printed(ex._print_outlook_items, [self.outlook(True)], "milkyway")
        self.assertIn("地形地平線5.0°を7.0°上回る", out)

    def test_stars_mode_has_no_terrain_note(self):
        for fn, make in ((ex._print_final_items, self.final), (ex._print_outlook_items, self.outlook)):
            out = self.printed(fn, [make(False)], "stars")
            self.assertNotIn("地形データなし", out)
            self.assertNotIn("地形地平線", out)


if __name__ == "__main__":
    unittest.main()
