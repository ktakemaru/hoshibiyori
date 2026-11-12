"""薄明・月の時刻の格子化と保存(astro_grid_cache.py、2026-11-13)の単体テスト(通信しない)。

計算の関数は偽物を差し込み、天体暦なしで動く。実際の天文計算との一致は de421.bsp がある環境だけで確かめる。
"""
import json
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from datetime import date, datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import explore_hoshibiyori as ex  # noqa: E402
import generate_report as gr  # noqa: E402
import astro_grid_cache as agc  # noqa: E402

JST = timezone(timedelta(hours=9))
BSP = ROOT / "step1_astronomy" / "de421.bsp"


class FakeAstro:
    """座標と日付から決まる値を返す偽の計算。呼ばれた座標を記録する。"""

    def __init__(self):
        self.dark_calls = []
        self.moon_calls = []
        self.ref_calls = []

    def dark(self, ts, eph, lat, lon, day_start_local):
        self.dark_calls.append((lat, lon, day_start_local.date()))
        base = day_start_local + timedelta(hours=18, minutes=int(lat * 10) % 60, microseconds=123456)
        return base, base + timedelta(hours=10, seconds=int(lon * 100) % 60)

    def moon(self, ts, eph, lat, lon, start, end):
        self.moon_calls.append((lat, lon, start))
        return start, end - timedelta(minutes=30), (end - start).total_seconds() / 3600.0 - 0.5

    def ref(self, ts, eph, lat, lon, day):
        self.ref_calls.append((lat, lon, day.date()))
        return {"sunset": day + timedelta(hours=16, minutes=40), "sunrise": day + timedelta(hours=30, minutes=10),
                "dark_start": day + timedelta(hours=18), "dark_end": day + timedelta(hours=28, minutes=50),
                "window_start": day + timedelta(hours=18), "window_end": day + timedelta(hours=27), "hours": 9.0}


COND = agc.make_conditions(moon_phase_negligible_deg=150.0, sample_interval_min=15, ephemeris="de421.bsp")


class AstroGridCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="hb_astro_test_"))
        self.fake = FakeAstro()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def make(self, conditions=COND, disk=True, today=date(2026, 11, 13), fake=None):
        f = fake or self.fake
        return agc.AstroNightCache(dark_fn=f.dark, moon_fn=f.moon, ref_fn=f.ref, conditions=conditions,
                                   cache_dir=self.tmp, disk_cache=disk, today=today)

    def test_same_cell_shares_result(self):
        c = self.make()
        a = c.site_night_window(None, None, {"lat": 35.01, "lon": 139.02}, date(2026, 11, 20))
        b = c.site_night_window(None, None, {"lat": 34.95, "lon": 138.90}, date(2026, 11, 20))
        self.assertEqual(a, b)
        self.assertEqual(len(self.fake.dark_calls), 1)
        # 代表点はECMWFの格子(grid_cache.grid_cell)と同じ
        self.assertEqual(self.fake.dark_calls[0][:2], agc.grid_cell(35.01, 139.02, agc.ECMWF_MODEL))
        self.assertEqual(c.computed, 1)

    def test_other_cell_or_night_not_mixed(self):
        c = self.make()
        a = c.site_night_window(None, None, {"lat": 35.0, "lon": 139.0}, date(2026, 11, 20))
        b = c.site_night_window(None, None, {"lat": 36.0, "lon": 139.0}, date(2026, 11, 20))
        d = c.site_night_window(None, None, {"lat": 35.0, "lon": 139.0}, date(2026, 11, 21))
        self.assertNotEqual(a, b)
        self.assertNotEqual(a, d)
        self.assertEqual(len(self.fake.dark_calls), 3)

    def test_roundtrip_equal(self):
        c = self.make()
        sites = [{"lat": 35.0, "lon": 139.0}, {"lat": 36.3, "lon": 138.2}]
        want = [c.site_night_window(None, None, s, date(2026, 11, 20)) for s in sites]
        ref_want = c.reference_night(None, None, 34.6, 138.85, datetime(2026, 11, 20, tzinfo=JST))
        self.assertEqual(c.flush(), 1)
        fake2 = FakeAstro()
        c2 = self.make(fake=fake2)
        got = [c2.site_night_window(None, None, s, date(2026, 11, 20)) for s in sites]
        ref_got = c2.reference_night(None, None, 34.6, 138.85, datetime(2026, 11, 20, tzinfo=JST))
        self.assertEqual(got, want)
        self.assertEqual([repr(x) for x in got], [repr(x) for x in want])
        self.assertEqual(ref_got, ref_want)
        self.assertEqual(fake2.dark_calls, [])
        self.assertEqual(fake2.ref_calls, [])
        self.assertEqual((c2.computed, c2.from_disk), (0, 3))
        for v in got[0][:2]:
            self.assertIsNotNone(v.tzinfo)

    def test_none_window_roundtrip(self):
        fake = FakeAstro()
        fake.dark = lambda ts, eph, lat, lon, d: (None, None)
        c = self.make(fake=fake)
        self.assertEqual(c.site_night_window(None, None, {"lat": 35.0, "lon": 139.0}, date(2026, 11, 20)), (None, None, 0.0))
        c.flush()
        c2 = self.make()
        self.assertEqual(c2.site_night_window(None, None, {"lat": 35.0, "lon": 139.0}, date(2026, 11, 20)), (None, None, 0.0))
        self.assertEqual(self.fake.dark_calls, [])

    def test_different_conditions_not_used(self):
        c = self.make()
        c.site_night_window(None, None, {"lat": 35.0, "lon": 139.0}, date(2026, 11, 20))
        c.flush()
        for changed in (
            agc.make_conditions(moon_phase_negligible_deg=140.0, sample_interval_min=15, ephemeris="de421.bsp"),
            agc.make_conditions(moon_phase_negligible_deg=150.0, sample_interval_min=10, ephemeris="de421.bsp"),
            agc.make_conditions(moon_phase_negligible_deg=150.0, sample_interval_min=15, ephemeris="de440s.bsp"),
            {**COND, "format_version": 999},
            {**COND, "grid": {**COND["grid"], "lat_step": 0.1}},
        ):
            fake = FakeAstro()
            c2 = self.make(conditions=changed, fake=fake)
            c2.site_night_window(None, None, {"lat": 35.0, "lon": 139.0}, date(2026, 11, 20))
            self.assertEqual(len(fake.dark_calls), 1, changed)

    def test_conditions_inside_file_checked(self):
        # フォルダ名が同じでも、ファイルの中の条件が違えば使わない
        c = self.make()
        c.site_night_window(None, None, {"lat": 35.0, "lon": 139.0}, date(2026, 11, 20))
        c.flush()
        path = c._path(date(2026, 11, 20))
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["conditions"]["sample_interval_min"] = 5
        path.write_text(json.dumps(raw), encoding="utf-8")
        fake = FakeAstro()
        c2 = self.make(fake=fake)
        c2.site_night_window(None, None, {"lat": 35.0, "lon": 139.0}, date(2026, 11, 20))
        self.assertEqual(len(fake.dark_calls), 1)

    def test_broken_file_is_ignored(self):
        c = self.make()
        c.dir.mkdir(parents=True)
        for i, text in enumerate(["{not json", json.dumps({"schema": agc.SCHEMA, "conditions": COND,
                                                           "night_date": "2026-11-21", "cells": {"x": {"dark_start": 1}}}),
                                  json.dumps([1, 2])]):
            d = date(2026, 11, 20 + i)
            c._path(d).write_text(text, encoding="utf-8")
        fake = FakeAstro()
        c2 = self.make(fake=fake)
        for i in range(3):
            c2.site_night_window(None, None, {"lat": 35.0, "lon": 139.0}, date(2026, 11, 20 + i))
        self.assertEqual(len(fake.dark_calls), 3)
        self.assertEqual(c2.ignored_files, 3)
        c2.flush()  # 壊れたファイルは正しい内容で置き換わる
        c3 = self.make(fake=FakeAstro())
        for i in range(3):
            c3.site_night_window(None, None, {"lat": 35.0, "lon": 139.0}, date(2026, 11, 20 + i))
        self.assertEqual(c3.computed, 0)

    def test_old_nights_pruned(self):
        c = self.make(today=date(2026, 11, 1))
        for d in (date(2026, 11, 1), date(2026, 11, 6), date(2026, 11, 7)):
            c.site_night_window(None, None, {"lat": 35.0, "lon": 139.0}, d)
        c.flush()
        other = self.tmp / "unrelated.json"
        other.write_text("{}", encoding="utf-8")
        c.dir.joinpath("notes.txt").write_text("x", encoding="utf-8")
        c2 = self.make(today=date(2026, 11, 13))  # 7日より前 = 11/6 より前
        names = sorted(p.name for p in c2.dir.iterdir())
        self.assertEqual(names, ["night_2026-11-06.json", "night_2026-11-07.json", "notes.txt"])
        self.assertEqual(c2.pruned, 1)
        self.assertTrue(other.exists())

    def test_no_disk_mode_does_not_write(self):
        c = self.make(disk=False)
        c.site_night_window(None, None, {"lat": 35.0, "lon": 139.0}, date(2026, 11, 20))
        self.assertEqual(c.flush(), 0)
        self.assertFalse(c.dir.exists())

    def test_atomic_write_leaves_no_temp(self):
        c = self.make()
        c.site_night_window(None, None, {"lat": 35.0, "lon": 139.0}, date(2026, 11, 20))
        c.flush()
        self.assertEqual([p.name for p in c.dir.iterdir()], ["night_2026-11-20.json"])

    def test_merge_with_other_run(self):
        a = self.make()
        a.site_night_window(None, None, {"lat": 35.0, "lon": 139.0}, date(2026, 11, 20))
        b = self.make(fake=FakeAstro())
        b.site_night_window(None, None, {"lat": 36.0, "lon": 139.0}, date(2026, 11, 20))
        a.flush()
        b.flush()
        c = self.make(fake=FakeAstro())
        c.site_night_window(None, None, {"lat": 35.0, "lon": 139.0}, date(2026, 11, 20))
        c.site_night_window(None, None, {"lat": 36.0, "lon": 139.0}, date(2026, 11, 20))
        self.assertEqual(c.computed, 0)

    def test_unregistered_coordinates(self):
        c = self.make()
        w = c.site_night_window(None, None, {"lat": 43.06, "lon": 141.35}, date(2026, 11, 20))  # 登録外(札幌付近)
        self.assertIsNotNone(w[0])
        self.assertEqual(self.fake.dark_calls[0][:2], (43.0, 141.25))

    def test_lines(self):
        c = self.make()
        sites = [{"lat": 35.0, "lon": 139.0}, {"lat": 35.05, "lon": 139.05}, {"lat": 36.0, "lon": 139.0}]
        self.assertEqual(c.start_line(sites), "[天文計算] 薄明・月の時刻は0.25度格子の代表点で計算(3地点 → 2セル)")
        self.assertTrue(c.summary_line().startswith("天文計算のキャッシュ: 計算 0 件 / 保存済みを使用 0 件"))


class ExploreWiringTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="hb_astro_test_"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_argument_default_and_bad_value(self):
        for parse in (ex.parse_args, gr.parse_args):
            self.assertEqual(parse([]).astro_grid, "ecmwf")
            self.assertEqual(parse(["--astro-grid", "site"]).astro_grid, "site")
            with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
                parse(["--astro-grid", "bogus"])

    def test_make_astro_cache(self):
        self.assertIsNone(ex.make_astro_cache("site"))
        c = ex.make_astro_cache("ecmwf", cache_dir=self.tmp)
        self.assertIsInstance(c, agc.AstroNightCache)
        self.assertEqual(c.conditions["sample_interval_min"], ex.MOON_SAMPLE_INTERVAL_MIN)
        self.assertEqual(c.conditions["moon_phase_negligible_deg"], ex.MOON_PHASE_NEGLIGIBLE_DEG)
        self.assertEqual(c.conditions["ephemeris"], ex.EPHEMERIS_FILE)
        with self.assertRaises(ValueError):
            ex.make_astro_cache("bogus")

    def test_site_mode_never_touches_cache(self):
        # site(astro=None)では保存の読み書きをしない: AstroNightCache のどのメソッドも呼ばれない
        with mock.patch.object(agc.AstroNightCache, "_read", side_effect=AssertionError("read")), \
                mock.patch.object(agc.AstroNightCache, "flush", side_effect=AssertionError("flush")), \
                mock.patch.object(ex, "find_astro_dark_events", return_value=(None, None)) as dark, \
                mock.patch.object(ex, "find_sun_events", return_value=(None, None)), \
                mock.patch("builtins.print"):
            self.assertEqual(ex.compute_site_night_window(None, None, {"lat": 35.0, "lon": 139.0}, date(2026, 11, 20)),
                             (None, None, 0.0))
            ex.finish_astro_cache(None)
            ex.stage1_moon_filter(None, None, 34.6, 138.85)
        dark.assert_called_once()

    def test_stage_functions_pass_astro(self):
        fake = FakeAstro()
        astro = agc.AstroNightCache(dark_fn=fake.dark, moon_fn=fake.moon, ref_fn=fake.ref, conditions=COND,
                                    cache_dir=self.tmp, disk_cache=False)
        night = ex.NightCandidate(date(2026, 11, 20), None, None, None, None, None, None, 0.0)
        sites = [{"name": "a", "lat": 35.0, "lon": 139.0, "elevation_m": 0.0},
                 {"name": "b", "lat": 35.05, "lon": 139.05, "elevation_m": 0.0}]
        with mock.patch.object(ex, "get_level_cloud_forecast", return_value=[]), \
                mock.patch.object(ex, "find_astro_dark_events", side_effect=AssertionError("地点ごとの計算")), \
                mock.patch("builtins.print"):
            ex.stage2_cloud_filter(None, None, [night], sites, cache=mock.Mock(call_count=0, cache_hit_count=0),
                                   astro=astro)
            with mock.patch.object(gr, "get_level_cloud_forecast", return_value=[]):
                gr.build_casual_weather_note(None, None, sites, [night], cache=None, astro=astro)
        self.assertEqual(len(fake.dark_calls), 1)  # 2地点・2回の呼び出しでセルの計算は1回
        self.assertEqual(astro.lookups, 4)

    def test_reference_night_uses_cache(self):
        fake = FakeAstro()
        astro = agc.AstroNightCache(dark_fn=fake.dark, moon_fn=fake.moon, ref_fn=fake.ref, conditions=COND,
                                    cache_dir=self.tmp, disk_cache=True)
        with redirect_stderr(StringIO()), mock.patch("builtins.print"):
            n1 = ex.stage1_moon_filter(None, None, 34.6, 138.85, astro)
            t1 = ex.all_nights_timeline(None, None, 34.6, 138.85, astro=astro)
        self.assertEqual(len(fake.ref_calls), ex.NUM_NIGHTS_TO_SCAN)  # 同じ夜は1回だけ計算
        self.assertEqual(fake.ref_calls[0][:2], (34.6, 138.85))     # 基準地点は格子に丸めない
        astro.flush()
        fake2 = FakeAstro()
        astro2 = agc.AstroNightCache(dark_fn=fake2.dark, moon_fn=fake2.moon, ref_fn=fake2.ref, conditions=COND,
                                     cache_dir=self.tmp, disk_cache=True)
        with mock.patch("builtins.print"):
            n2 = ex.stage1_moon_filter(None, None, 34.6, 138.85, astro2)
            t2 = ex.all_nights_timeline(None, None, 34.6, 138.85, astro=astro2)
        self.assertEqual(fake2.ref_calls, [])
        self.assertEqual(n1, n2)
        self.assertEqual(t1, t2)


@unittest.skipUnless(BSP.exists(), "de421.bsp が無い環境では天文計算のテストをスキップ")
class RealAstroTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ts = ex.load.timescale()
        cls.eph = ex.load(str(BSP))

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="hb_astro_test_"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_grid_equals_site_calc_at_cell_point(self):
        site = {"lat": 36.80, "lon": 139.42}
        d = date(2026, 11, 20)
        cell = agc.grid_cell(site["lat"], site["lon"], agc.ECMWF_MODEL)
        astro = ex.make_astro_cache("ecmwf", cache_dir=self.tmp)
        got = ex.compute_site_night_window(self.ts, self.eph, site, d, astro)
        want = ex.compute_site_night_window(self.ts, self.eph, {"lat": cell[0], "lon": cell[1]}, d)
        self.assertEqual(got, want)
        astro.flush()
        again = ex.compute_site_night_window(self.ts, self.eph, site, d, ex.make_astro_cache("ecmwf", cache_dir=self.tmp))
        self.assertEqual(repr(again), repr(want))

    def test_warm_command(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("warm_astro_cache", ROOT / "scripts" / "warm_astro_cache.py")
        warm = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(warm)
        sites = [{"name": "石廊崎", "lat": 34.60, "lon": 138.85}, {"name": "x", "lat": 34.62, "lon": 138.80},
                 {"name": "y", "lat": 36.80, "lon": 139.42}]
        lines = []

        class Stop(Exception):
            pass

        def out_stop(s):
            lines.append(s)
            if "(1/2夜)" in s:
                raise Stop  # 1夜目を書き出したあとで止める

        with self.assertRaises(Stop):
            warm.warm(2, start=date(2026, 11, 20), cache_dir=self.tmp, ts=self.ts, eph=self.eph, sites=sites, out=out_stop)
        files = sorted(p.name for p in next(self.tmp.iterdir()).iterdir())
        self.assertEqual(files, ["night_2026-11-20.json"])  # 止めても1夜目は保存済み
        c, r = warm.warm(2, start=date(2026, 11, 20), cache_dir=self.tmp, ts=self.ts, eph=self.eph, sites=sites,
                         out=lambda s: None)
        self.assertEqual((c, r), (3, 3))  # 2セル+基準地点 × 1夜目は保存済み、2夜目は計算
        astro = ex.make_astro_cache("ecmwf", cache_dir=self.tmp)
        got = ex.compute_site_night_window(self.ts, self.eph, sites[2], date(2026, 11, 21), astro)
        self.assertEqual(astro.computed, 0)
        self.assertEqual(got, ex.compute_site_night_window(self.ts, self.eph, {"lat": 36.75, "lon": 139.5}, date(2026, 11, 21)))

    def test_reference_night_same_as_before(self):
        day = datetime(2026, 11, 20, tzinfo=JST)
        r = ex.reference_night(self.ts, self.eph, 34.60, 138.85, day)
        self.assertEqual((r["sunset"], r["sunrise"]), ex.find_sun_events(self.ts, self.eph, 34.60, 138.85, day))
        self.assertEqual((r["dark_start"], r["dark_end"]), ex.find_astro_dark_events(self.ts, self.eph, 34.60, 138.85, day))
        self.assertEqual((r["window_start"], r["window_end"], r["hours"]),
                         ex.longest_negligible_window(self.ts, self.eph, 34.60, 138.85, r["dark_start"], r["dark_end"]))


if __name__ == "__main__":
    unittest.main()
