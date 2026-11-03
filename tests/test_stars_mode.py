"""星空・星座モード(--target stars)の単体テスト(通信しない)。

stage3_direction_filter に合成の「雲フィルタ通過済み」データと偽の光害ストアを渡し、
  - milkyway(既定): 従来どおり銀河中心が地形地平線を上回る組だけが残る
  - stars: 銀河中心が地平線下でも、光害が基準内なら残る。夜景系(ALR超過)は残らない
  - 順位: 晴れ時間 → 平均雲量 → ALR → 月の影響が小さい時間
を確認する。天文計算は step1_astronomy/de421.bsp が無い環境ではスキップする。
"""
import contextlib
import csv
import io
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import explore_hoshibiyori as ex  # noqa: E402

JST = timezone(timedelta(hours=9))
BSP = ROOT / "step1_astronomy" / "de421.bsp"


class FakeLpStore:
    alr_threshold = 10.66
    """名前の代わりに緯度で光害を決める偽ストア(lat==36.0 の地点だけ夜景系=基準超過)。"""

    def get(self, lat, lon):
        if lat == 36.0:
            return SimpleNamespace(brightness_ratio=ex.LP_INDEX_LIMIT * 2, alr=30.0, rank_pct=95.0)
        return SimpleNamespace(brightness_ratio=ex.LP_INDEX_LIMIT * 0.2, alr=2.0, rank_pct=20.0)


def flat_horizon_csv(directory: Path) -> str:
    path = directory / "flat0.csv"
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["azimuth_deg", "horizon_altitude_deg"])
        for az in range(360):
            w.writerow([az, 0.0])
    return str(path)


def make_survivor(name, lat, window_start, window_end, horizon_csv, clear_hours=5.0, obstruction=10.0,
                  moon_free_hours=6.0):
    night = SimpleNamespace(night_date=window_start.date())
    site = {"name": name, "municipality": "テスト市", "origin": "curated", "lat": lat, "lon": 139.0,
            "elevation_m": 100.0, "horizon_csv": horizon_csv, "requires_lift_access": False}
    return {"night": night, "site": site, "window_start": window_start, "window_end": window_end,
            "moon_free_hours": moon_free_hours, "mean_obstruction": obstruction, "clear_hours": clear_hours}


@unittest.skipUnless(BSP.exists(), "de421.bsp が無い環境では天文計算のテストをスキップ")
class StageThreeModeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from skyfield.api import load
        cls.ts = load.timescale()
        cls.eph = load(str(BSP))
        cls.tmp = tempfile.TemporaryDirectory()
        cls.csv = flat_horizon_csv(Path(cls.tmp.name))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def run_stage3(self, survivors, mode=None):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            if mode is None:
                return ex.stage3_direction_filter(self.ts, self.eph, survivors, FakeLpStore())
            return ex.stage3_direction_filter(self.ts, self.eph, survivors, FakeLpStore(), mode)

    def winter_evening(self, **kw):
        # 11月上旬の夜。銀河中心は宵のうちに沈んでおり、地平線(0°)を上回らない
        return make_survivor("冬の暗い高原", 35.5, datetime(2026, 11, 2, 21, 0, tzinfo=JST),
                             datetime(2026, 11, 2, 23, 0, tzinfo=JST), self.csv, **kw)

    def summer_night(self, name="夏の暗い高原", lat=35.5, **kw):
        # 7月中旬の深夜。銀河中心が空に上がる
        return make_survivor(name, lat, datetime(2026, 7, 15, 23, 0, tzinfo=JST),
                             datetime(2026, 7, 16, 1, 0, tzinfo=JST), self.csv, **kw)

    def test_default_is_milkyway(self):
        surv = [self.winter_evening(), self.summer_night()]
        default = self.run_stage3(surv)
        explicit = self.run_stage3(surv, "milkyway")
        self.assertEqual([(f.site_name, f.night_date, f.score) for f in default],
                         [(f.site_name, f.night_date, f.score) for f in explicit])

    def test_milkyway_drops_galactic_center_below_horizon(self):
        finals = self.run_stage3([self.winter_evening(), self.summer_night()], "milkyway")
        self.assertEqual([f.site_name for f in finals], ["夏の暗い高原"])
        f = finals[0]
        self.assertIsNotNone(f.target_alt)
        self.assertGreater(f.target_alt, f.horizon_alt)
        self.assertGreater(f.score, 0)

    def test_stars_keeps_galactic_center_below_horizon(self):
        finals = self.run_stage3([self.winter_evening(), self.summer_night()], "stars")
        self.assertEqual(sorted(f.site_name for f in finals), ["冬の暗い高原", "夏の暗い高原"])
        for f in finals:
            self.assertIsNone(f.target_alt)
            self.assertIsNone(f.target_az)
            self.assertFalse(f.terrain_available)

    def test_stars_still_excludes_night_view_sites(self):
        # lat==36.0 はALRが基準超過(夜景系)。どちらのモードでも残らない
        surv = [self.winter_evening(), make_survivor("夜景の高台", 36.0, datetime(2026, 11, 2, 21, 0, tzinfo=JST),
                                                     datetime(2026, 11, 2, 23, 0, tzinfo=JST), self.csv)]
        for mode in ("milkyway", "stars"):
            names = [f.site_name for f in self.run_stage3(surv, mode)]
            self.assertNotIn("夜景の高台", names, mode)
        self.assertIn("冬の暗い高原", [f.site_name for f in self.run_stage3(surv, "stars")])

    def test_stars_ignores_terrain_horizon(self):
        # 地形が全方位で高い稜線(80°)でも、starsでは地形で落とさない
        path = Path(self.tmp.name) / "wall80.csv"
        with open(path, "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["azimuth_deg", "horizon_altitude_deg"])
            for az in range(360):
                w.writerow([az, 80.0])
        surv = [self.summer_night(name="谷底")]
        surv[0]["site"]["horizon_csv"] = str(path)
        self.assertEqual(self.run_stage3(surv, "milkyway"), [])
        self.assertEqual([f.site_name for f in self.run_stage3(surv, "stars")], ["谷底"])


class RankKeyTests(unittest.TestCase):
    def fin(self, name, clear, obstruction, alr, moon):
        return SimpleNamespace(site_name=name, clear_hours=clear, mean_obstruction=obstruction, alr=alr,
                               lp_index=1.0, moon_free_hours=moon, score=0.0)

    def order(self, items):
        return [f.site_name for f in sorted(items, key=lambda f: ex.final_rank_key(f, "stars"), reverse=True)]

    def test_clear_hours_first(self):
        a = self.fin("a", 6.0, 30.0, 9.0, 1.0)
        b = self.fin("b", 5.0, 0.0, 1.0, 9.0)
        self.assertEqual(self.order([b, a]), ["a", "b"])

    def test_then_alr_then_moon_then_cloud(self):
        # 同じ晴れ時間・雲量の中では ALR が小さい方、さらに同じなら月の影響が小さい時間が長い方
        same_cloud = [self.fin("p", 5.0, 10.0, 5.0, 5.0), self.fin("a", 5.0, 10.0, 2.0, 5.0),
                      self.fin("m", 5.0, 10.0, 5.0, 8.0)]
        self.assertEqual(self.order(same_cloud), ["a", "m", "p"])
        # 同じ晴れ時間なら雲量が低い方が先
        self.assertEqual(self.order([self.fin("hi", 5.0, 20.0, 1.0, 9.0), self.fin("lo", 5.0, 10.0, 9.0, 1.0)]),
                         ["lo", "hi"])

    def test_milkyway_key_is_score(self):
        a = SimpleNamespace(score=10.0)
        b = SimpleNamespace(score=20.0)
        self.assertEqual(sorted([a, b], key=lambda f: ex.final_rank_key(f), reverse=True), [b, a])


class CliTests(unittest.TestCase):
    def test_target_option(self):
        self.assertEqual(ex.parse_args([]).target, "milkyway")
        self.assertEqual(ex.parse_args(["--target", "stars"]).target, "stars")
        import generate_report as gr
        self.assertEqual(gr.parse_args([]).target, "milkyway")
        self.assertEqual(gr.parse_args(["--target", "stars"]).target, "stars")
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            gr.parse_args(["--target", "bogus"])

    def test_sky_guide_core_excluded_in_stars(self):
        import generate_report as gr
        with_core = [t.id if hasattr(t, "id") else t.name for t, _ in gr.select_seasonal_targets(11)]
        without = [t.id if hasattr(t, "id") else t.name for t, _ in gr.select_seasonal_targets(11, include_core=False)]
        self.assertEqual(len(without), len(with_core) - 1)
        self.assertNotIn(with_core[0], without)


if __name__ == "__main__":
    unittest.main()
