"""長い作業の前の予告と見積もり(time_estimates.py、--estimate)のテスト。2026-11-24 追加。通信しない・天文計算をしない。"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import explore_hoshibiyori as ex  # noqa: E402
import generate_report as gr  # noqa: E402
import time_estimates as te  # noqa: E402
from elevation_cloud import level_hourly_vars  # noqa: E402
from cloud_forecast import ECMWF_MAX_FORECAST_DAYS, ECMWF_MODEL, MSM_MAX_FORECAST_DAYS, MSM_MODEL  # noqa: E402
from grid_cache import CACHE_TTL_SEC, GridCloudCache, grid_cell  # noqa: E402
from test_explore_json import FakeCache, fake_result  # noqa: E402

SITES = [dict(name="石廊崎", lat=34.602778, lon=138.845278, origin="curated", horizon_csv=None, elevation_m=60.0),
         dict(name="山の地点", lat=36.0, lon=138.0, origin="curated", horizon_csv=None, elevation_m=1500.0),
         dict(name="明るい地点", lat=35.68, lon=139.77, origin="viewpoint", horizon_csv=None, elevation_m=10.0)]


class FakeLp:
    alr_threshold = 10.66

    def get(self, lat, lon):
        return SimpleNamespace(brightness_ratio=100.0 if lat == 35.68 else 1.0, alr=1.0, rank_pct=1.0)


def fill_cloud(cache_dir: Path, sites) -> int:
    cache = GridCloudCache(cache_dir=cache_dir)
    n = set()
    for s in sites:
        for m, d in ((MSM_MODEL, MSM_MAX_FORECAST_DAYS), (ECMWF_MODEL, ECMWF_MAX_FORECAST_DAYS)):
            key = (m, grid_cell(s["lat"], s["lon"], m), d, level_hourly_vars())
            cache._write_disk(key, {"time": []})
            n.add(key)
    return len(n)


def fill_astro(cache_dir: Path, sites, nights=ex.NUM_NIGHTS_TO_SCAN, windows=True, cells_for=None):
    """計算の代わりに手で与えた値を、実際の AstroNightCache で保存する。cells_for: セルも保存する夜の番号(None=全部)。"""
    def ref_fn(ts, eph, lat, lon, day):
        i = (day.date() - datetime.now(ex.JST).date()).days
        return {"sunset": day, "sunrise": day + timedelta(hours=13), "dark_start": day, "dark_end": day + timedelta(hours=10),
                "window_start": day if windows else None, "window_end": day + timedelta(hours=1 + i) if windows else None,
                "hours": float(1 + i) if windows else 0.0}
    from astro_grid_cache import AstroNightCache
    astro = AstroNightCache(dark_fn=lambda ts, e, la, lo, day: (day, day + timedelta(hours=10)),
                            moon_fn=lambda ts, e, la, lo, a, b: (a, b, 10.0), ref_fn=ref_fn,
                            conditions=ex.astro_conditions(), cache_dir=cache_dir)
    today = datetime.now(ex.JST).replace(hour=0, minute=0, second=0, microsecond=0)
    for i in range(nights):
        day = today + timedelta(days=i)
        astro.reference_night(None, None, sites[0]["lat"], sites[0]["lon"], day)
        if cells_for is None or i in cells_for:
            for s in sites:
                astro.cell_night(None, None, s["lat"], s["lon"], day.date())
    astro.flush()


class EstimateBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.astro = Path(self.tmp.name) / "astro"
        self.cloud = Path(self.tmp.name) / "cloud"
        for target, attr, value in ((ex, "make_lp_store", FakeLp), (ex, "ASTRO_CACHE_DIR", self.astro),
                                    (ex, "load_candidate_sites", lambda: [dict(s) for s in SITES]),
                                    (gr, "load_candidate_sites", lambda: [dict(s) for s in SITES])):
            p = mock.patch.object(target, attr, value)
            p.start()
            self.addCleanup(p.stop)
        for name in ("requests.get", "requests.Session.get"):
            p = mock.patch(name, side_effect=AssertionError("通信しない"))
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch("grid_cache._DEFAULT_CACHE_DIR", self.cloud)
        p.start()
        self.addCleanup(p.stop)

    def state(self, kind="explore"):
        return te.cache_state(ex, kind, [dict(s) for s in SITES], SITES[0], astro_cache_dir=self.astro,
                              cloud_cache_dir=self.cloud)


class CacheStateTests(EstimateBase):
    def test_nothing_saved(self):
        s = self.state()
        self.assertEqual((s.nights_total, s.nights_ready, s.cells_total, s.cells_fresh), (14, 0, 6, 0))
        self.assertFalse(s.ready)
        self.assertFalse(self.cloud.exists())      # 見積もりはフォルダを作らない
        lines = te.estimate_lines("explore", "stars", SITES, s)
        self.assertEqual(lines, ["探索の見積もり: 星空・星座モード / 3 地点", "天文計算の保存: 14 夜のうち 0 夜",
                                 "雲量の保存: 期限内 0 セル / 全 6 セル", "時間の目安: 約6分(通信あり)"])

    def test_everything_saved(self):
        fill_astro(self.astro, SITES)
        self.assertEqual(fill_cloud(self.cloud, SITES), 6)
        s = self.state()
        self.assertTrue(s.ready)
        self.assertEqual(te.estimate_lines("explore", "stars", SITES, s)[1:],
                         ["天文計算の保存: 14 夜のうち 14 夜", "雲量の保存: 期限内 6 セル / 全 6 セル", "時間の目安: 約10秒"])

    def test_only_candidate_nights_need_cells(self):
        # 無月時間帯の長い順に上位6夜 = 番号 8〜13。この6夜のセルがあればそろっている
        fill_astro(self.astro, SITES, cells_for=range(8, 14))
        self.assertEqual(self.state("explore").nights_ready, 14)
        self.assertEqual(self.state("report").nights_ready, 6)   # レポートは無月時間帯のある全部の夜を調べる

    def test_cells_of_light_polluted_sites_are_not_needed(self):
        fill_astro(self.astro, SITES[:2])
        self.assertEqual(self.state().nights_ready, 14)

    def test_partial_is_the_longer_time(self):
        fill_astro(self.astro, SITES, nights=13)
        fill_cloud(self.cloud, SITES)
        s = self.state()
        self.assertEqual(s.nights_ready, 13)
        self.assertEqual(te.pick_time("explore", "stars", s.ready)[0], "約6分")

    def test_expired_cloud_is_not_fresh(self):
        fill_cloud(self.cloud, SITES)
        with mock.patch("grid_cache.time.time", return_value=datetime.now().timestamp() + max(CACHE_TTL_SEC.values()) + 60):
            self.assertEqual(te.cloud_state([dict(s) for s in SITES], self.cloud), (0, 6))

    def test_does_not_delete_old_nights(self):
        folder = self.astro / "v1_old"
        folder.mkdir(parents=True)
        old = folder / "night_2020-01-01.json"
        old.write_text("{}", encoding="utf-8")
        self.state()
        self.assertTrue(old.exists())


def fill_reference_forecast(cache_dir: Path, msm_hours: int) -> None:
    """基準地点の2セルに予報の値を入れる。MSM は今日の0時から msm_hours 時間分。"""
    cache = GridCloudCache(cache_dir=cache_dir)
    today = datetime.now(ex.JST).replace(hour=0, minute=0, second=0, microsecond=0)
    for m, d, hours in ((MSM_MODEL, MSM_MAX_FORECAST_DAYS, msm_hours), (ECMWF_MODEL, ECMWF_MAX_FORECAST_DAYS, 15 * 24)):
        hourly = {"time": [f"{today + timedelta(hours=h):%Y-%m-%dT%H:%M}" for h in range(hours)]}
        for v in level_hourly_vars().split(","):
            hourly[v] = [1500.0 if "geopotential" in v else 10.0] * hours
        cache._write_disk((m, grid_cell(SITES[0]["lat"], SITES[0]["lon"], m), d, level_hourly_vars()), hourly)


class NeededCellsTests(EstimateBase):
    """「通信あり」= この回に要る雲量のセルが期限内に無い。光害で落ちる地点のセルは、MSM の夜を調べる回だけ要る。"""

    def fill(self, msm_hours, **astro):
        fill_cloud(self.cloud, SITES[:2])           # 光害で落ちる地点(3つ目)のセルは無い
        fill_reference_forecast(self.cloud, msm_hours)
        fill_astro(self.astro, SITES[:2], **astro)

    def test_ecmwf_only(self):
        self.fill(0)
        for kind in ("explore", "report"):
            with self.subTest(kind=kind):
                s = self.state(kind)
                self.assertEqual((s.cells_fresh, s.cells_total, s.needed_fresh, s.needed_total), (4, 6, 4, 4))
                self.assertTrue(s.cloud_ready)
                lines = te.estimate_lines(kind, "stars", SITES, s)
                self.assertEqual(lines[2], "雲量の保存: 期限内 4 セル / 全 6 セル(この回に要るのは 4 セル)")
                self.assertEqual(lines[3], "時間の目安: " + {"explore": "約10秒", "report": "約21秒"}[kind])

    def test_msm_night_needs_every_cell(self):
        self.fill(48)
        s = self.state("report")
        self.assertIsNone(s.needed_total)
        self.assertFalse(s.cloud_ready)
        self.assertIn("通信あり", te.estimate_lines("report", "stars", SITES, s)[3])

    def test_msm_night_outside_the_top_is_not_counted(self):
        # 見本の無月時間帯は日が進むほど長いので、MSM の範囲の夜は探索の上位6夜に入らない
        self.fill(48)
        self.assertTrue(self.state("explore").cloud_ready)

    def test_missing_astro_is_not_a_reason(self):
        # 近い3夜だけ保存済み。残りの夜は保存が無いが、MSM の値も無いので、天文計算が無くても要るセルが決まる
        self.fill(0, nights=3)
        for kind in ("explore", "report"):
            s = self.state(kind)
            self.assertEqual((s.nights_ready, s.cloud_ready), (3, True))
            self.assertNotIn("通信あり", te.estimate_lines(kind, "stars", SITES, s)[3])
        self.assertEqual(te.estimate_lines("report", "stars", SITES, self.state("report"))[3],
                         "時間の目安: 約21秒。天文計算の保存が足りない分だけ長くなることがある")

    def test_no_astro_at_all_has_no_short_time(self):
        fill_cloud(self.cloud, SITES[:2])
        fill_reference_forecast(self.cloud, 0)
        self.assertEqual(te.estimate_lines("report", "stars", SITES, self.state("report"))[3], "時間の目安: まだ測っていません")

    def test_unknown_near_night_is_on_the_safe_side(self):
        # MSM の値のある夜の天文計算が無いときは、MSM の夜がありうるので全セルを要るとする
        fill_cloud(self.cloud, SITES[:2])
        fill_reference_forecast(self.cloud, 48)
        self.assertFalse(self.state("report").cloud_ready)

    def test_start_notice(self):
        self.fill(0)
        for msm_hours, text in ((0, "(時間の目安: 約21秒)"), (48, "(時間の目安: まだ測っていません・通信あり)")):
            fill_reference_forecast(self.cloud, msm_hours)
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                te.print_start_notice(ex, "report", "stars", lambda: [dict(s) for s in SITES], "ecmwf")
            self.assertTrue(err.getvalue().endswith(text + "\n"), err.getvalue())


class PickTimeTests(unittest.TestCase):
    def test_measured_combinations(self):
        self.assertEqual(te.pick_time("explore", "stars", False)[0], "約6分")
        self.assertEqual(te.pick_time("explore", "stars", True)[0], "約10秒")
        self.assertEqual(te.pick_time("report", "milkyway", True)[0], "約2分")

    def test_unmeasured_uses_the_longer_and_says_so(self):
        for ready in (True, False):
            text, used = te.pick_time("explore", "milkyway", ready)
            self.assertTrue(text.startswith("約6分"))
            self.assertIn("未実測", text)
            self.assertEqual(used.key, "explore/stars/cold")
        # 2026-11-24 に実測が入ったので代用しない(以前は天の川モードの「約2分」で代用していた)
        self.assertEqual(te.pick_time("report", "stars", True)[0], "約21秒")

    def test_short_measurement_is_not_used_for_a_longer_state(self):
        # レポートは「保存が足りない」状態の実測が無い。保存済みの約2分を当てはめない
        self.assertEqual(te.pick_time("report", "milkyway", False), (te.UNMEASURED_PHRASE, None))

    def test_unmeasured_has_no_number(self):
        for e in te.ESTIMATES:
            self.assertEqual(e.sec is None, e.text == te.UNMEASURED, e.key)
            if e.sec is not None:
                self.assertRegex(e.source, r"^\d{4}-\d{2}-\d{2}")

    def test_text_matches_seconds(self):
        for e in te.ESTIMATES:
            if e.sec is None:
                continue
            n = int(e.text[1:-1])
            self.assertLess(abs(e.sec - n * (60 if e.text.endswith("分") else 1)), 30 if e.text.endswith("分") else 5, e.key)


class AgentsTableTests(unittest.TestCase):
    def test_table_in_agents_md_matches(self):
        lines = (ROOT / "AGENTS.md").read_text(encoding="utf-8").splitlines()
        head = lines.index("| 作業 | コマンド | 目安 | 出どころ |")
        rows = []
        for line in lines[head + 2:]:
            if not line.startswith("|"):
                break
            rows.append(line)
        self.assertEqual(rows, te.table_rows())

    def test_rule_text(self):
        text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("長い作業の前に伝える", text)
        self.assertIn(f"{te.NOTICE_THRESHOLD_SEC} 秒以上かかる見込み", text)


class CommandTests(EstimateBase):
    def run_main(self, module, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = module.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_explore_estimate_does_not_explore(self):
        with mock.patch.object(ex, "_explore", side_effect=AssertionError("探索しない")), \
                mock.patch.object(ex, "GridCloudCache", side_effect=AssertionError("作らない")), \
                mock.patch.object(ex, "find_astro_dark_events", side_effect=AssertionError("計算しない")):
            code, out, err = self.run_main(ex, ["--target", "stars", "--estimate"])
        self.assertEqual(code, 0)
        self.assertEqual(len(out.splitlines()), 4)
        self.assertEqual(out.splitlines()[0], "探索の見積もり: 星空・星座モード / 3 地点")
        self.assertEqual(err, "")

    def test_estimate_with_json_out_writes_nothing(self):
        path = Path(self.tmp.name) / "x.json"
        code, _, _ = self.run_main(ex, ["--estimate", "--json-out", str(path)])
        self.assertEqual(code, 0)
        self.assertFalse(path.exists())

    def test_report_estimate_is_primary_only(self):
        with mock.patch.object(gr, "_generate", side_effect=AssertionError("作らない")), \
                mock.patch.object(gr, "GridCloudCache", side_effect=AssertionError("作らない")):
            code, out, err = self.run_main(gr, ["--estimate"])
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines()[0], "レポートの生成の見積もり: 天の川モード / 2 地点")
        self.assertIn("時間の目安: まだ測っていません・通信あり", out)

    def test_site_mode_does_not_count_saved_nights(self):
        fill_astro(self.astro, SITES)
        fill_cloud(self.cloud, SITES)
        _, out, _ = self.run_main(ex, ["--target", "stars", "--estimate", "--astro-grid", "site"])
        self.assertIn("天文計算の保存: 14 夜のうち 0 夜", out)
        self.assertIn("時間の目安: 約6分", out)
        self.assertNotIn("通信あり", out)      # 雲量はそろっている

    def run_explore(self, notice=True):
        patches = [mock.patch.object(ex, "GridCloudCache", lambda: FakeCache()),
                   mock.patch.object(ex, "make_astro_cache", lambda mode: None),
                   mock.patch.object(ex, "timing_line", lambda *a: "内訳"),
                   mock.patch.object(ex, "_explore", side_effect=lambda *a, **k: (print("本体"), fake_result())[1])]
        if not notice:
            patches.append(mock.patch.object(te, "print_start_notice", lambda *a: None))
        with contextlib.ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            return self.run_main(ex, ["--target", "stars"])

    def test_notice_goes_to_stderr_only(self):
        code, out, err = self.run_explore()
        self.assertEqual(code, 0)
        self.assertEqual(err, "3 地点の星空の条件を調べます(時間の目安: 約6分(通信あり))\n")
        self.assertEqual(out, self.run_explore(notice=False)[1])   # 標準出力は変わらない

    def test_notice_failure_does_not_stop(self):
        with mock.patch.object(te, "cache_state", side_effect=RuntimeError("壊れた保存")):
            code, out, err = self.run_explore()
        self.assertEqual(code, 0)
        self.assertEqual(err, "探索を始めます(時間の目安: まだ測っていません)\n")
        self.assertIn("本体", out)


if __name__ == "__main__":
    unittest.main()
