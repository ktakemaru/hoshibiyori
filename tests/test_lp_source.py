"""光害の入力(Black Marble由来のALR、lp_source.py)の単体テスト。合成データのみ・通信しない。

段階LP2で legacy(以前の光害データ)との切り替えとして作り、段階LP3bで ALR だけの形に直した。
"""
from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
for sub in ("", "scripts", "step1_astronomy", "step2_terrain", "step3_light_pollution", "step4_moonlight", "step5_cloud_forecast"):
    sys.path.insert(0, str(ROOT / sub) if sub else str(ROOT))

import bm_threshold as bt  # noqa: E402
import explore_hoshibiyori as ex  # noqa: E402
import generate_report as gr  # noqa: E402
import lp_source as lp  # noqa: E402
import skyglow_bm as sg  # noqa: E402

JST = timezone(timedelta(hours=9))
D = date(2026, 10, 17)


def synthetic_grid() -> sg.DerivedGrid:
    """緯度 36.0..35.0 / 経度 138.0..139.0。ALRは経度とともに 0..20 に増える。"""
    a = np.tile(np.linspace(0.0, 20.0, 101), (101, 1))
    return sg.DerivedGrid(a, 36.0, 138.0, 0.01, {})


def lon_for_alr(alr: float) -> float:
    return 138.0 + alr / 20.0


class ThresholdTests(unittest.TestCase):
    def test_threshold_for_count_is_midpoint_and_reproduces_count(self):
        alr = np.array([5.0, 1.0, 9.0, 3.0, 7.0])
        t = bt.threshold_for_count(alr, 3)
        self.assertEqual(t, 6.0)
        self.assertEqual(int((alr <= t).sum()), 3)

    def test_threshold_for_count_rejects_ties_and_bad_n(self):
        with self.assertRaises(ValueError):
            bt.threshold_for_count(np.array([1.0, 2.0, 2.0, 3.0]), 2)
        with self.assertRaises(ValueError):
            bt.threshold_for_count(np.array([1.0, 2.0]), 2)

    def test_constant_reproduces_pass_count_on_committed_data(self):
        """仮閾値が、決めたときの通過件数(N=141)をALRで通す(データが変わったら気づける)。"""
        _, alr = bt.load_pairs()
        n = lp.BM_THRESHOLD_N_PASS
        self.assertEqual(int((alr <= lp.BM_ALR_THRESHOLD).sum()), n)
        s = np.sort(alr)
        self.assertLess(s[n - 1], lp.BM_ALR_THRESHOLD)
        self.assertLess(lp.BM_ALR_THRESHOLD, s[n])


class BmStoreTests(unittest.TestCase):
    def setUp(self):
        self.store = lp.BmLightPollutionStore(grid=synthetic_grid(), reference=np.array([1.0, 2.0, 5.0, 10.0]),
                                              alr_threshold=10.0, index_limit=5.0)

    def test_threshold_test_in_explore_is_exactly_alr_threshold(self):
        for alr, passes in ((9.9, True), (10.0, True), (10.1, False), (0.5, True), (19.0, False)):
            r = self.store.get(35.5, lon_for_alr(alr))
            self.assertAlmostEqual(r.alr, alr, places=6)
            # 探索側の判定式そのまま(既定の LP_INDEX_LIMIT と同じ 5.0 で規格化した store)
            self.assertEqual(r.brightness_ratio <= ex.LP_INDEX_LIMIT + 1e-9, passes, alr)

    def test_default_store_matches_alr_threshold(self):
        store = lp.BmLightPollutionStore(grid=synthetic_grid(), reference=np.array([1.0]))
        self.assertAlmostEqual(store.scale * lp.BM_ALR_THRESHOLD, lp.LP_INDEX_LIMIT)

    def test_reading_has_only_alr_fields(self):
        import dataclasses
        self.assertEqual([f.name for f in dataclasses.fields(lp.BmReading)],
                         ["lat", "lon", "alr", "rank_pct", "brightness_ratio"])  # 等級・ボートル値は持たない

    def test_rank_pct_is_share_of_reference_at_or_below(self):
        self.assertEqual(self.store.get(35.5, lon_for_alr(0.5)).rank_pct, 0.0)
        self.assertEqual(self.store.get(35.5, lon_for_alr(2.2)).rank_pct, 50.0)
        self.assertEqual(self.store.get(35.5, lon_for_alr(15.0)).rank_pct, 100.0)

    def test_out_of_range_never_passes(self):
        r = self.store.get(50.0, 138.5)
        self.assertIsNone(r.alr)
        self.assertIsNone(r.rank_pct)
        self.assertEqual(r.brightness_ratio, float("inf"))
        self.assertGreater(r.brightness_ratio, ex.LP_INDEX_LIMIT)
        self.assertIsNone(self.store.site_type(50.0, 138.5))

    def test_site_type(self):
        self.assertEqual(self.store.site_type(35.5, lon_for_alr(3.0)), "dark_sky")
        self.assertEqual(self.store.site_type(35.5, lon_for_alr(12.0)), "night_view")

    def test_describe_alr(self):
        self.assertEqual(lp.describe_alr(None, None), "範囲外(未評価)")
        self.assertIn("ALR 2.50", lp.describe_alr(2.5, 40.0))
        self.assertIn("40%", lp.describe_alr(2.5, 40.0))
        self.assertNotIn("mag", lp.describe_alr(2.5, 40.0))


class SingleSourceTests(unittest.TestCase):
    """段階LP3b: ALRが唯一の方式。以前の光害データの切り替え・取得処理は無い。"""

    def test_no_lp_source_option(self):
        for parse in (ex.parse_args, gr.parse_args):
            with self.assertRaises(SystemExit):
                parse(["--lp-source", "bm"])
        self.assertIsInstance(ex.make_lp_store(), lp.BmLightPollutionStore)

    def test_old_modules_are_gone(self):
        for name in ("light_pollution", "legacy_ref"):
            self.assertIsNone(importlib.util.find_spec(name), name)
        self.assertFalse(hasattr(gr, "OUTPUT_PATH_LEGACY"))
        self.assertEqual(gr.OUTPUT_PATH.name, "report.html")

    def test_limit_text(self):
        self.assertIn("ALR", ex.lp_limit_text(lp.BmLightPollutionStore(grid=synthetic_grid(), reference=np.array([1.0]))))

    def test_committed_spots_have_only_known_fields(self):
        """現行の地点ファイルの各地点が、既知の項目だけを持つ(以前の光害データの値が戻っていない)。"""
        allowed = {
            "spots": {"id", "name", "prefecture", "municipality", "description", "nominatim_display_name", "lat", "lon",
                      "coordinate_source", "origin", "matched_candidate", "horizon_profile", "elevation_m", "site_type",
                      "requires_lift_access", "requires_lift_access_note"},
        }
        data = json.loads(sg.SPOTS_PATH.read_text(encoding="utf-8"))
        extra = {k for s in data["spots"] for k in s} - allowed["spots"]
        self.assertEqual(extra, set())
        bm = json.loads((sg.REPO_ROOT / "stargazing_spots.bm.json").read_text(encoding="utf-8"))
        self.assertEqual({k for s in bm["spots"] for k in s},
                         {"id", "name", "prefecture", "lat", "lon", "site_type", "skyglow_bm_index", "skyglow_bm_rank_pct"})

    def test_site_type_of_committed_spots_follows_alr_threshold(self):
        store = lp.BmLightPollutionStore()
        for s in json.loads(sg.SPOTS_PATH.read_text(encoding="utf-8"))["spots"]:
            self.assertEqual(s["site_type"], store.site_type(s["lat"], s["lon"]), s["name"])


def _card(alr=2.34, rank=41.0):
    return SimpleNamespace(
        site_name="テスト地点", municipality="市", score=100.0, origin="curated", site_lat=36.0, site_lon=138.5,
        window_start=datetime(2026, 10, 17, 21, 15, tzinfo=JST), window_end=datetime(2026, 10, 18, 4, 15, tzinfo=JST),
        best_time=datetime(2026, 10, 17, 23, tzinfo=JST), night_date=D, mean_obstruction=12.0,
        alr=alr, alr_rank_pct=rank)


def _render(nv=None, cards=None):
    nights = [SimpleNamespace(night_date=D, moon_free_hours=6.0, window_start=datetime(2026, 10, 17, 21, tzinfo=JST))]
    cards = cards or [_card()]
    return gr.render_html(SimpleNamespace(name="天の川銀河中心"), datetime(2026, 10, 17, 11, 20), nights,
                          {D: "🌓"}, {}, 0, 3, cards, cards, "", {}, [], {}, "概況", night_view_items=nv)


class ReportRenderTests(unittest.TestCase):
    def test_card_shows_alr_not_magnitude(self):
        h = _render()
        self.assertIn("光害(相対指数)", h)
        self.assertIn("ALR 2.34", h)
        self.assertNotIn("mag/arcsec", h)
        self.assertNotIn("実効的な空の明るさ", h)
        self.assertNotIn("ボートル", h)

    def test_footer_and_notice(self):
        h = _render()
        self.assertIn("10.5067/VIIRS/VNP46A4.002", h)
        self.assertIn("Duriscoe et al. 2018", h)
        self.assertIn("相対指数", h)
        self.assertIn("絶対値", h)
        self.assertIn(str(lp.BM_ALR_THRESHOLD), h)

    def test_night_view_group(self):
        item = {"site_name": "菜の花台", "municipality": "横須賀市", "lat": 35.2, "lon": 139.6, "night_date": D,
                "window_start": datetime(2026, 10, 17, 21, tzinfo=JST), "window_end": datetime(2026, 10, 17, 23, tzinfo=JST),
                "mean_obstruction": 10.0, "alr": 17.3, "alr_rank_pct": 98.0}
        h = gr.render_night_view_group([item])
        self.assertIn("光害(相対指数)", h)
        self.assertIn("ALR 17.30", h)

    def test_cards_without_alr_fields_do_not_crash(self):
        c = _card()
        del c.alr, c.alr_rank_pct
        self.assertIn("範囲外(未評価)", gr._light_pollution_stat(c))


if __name__ == "__main__":
    unittest.main()
