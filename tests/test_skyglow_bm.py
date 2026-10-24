"""skyglow_bm(Black Marble起点のスカイグロー近似、段階LP1)の単体テスト。通信しない・h5pyを使わない。"""
from __future__ import annotations

import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "step3_light_pollution"))
import skyglow_bm as sg  # noqa: E402


def _point_source(n: int, ij: tuple[int, int], value: float = 100.0) -> np.ndarray:
    a = np.zeros((n, n))
    a[ij] = value
    return a


class PaperFormulaTests(unittest.TestCase):
    def test_alpha_matches_values_quoted_in_paper(self):
        # 論文§3.1: 式(11)の -alpha は 1km で -0.45、300km で -2.20
        self.assertAlmostEqual(float(sg.alpha(1.0)), 0.45, places=2)
        self.assertAlmostEqual(float(sg.alpha(300.0)), 2.20, places=2)

    def test_weight_is_monotonic_decreasing_beyond_dmin(self):
        d = np.array([1.0, 5.0, 20.0, 100.0, 300.0])
        w = sg.weight(d)
        self.assertTrue(np.all(np.diff(w) < 0))

    def test_weight_clamps_at_dmin(self):
        self.assertEqual(float(sg.weight(0.0)), float(sg.weight(sg.D_MIN_KM)))


class NeighborhoodSumTests(unittest.TestCase):
    PIX = 5.0  # 粗い画素にしてテストを速くする

    def test_single_source_decays_with_distance(self):
        n = 301
        c = n // 2
        out = sg.neighborhood_sum(_point_source(n, (c, c)), self.PIX)
        for k in (2, 5, 10, 30):  # 画素数 -> 距離 k*5km
            expect = 100.0 * float(sg.weight(k * self.PIX))
            self.assertAlmostEqual(out[c, c + k], expect, delta=expect * 1e-6)
        self.assertGreater(out[c, c + 2], out[c, c + 10])
        self.assertGreater(out[c, c + 10], out[c, c + 30])

    def test_isotropic(self):
        n = 201
        c = n // 2
        out = sg.neighborhood_sum(_point_source(n, (c, c)), self.PIX)
        v = [out[c, c + 20], out[c, c - 20], out[c + 20, c], out[c - 20, c]]
        self.assertTrue(np.allclose(v, v[0], rtol=1e-6))

    def test_sources_add_up(self):
        n = 201
        a = _point_source(n, (60, 70), 30.0)
        b = _point_source(n, (120, 150), 55.0)
        both = sg.neighborhood_sum(a + b, self.PIX)
        sep = sg.neighborhood_sum(a, self.PIX) + sg.neighborhood_sum(b, self.PIX)
        self.assertTrue(np.allclose(both, sep, rtol=1e-9, atol=1e-9))

    def test_linear_in_radiance(self):
        n = 121
        a = _point_source(n, (60, 60), 10.0)
        self.assertTrue(np.allclose(sg.neighborhood_sum(3 * a, self.PIX),
                                    3 * sg.neighborhood_sum(a, self.PIX), rtol=1e-9))

    def test_source_beyond_radius_is_ignored(self):
        n = 301
        c = n // 2
        out = sg.neighborhood_sum(_point_source(n, (c, c)), self.PIX)
        r_px = int(sg.RADIUS_KM / self.PIX)  # 60
        self.assertGreater(out[c, c + r_px], 0.0)          # ちょうど半径上は数える
        self.assertEqual(out[c, c + r_px + 1], 0.0)        # 半径の外は0
        self.assertEqual(out[c + r_px, c + 1], 0.0)        # 斜め方向でも(距離>300km)

    def test_same_pixel_source_uses_dmin(self):
        n = 121
        c = n // 2
        out = sg.neighborhood_sum(_point_source(n, (c, c), 50.0), self.PIX)
        self.assertAlmostEqual(out[c, c], 50.0 * float(sg.weight(sg.D_MIN_KM)), places=6)

    def test_no_negative_values(self):
        n = 121
        out = sg.neighborhood_sum(_point_source(n, (10, 10), 1e3), self.PIX)
        self.assertGreaterEqual(float(out.min()), 0.0)

    def test_grid_edge_is_truncated_and_flagged_invalid(self):
        # 一様な光源の海。縁の画素は半径の一部が格子外なので、内側より和が小さくなる
        n = 301
        flat = np.ones((n, n))
        out = sg.neighborhood_sum(flat, self.PIX)
        mask = sg.valid_mask(flat.shape, self.PIX)
        c = n // 2
        self.assertTrue(mask[c, c])
        self.assertFalse(mask[0, c])
        self.assertFalse(mask[c, n - 1])
        self.assertLess(out[0, c], out[c, c])
        self.assertLess(out[0, 0], out[0, c])  # 角はさらに小さい
        # 有効領域の内側では一様(縁の影響を受けない)
        inner = out[mask]
        self.assertTrue(np.allclose(inner, inner[0], rtol=1e-6))

    def test_valid_mask_is_empty_when_grid_smaller_than_radius(self):
        self.assertFalse(sg.valid_mask((50, 50), self.PIX).any())

    def test_alr_is_sum_over_calibration_constant(self):
        s = np.array([[562.72, 1125.44]])
        self.assertTrue(np.allclose(sg.alr_from_sum(s), [[1.0, 2.0]]))


class ProjectionAndBinningTests(unittest.TestCase):
    def test_project_roundtrip(self):
        lat0, lon0 = 36.5, 138.4
        la = np.array([30.0, 33.1, 36.5, 38.6, 41.3])
        lo = np.array([132.0, 135.9, 138.4, 141.4, 144.9])
        x, y = sg.project(la, lo, lat0, lon0)
        la2, lo2 = sg.unproject(x, y, lat0, lon0)
        self.assertTrue(np.allclose(la, la2, atol=1e-8))
        self.assertTrue(np.allclose(lo, lo2, atol=1e-8))

    def test_project_distance_from_center_is_great_circle(self):
        # 方位等距離図法: 中心からの平面距離 = 大円距離
        x, y = sg.project(37.0, 138.4, 36.0, 138.4)
        self.assertAlmostEqual(float(np.hypot(x, y)), sg.KM_PER_DEG_LAT, delta=0.2)

    def test_to_plane_clips_noise_and_nan(self):
        ext = {"lat_min": 35.0, "lat_max": 36.0, "lon_min": 138.0, "lon_max": 139.0}
        geom = sg.plane_geometry_for_extent(ext)
        d = 1.0 / 240
        r = np.zeros((20, 20))
        r[5, 5] = 0.49        # 0.5未満 -> 0
        r[6, 6] = np.nan      # 欠損 -> 0
        r[7, 7] = 10.0
        plane = sg.to_plane(r, 35.9, 138.5, d, d, geom)
        self.assertGreater(plane.sum(), 0.0)
        r2 = np.zeros((20, 20))
        r2[7, 7] = 10.0
        plane2 = sg.to_plane(r2, 35.9, 138.5, d, d, geom)
        self.assertAlmostEqual(plane.sum(), plane2.sum(), places=9)

    def test_to_plane_conserves_flux_with_area_normalisation(self):
        ext = {"lat_min": 35.0, "lat_max": 36.0, "lon_min": 138.0, "lon_max": 139.0}
        geom = sg.plane_geometry_for_extent(ext)
        d = 1.0 / 240
        r = np.full((30, 30), 5.0)
        plane = sg.to_plane(r, 35.9, 138.5, d, d, geom)
        lats = 35.9 - (np.arange(30) + 0.5) * d
        area = sum(30 * (d * sg.KM_PER_DEG_LAT) * (d * sg.KM_PER_DEG_LAT * math.cos(math.radians(la)))
                   for la in lats)
        self.assertAlmostEqual(plane.sum(), 5.0 * area / sg.PAPER_CELL_KM ** 2, delta=1e-6 * plane.sum())

    def test_to_plane_ignores_cells_outside_geometry(self):
        ext = {"lat_min": 35.0, "lat_max": 36.0, "lon_min": 138.0, "lon_max": 139.0}
        geom = sg.plane_geometry_for_extent(ext)
        d = 1.0 / 240
        r = np.full((5, 5), 50.0)
        plane = sg.to_plane(r, 45.0, 120.0, d, d, geom)  # 遠く離れた場所
        self.assertEqual(float(plane.sum()), 0.0)


class ExtentTests(unittest.TestCase):
    def _spots_file(self, spots):
        tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
        json.dump({"spots": spots, "viewpoint_reference": [{"lat": 10.0, "lon": 10.0}]}, tmp)
        tmp.close()
        self.addCleanup(Path(tmp.name).unlink)
        return Path(tmp.name)

    def test_extent_follows_spots_and_ignores_viewpoint_reference(self):
        p = self._spots_file([{"lat": 35.0, "lon": 138.0}, {"lat": 37.0, "lon": 140.0}])
        b = sg.spot_bbox(p)
        self.assertEqual((b["lat_min"], b["lat_max"], b["lon_min"], b["lon_max"]), (35.0, 37.0, 138.0, 140.0))
        o = sg.output_extent(p, pad_deg=0.5)
        self.assertAlmostEqual(o["lat_min"], 34.5)
        i = sg.input_extent(p, pad_deg=0.5, margin_km=300.0)
        self.assertAlmostEqual(o["lat_min"] - i["lat_min"], 300.0 / sg.KM_PER_DEG_LAT, places=6)
        self.assertGreater(o["lon_min"] - i["lon_min"], 300.0 / (sg.KM_PER_DEG_LAT * math.cos(math.radians(38))))

    def test_adding_a_far_spot_widens_extent(self):
        small = sg.input_extent(self._spots_file([{"lat": 35.0, "lon": 138.0}]))
        big = sg.input_extent(self._spots_file([{"lat": 35.0, "lon": 138.0}, {"lat": 38.0, "lon": 142.0}]))
        self.assertGreater(big["lat_max"], small["lat_max"])
        self.assertGreater(big["lon_max"], small["lon_max"])

    def test_tiles_for_extent(self):
        self.assertEqual(sg.tiles_for_extent({"lat_min": 31.0, "lat_max": 39.0, "lon_min": 133.0, "lon_max": 139.0}),
                         ["h31v05"])
        t = sg.tiles_for_extent({"lat_min": 35.0, "lat_max": 41.0, "lon_min": 138.0, "lon_max": 141.0})
        self.assertEqual(t, ["h31v04", "h32v04", "h31v05", "h32v05"])


class DerivedGridTests(unittest.TestCase):
    def _grid(self):
        # 緯度 36.00..35.00 / 経度 138.00..139.00 、値は経度とともに0..10
        a = np.tile(np.linspace(0, 10, 101), (101, 1))
        return sg.DerivedGrid(a, 36.0, 138.0, 0.01, {})

    def test_bilinear_lookup(self):
        g = self._grid()
        self.assertAlmostEqual(float(g.at(35.5, 138.5)), 5.0, places=6)
        self.assertAlmostEqual(float(g.at(35.5, 138.255)), 2.55, places=6)

    def test_out_of_range_is_nan(self):
        g = self._grid()
        self.assertTrue(np.isnan(g.at(40.0, 138.5)))
        self.assertTrue(np.isnan(g.at(35.5, 150.0)))

    def test_rank_pct(self):
        p = sg.rank_pct([5.0, 1.0, 3.0])
        self.assertEqual(list(p), [100.0, 0.0, 50.0])
        self.assertEqual(list(sg.rank_pct([2.0, 2.0, 9.0])), [25.0, 25.0, 100.0])

    def test_annotate_spots_adds_separate_fields_and_does_not_mutate(self):
        g = self._grid()
        spots = [{"name": "a", "lat": 35.5, "lon": 138.2, "extra": 1.0},
                 {"name": "b", "lat": 35.5, "lon": 138.8, "extra": 2.0},
                 {"name": "far", "lat": 50.0, "lon": 138.8, "extra": 3.0}]
        before = json.dumps(spots, sort_keys=True)
        out = sg.annotate_spots(spots, g)
        self.assertEqual(json.dumps(spots, sort_keys=True), before)  # 入力は不変
        self.assertEqual([s["extra"] for s in out], [1.0, 2.0, 3.0])    # 既存フィールドはそのまま
        self.assertLess(out[0]["skyglow_bm_index"], out[1]["skyglow_bm_index"])
        self.assertEqual(out[0]["skyglow_bm_rank_pct"], 0.0)
        self.assertEqual(out[1]["skyglow_bm_rank_pct"], 100.0)
        self.assertIsNone(out[2]["skyglow_bm_index"])
        self.assertIsNone(out[2]["skyglow_bm_rank_pct"])


class CommittedDataTests(unittest.TestCase):
    """リポジトリに同梱した派生データの読み込みと常識的な値(ファイルが無ければスキップ)。"""

    PATH = sg.DATA_DIR / "skyglow_bm_2025.npz"

    @unittest.skipUnless(PATH.exists(), "派生データが無い")
    def test_derived_data_is_sane(self):
        g = sg.DerivedGrid.load(self.PATH)
        tokyo = float(g.at(35.6812, 139.7671))
        noto = float(g.at(37.39, 136.90))
        self.assertGreater(tokyo, 50 * noto)
        self.assertEqual(g.meta["layer"], "AllAngle_Composite_Snow_Free")
        self.assertTrue(np.isfinite(g.alr).all())


if __name__ == "__main__":
    unittest.main()
