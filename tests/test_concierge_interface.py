"""ビヨリコンシェル向けの出力(地点の変わらない ID・全地点の一覧・--nights)のテスト。2026-11-24 追加。通信しない。

--nights の通しのテストは、通信の関数を作りもの(回数を数える)に差し替えて _explore を実際に動かす
(天文計算は de421.bsp が要るため、無い環境ではスキップする)。
"""
from __future__ import annotations

import contextlib
import io
import json
import math
import re
import sys
import tempfile
import unittest
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import explore_hoshibiyori as ex  # noqa: E402
import explore_json as ej  # noqa: E402
import grid_cache  # noqa: E402
import requested_nights as rn  # noqa: E402
from cloud_forecast import FetchOutcome  # noqa: E402
from grid_cache import GridCloudCache  # noqa: E402
from test_explore_json import FakeCache, SCHEMA_PATH, build, fake_result, make_final, make_outlook, validate  # noqa: E402

JST = timezone(timedelta(hours=9))
BSP = ex.DATA_ROOT / "step1_astronomy" / "de421.bsp"
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


class SiteIdTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sites = ex.load_candidate_sites()
        cls.fixture = json.loads((ROOT / "tests" / "fixtures" / "site_ids.json").read_text(encoding="utf-8"))

    def test_ids_match_the_recorded_list(self):
        ids = [s["id"] for s in self.sites]
        self.assertEqual(sorted(ids), sorted(self.fixture["site_ids"]))
        self.assertEqual(len(ids), len(set(ids)))
        self.assertNotIn(None, ids)

    def test_retired_ids_are_not_reused(self):
        self.assertEqual(set(self.fixture["retired"]) & {s["id"] for s in self.sites}, set())

    def test_candidates_carry_the_id(self):
        doc = build([make_final("A", site_id="curated:001")], [make_outlook("B", site_id="viewpoint:1")])
        self.assertEqual(doc["finals"][0]["site_id"], "curated:001")
        self.assertEqual(doc["outlooks"][0]["site_id"], "viewpoint:1")

    def test_stages_set_the_id(self):
        site = dict(self.sites[0])
        s = {"night": SimpleNamespace(night_date=date(2026, 11, 28)), "site": site, "moon_free_hours": 4.0,
             "window_start": datetime(2026, 11, 28, 19, tzinfo=JST), "window_end": datetime(2026, 11, 28, 23, tzinfo=JST),
             "mean_obstruction": 5.0, "clear_hours": 4.0}
        lp = SimpleNamespace(alr_threshold=10.66, get=lambda la, lo: SimpleNamespace(brightness_ratio=1.0, alr=1.0, rank_pct=1.0))
        with contextlib.redirect_stdout(io.StringIO()):
            finals = ex.stage3_direction_filter(None, None, [s], lp, "stars")
        self.assertEqual(finals[0].site_id, site["id"])

    def test_site_index(self):
        recs = ej.site_index_records(self.sites, ex.is_primary_origin)
        self.assertEqual([r["site_id"] for r in recs], [s["id"] for s in self.sites])
        self.assertEqual(sum(r["is_primary"] for r in recs), 146)
        labels = Counter(r["label"] for r in recs)
        self.assertEqual([k for k, v in labels.items() if v > 1], [])            # 見分けられる
        self.assertGreater(sum(v > 1 for v in Counter(r["name"] for r in recs).values()), 0)   # 同じ名前は実在する
        by_id = {r["site_id"]: r for r in recs}
        self.assertEqual(by_id["curated:001"]["label"], "神磯の鳥居・大洗海岸(大洗町)")
        self.assertTrue(any(r["requires_lift_access"] for r in recs))
        for r in recs:
            self.assertEqual(validate(r, SCHEMA["$defs"]["site"], SCHEMA), [])

    def test_main_passes_the_index(self):
        result = dict(fake_result(), site_index=self.sites)
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "x.json"
            with mock.patch.object(ex, "GridCloudCache", lambda: FakeCache()), \
                    mock.patch.object(ex, "make_astro_cache", lambda mode: None), \
                    mock.patch.object(ex, "_explore", return_value=result) as explore, \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(ex.main(["--json-out", str(path)]), 0)
            doc = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(len(doc["site_index"]), len(self.sites))
        self.assertNotIn("requested_nights", doc)              # --nights なしではキーも注記も無い
        self.assertNotIn(ej.REQUESTED_NOTE, doc["notes"])
        self.assertNotIn("requested_dates", explore.call_args.kwargs)
        self.assertEqual(validate(doc, SCHEMA, SCHEMA), [])


class ArgumentTests(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(ex.parse_args(["--nights", "2026-11-29,2026-11-28,2026-11-29"]).nights,
                         [date(2026, 11, 28), date(2026, 11, 29)])
        self.assertIsNone(ex.parse_args([]).nights)

    def test_bad_value_is_refused(self):
        for bad in ("2026-13-01", "土曜", ","):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                ex.parse_args(["--nights", bad])


def hourly(now: datetime, model: str, days: int, variables: str, cloud) -> dict:
    """作りものの時系列。cloud(時刻) が雲量(%)。MSM は78時間分、ECMWF は日数分。"""
    n = 78 if "msm" in model else days * 24
    t0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    times = [t0 + timedelta(hours=i) for i in range(n)]
    out = {"time": [t.strftime("%Y-%m-%dT%H:%M") for t in times]}
    for v in variables.split(","):
        m = re.search(r"geopotential\w*_(\d+)hPa", v)
        out[v] = [44330 * (1 - (int(m.group(1)) / 1013.25) ** 0.1903)] * n if m else [float(cloud(t)) for t in times]
    return out


DARK = dict(name="石廊崎", id="curated:irozaki", lat=34.602778, lon=138.845278, origin="curated", elevation_m=60.0,
            municipality="南伊豆町", horizon_csv=None, requires_lift_access=False, site_type=None)
SITES = [DARK,
         dict(DARK, name="暗い高原", id="curated:a", lat=36.1, lon=138.1, elevation_m=1500.0),
         dict(DARK, name="暗い参考地点", id="viewpoint:b", lat=36.9, lon=139.2, origin="viewpoint"),
         dict(DARK, name="明るい参考地点", id="viewpoint:c", lat=35.69, lon=139.76, origin="viewpoint"),
         dict(DARK, name="明るい主軸", id="curated:d", lat=35.44, lon=139.64)]
BRIGHT = {"viewpoint:c", "curated:d"}


class FakeLp:
    alr_threshold = 10.66

    def get(self, lat, lon):
        bright = any(s["lat"] == lat for s in SITES if s["id"] in BRIGHT)
        return SimpleNamespace(brightness_ratio=ex.LP_INDEX_LIMIT * (3.0 if bright else 0.2), alr=30.0 if bright else 1.0,
                               rank_pct=50.0)


@unittest.skipUnless(BSP.exists(), "de421.bsp が無い環境では天文計算のテストをスキップ")
class RequestedNightsTests(unittest.TestCase):
    """_explore を実際に動かす。新月のころ(MSM の夜あり)と、満月のころ(候補が全部 ECMWF 側)。"""
    NEW_MOON = datetime(2026, 12, 8, 9, 0, tzinfo=JST)
    FULL_MOON = datetime(2026, 11, 24, 9, 0, tzinfo=JST)

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)

    def explore(self, now, target, nights=None, cloud=lambda t: 0.0):
        calls = []

        def fake_fetch(lat, lon, model, days, variables=None):
            calls.append((model, lat, lon))
            return FetchOutcome(hourly(now, model, days, variables, cloud), attempts=1)

        class FakeDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return now.astimezone(tz) if tz else now
        out = io.StringIO()
        with mock.patch.object(ex, "datetime", FakeDatetime), mock.patch("astro_grid_cache.datetime", FakeDatetime), \
                mock.patch.object(ex, "load_candidate_sites", lambda: [dict(s) for s in SITES]), \
                mock.patch.object(ex, "make_lp_store", FakeLp), \
                mock.patch.object(grid_cache, "_fetch_hourly_detailed", fake_fetch), \
                mock.patch("requests.get", side_effect=AssertionError("通信しない")), \
                mock.patch("requests.Session.get", side_effect=AssertionError("通信しない")), \
                contextlib.redirect_stdout(out):
            astro = ex.make_astro_cache("ecmwf", cache_dir=Path(self.tmp.name) / f"astro_{now:%Y%m%d}")
            cache = GridCloudCache(disk_cache=False)
            kw = {"requested_dates": nights} if nights else {}
            result = ex._explore(cache, target, astro, collect_scan=True, **kw)
            astro.flush()
        text = re.sub(r"実行時間: .*", "", out.getvalue())
        return result, text, calls, cache

    def doc(self, result, target, cache, now):
        return json.loads(ej.dumps(ej.build_explore_json(
            generated_at=now, version="1.1.0", commit=None, dirty=None, target=target, astro_grid="ecmwf",
            thresholds=ex.explore_thresholds(10.66), reference_site=result["reference_site"], nights=result["nights"],
            msm_dates=result["msm_dates"], finals=result["finals"], outlooks=result["outlooks"],
            final_rank_key=lambda f: ex.final_rank_key(f, target), outlook_rank_key=lambda o: ex.outlook_rank_key(o, target),
            is_primary=ex.is_primary_origin, fetch_summary=cache.summary(), fetch_failures=[], sites=result["sites"],
            scanned_nights=result["scanned_nights"], site_index=result["site_index"],
            requested_nights=result.get("requested_nights"))))

    def not_selected(self, result):
        selected = {n.night_date for n in result["nights"]}
        return [n for n, _ in result["scanned_nights"] if n.night_date not in selected]

    def test_calls_candidates_and_screen_do_not_change(self):
        # (満月のころ・天の川)は、通常の探索が雲量をほとんど取らない場合。ここで通信が増えないことが大事
        for now, target in ((self.NEW_MOON, "stars"), (self.FULL_MOON, "stars"), (self.FULL_MOON, "milkyway")):
            asked_nights = [now.date() + timedelta(days=i) for i in (0, 6, 13)]
            with self.subTest(now=now, target=target):
                base, text, calls, cache = self.explore(now, target)
                asked, text2, calls2, cache2 = self.explore(now, target, asked_nights)
                self.assertEqual(calls, calls2)              # 通信の回数も中身も同じ
                self.assertEqual(cache.summary(), cache2.summary())
                self.assertEqual(base["finals"], asked["finals"])
                self.assertEqual(base["outlooks"], asked["outlooks"])
                self.assertNotIn("requested_nights", base)
                self.assertIn("[指定した夜]", text2)
                self.assertNotIn("[指定した夜]", text)
                a, b = self.doc(base, target, cache, now), self.doc(asked, target, cache2, now)
                self.assertEqual(b.pop("requested_nights")[0]["night_date"], now.date().isoformat())
                self.assertEqual(b["notes"].pop(), ej.REQUESTED_NOTE)
                self.assertEqual(a, b)
                # 標準出力は、足した行のほかは同じ
                head, tail = text2.split("\n[指定した夜]", 1)
                self.assertTrue(text.startswith(head))
                self.assertEqual(text[len(head):].lstrip("\n"), re.sub(r"^(.*\n)(    .*\n)*", "", tail, count=1).lstrip("\n"))

    def test_night_outside_the_top_is_examined(self):
        base, _, _, _ = self.explore(self.NEW_MOON, "stars")
        night = next(n for n in self.not_selected(base) if (n.moon_free_hours or 0) >= 1.0)
        result, _, _, cache = self.explore(self.NEW_MOON, "stars", [night.night_date])
        rec = result["requested_nights"][0]
        self.assertFalse(rec["selected"])
        self.assertTrue(rec["scanned"])
        self.assertEqual(rec["window_kind"], "moon_free")
        self.assertEqual(rec["not_selected_reason"], "not_in_top_n")
        self.assertIsNone(rec["regime"])
        self.assertEqual(rec["forecast_regime"], "ECMWF")
        c = rec["counts"]["all"]
        self.assertEqual((c["total"], c["passed"], c["failed"], c["not_examined"]), (5, 3, 2, 0))
        self.assertEqual(c["failed_reasons"], {"cloud_filter": 0, "light_pollution_filter": 2, "direction_filter": 0})
        self.assertEqual(rec["counts"]["primary"]["total"], 3)
        # 通った地点は全部、通らなかった地点は主軸だけ
        self.assertEqual({s["site_id"]: s["status"] for s in rec["sites"]},
                         {"curated:irozaki": "passed", "curated:a": "passed", "viewpoint:b": "passed", "curated:d": "failed"})
        for s in rec["sites"]:
            self.assertIsNone(s["score"])
        ok = next(s for s in rec["sites"] if s["site_id"] == "curated:a")
        self.assertGreaterEqual(ok["clear_hours"], 1.0)
        self.assertEqual(ok["mean_obstruction"], 0.0)
        doc = self.doc(result, "stars", cache, self.NEW_MOON)
        self.assertEqual(validate(doc, SCHEMA, SCHEMA), [])
        index = {r["site_id"] for r in doc["site_index"]}
        for r in doc["finals"] + doc["outlooks"] + doc["requested_nights"][0]["sites"]:
            self.assertIn(r["site_id"], index)

    def test_dark_when_no_usable_moon_free_window(self):
        d = self.FULL_MOON.date()        # 満月の夜
        result, text, _, _ = self.explore(self.FULL_MOON, "stars", [d])
        rec = result["requested_nights"][0]
        self.assertEqual(rec["window_kind"], "dark")
        self.assertEqual(rec["not_selected_reason"], "no_moon_free_window")
        self.assertEqual(rec["forecast_regime"], "MSM")
        self.assertEqual(rec["counts"]["all"]["passed"], 3)
        self.assertGreater(rec["moon"]["up_hours"], 9.0)
        self.assertGreater(rec["moon"]["illuminated_fraction"], 0.95)
        self.assertTrue(math.isfinite(rec["moon"]["phase_angle_deg"]))
        self.assertIn("暗い時間帯ぜんぶ(月が出ている)", text)

    def test_window_shorter_than_min_clear_is_dark(self):
        # 無月時間帯が1時間未満の夜は、晴れていても「雲で通らない」になるので、暗い時間帯ぜんぶで調べる
        base, _, _, _ = self.explore(self.NEW_MOON, "stars")
        short = [n for n, _ in base["scanned_nights"] if n.window_start is not None and n.moon_free_hours < 1.0]
        self.assertTrue(short)
        result, _, _, _ = self.explore(self.NEW_MOON, "stars", [short[0].night_date])
        rec = result["requested_nights"][0]
        self.assertEqual(rec["window_kind"], "dark")
        self.assertEqual(rec["counts"]["all"]["passed"], 3)
        self.assertEqual(rec["moon_free_hours"], short[0].moon_free_hours)

    def test_out_of_range_is_none(self):
        days = [self.NEW_MOON.date() - timedelta(days=1), self.NEW_MOON.date() + timedelta(days=14)]
        result, text, _, cache = self.explore(self.NEW_MOON, "stars", days)
        for rec in result["requested_nights"]:
            self.assertEqual((rec["window_kind"], rec["none_reason"], rec["scanned"]), ("none", "out_of_scanned_range", False))
            self.assertIsNone(rec["counts"])
            self.assertEqual(rec["sites"], [])
        self.assertIn("調べていない(今日から14夜の外)", text)
        doc = self.doc(result, "stars", cache, self.NEW_MOON)
        self.assertEqual(validate(doc, SCHEMA, SCHEMA), [])

    def test_cloudy_night_is_failed_not_unexamined(self):
        d = self.NEW_MOON.date()
        result, _, _, _ = self.explore(self.NEW_MOON, "stars", [d], cloud=lambda t: 100.0)
        c = result["requested_nights"][0]["counts"]["all"]
        self.assertEqual((c["passed"], c["failed"], c["not_examined"], c["clear"], c["cloud_examined"]), (0, 5, 0, 0, 5))
        self.assertEqual(c["failed_reasons"]["cloud_filter"], 5)

    def test_unfetched_cells_are_not_examined(self):
        # 満月のころの探索は候補が ECMWF 側だけ → 光害で落ちる地点のセルは取られない。「調べていない」理由が残る
        d = self.FULL_MOON.date()
        result, _, calls, _ = self.explore(self.FULL_MOON, "stars", [d])
        bright = next(s for s in result["requested_nights"][0]["sites"] if s["site_id"] == "curated:d")
        self.assertEqual(bright["status"], "failed")                      # 光害で落ちることは雲量なしで決まる
        self.assertEqual(bright["reasons"], ["light_pollution_filter"])
        self.assertEqual(bright["not_examined_reason"], "cell_not_fetched")
        self.assertIsNone(bright["clear_hours"])
        self.assertEqual(result["requested_nights"][0]["counts"]["all"]["cloud_examined"], 3)

    def test_milkyway_direction(self):
        # 冬の天の川モード: 銀河中心は夜のあいだ地平線の下。方角で落ち、雲量のセルを取らない
        d = self.FULL_MOON.date() + timedelta(days=5)
        result, _, _, _ = self.explore(self.FULL_MOON, "milkyway", [d])
        c = result["requested_nights"][0]["counts"]["all"]
        self.assertEqual(c["passed"], 0)
        self.assertEqual(c["failed_reasons"]["direction_filter"], 3)
        self.assertEqual(c["failed_reasons"]["light_pollution_filter"], 2)


class ReaderTests(unittest.TestCase):
    def test_reader_never_fetches_and_never_counts(self):
        cache = GridCloudCache(disk_cache=False)
        with mock.patch.object(grid_cache, "_fetch_hourly_detailed", side_effect=AssertionError("通信しない")):
            reader = rn.FetchedOnlyCache(cache)
            self.assertIsNone(reader.get_hourly(35.0, 139.0, "jma_msm", 4, "x"))
            self.assertFalse(reader.has_cell(35.0, 139.0))
            self.assertFalse(reader.failed_cell(35.0, 139.0))
        self.assertEqual(cache.summary().total_cells, 0)
        self.assertEqual(cache.cache_hit_count, 0)

    def test_failed_cell_is_told_apart(self):
        cache = GridCloudCache(disk_cache=False)
        with mock.patch.object(grid_cache, "_fetch_hourly_detailed", lambda *a, **k: FetchOutcome(None, reason="TimeoutError")):
            for m, d, v in rn._cells():
                cache.get_hourly(35.0, 139.0, m, d, v)
        reader = rn.FetchedOnlyCache(cache)
        self.assertTrue(reader.failed_cell(35.0, 139.0))
        self.assertFalse(reader.has_cell(35.0, 139.0))


if __name__ == "__main__":
    unittest.main()
