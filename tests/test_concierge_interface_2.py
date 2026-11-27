"""コンシェル向けの項目の追加(2026-11-27)の単体テスト(通信しない)。

- requested_nights[].sites[].night_rank: passed の地点だけ group ごとに1から、ほかは null。
  星空・星座モードはどの夜も「ALR が小さい→月の影響が小さい時間が長い順」(outlooks の決め方、利用者の決定)で、候補の夜では同じ夜の
  outlooks の rank と、共通の地点どうしの並びが同じ。天の川モードは予報が MSM の夜は finals、ECMWF の夜は outlooks と同じ。
- site_index[].origin(候補の origin と同じ値)。
- 月を条件にしていない dark の夜の passed の注記。
_explore を実際に動かす部分は tests/test_concierge_interface.py の仕組み(作りものの時刻・雲量・光害)を使う。
天文計算は step1_astronomy/de421.bsp が無い環境ではスキップする。
"""
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import explore_hoshibiyori as ex  # noqa: E402
import explore_json as ej  # noqa: E402
import test_concierge_interface as tci  # noqa: E402

JST = timezone(timedelta(hours=9))
BSP = ROOT / "step1_astronomy" / "de421.bsp"


def _order_by_rank(recs, key):
    return [r["site_id"] for r in sorted(recs, key=lambda r: r[key])]


@unittest.skipUnless(BSP.exists(), "de421.bsp が無い環境では天文計算のテストをスキップ")
class NightRankTests(unittest.TestCase):
    NEW_MOON = tci.RequestedNightsTests.NEW_MOON
    SUMMER = datetime(2026, 7, 13, 9, 0, tzinfo=JST)     # 新月(7/14)のころ。銀河中心が夜に高く上がる

    explore = tci.RequestedNightsTests.explore
    doc = tci.RequestedNightsTests.doc

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)

    def run_all_nights(self, now, target):
        nights = [now.date() + timedelta(days=i) for i in range(14)]
        result, _text, _calls, cache = self.explore(now, target, nights)
        return result, self.doc(result, target, cache, now)

    def check_rank_shape(self, doc):
        for night in doc["requested_nights"]:
            for group in ("primary", "reference"):
                members = [s for s in night["sites"] if s["group"] == group]
                ranks = sorted(s["night_rank"] for s in members if s["status"] == "passed")
                self.assertEqual(ranks, list(range(1, len(ranks) + 1)), f"{night['night_date']} {group}")
                for s in members:
                    if s["status"] != "passed":
                        self.assertIsNone(s["night_rank"])
                    self.assertIsNone(s["score"])

    def check_same_order_as_candidates(self, doc, stars=False):
        """候補の夜では、同じ夜の finals / outlooks の並びと、共通の地点どうしの並びが同じ。比べた夜の (MSM, ECMWF) の数を返す。
        stars なら MSM の夜は比べない(星空・星座モードの night_rank は outlooks の決め方で、finals とは違ってよい)。"""
        compared = {"MSM": 0, "ECMWF": 0}
        for night in doc["requested_nights"]:
            if not night["selected"] or (stars and night["regime"] == "MSM"):
                continue
            listed = doc["finals"] if night["regime"] == "MSM" else doc["outlooks"]
            for group in ("primary", "reference"):
                cands = [c for c in listed if c["night_date"] == night["night_date"] and c["group"] == group]
                passed = [s for s in night["sites"] if s["status"] == "passed" and s["group"] == group]
                shared = {c["site_id"] for c in cands} & {s["site_id"] for s in passed}
                if len(shared) < 2:
                    continue
                a = [x for x in _order_by_rank(cands, "rank") if x in shared]
                b = [x for x in _order_by_rank(passed, "night_rank") if x in shared]
                self.assertEqual(a, b, f"{night['night_date']} {group}")
                compared[night["regime"]] += 1
        return compared

    def check_stars_order(self, doc, now):
        """星空・星座モードは、どの夜も ALR が小さい→月の影響が小さい時間が長い(同じなら地点の並び)。比べた夜の数を返す。
        月の影響が小さい時間は、探索が保存した天文計算(同じ格子の代表点)から読む。"""
        ts = ex.load.timescale()
        eph = ex.load(str(BSP))
        astro = ex.make_astro_cache("ecmwf", cache_dir=Path(self.tmp.name) / f"astro_{now:%Y%m%d}")
        order = {s["site_id"]: i for i, s in enumerate(doc["site_index"])}
        nights = 0
        for night in doc["requested_nights"]:
            for group in ("primary", "reference"):
                passed = [s for s in night["sites"] if s["status"] == "passed" and s["group"] == group]
                if len(passed) < 2:
                    continue
                moon = {}
                for s in passed:
                    _a, _b, h = ex.compute_site_night_window(ts, eph, next(x for x in tci.SITES if x["id"] == s["site_id"]),
                                                             date.fromisoformat(night["night_date"]), astro)
                    moon[s["site_id"]] = h
                want = [s["site_id"] for s in sorted(passed, key=lambda s: (s["alr"], -moon[s["site_id"]], order[s["site_id"]]))]
                self.assertEqual(_order_by_rank(passed, "night_rank"), want, f"{night['night_date']} {group}")
                nights += 1
        return nights

    def test_stars_mode(self):
        result, doc = self.run_all_nights(self.NEW_MOON, "stars")
        self.assertEqual(tci.validate(doc, tci.SCHEMA, tci.SCHEMA), [])
        self.check_rank_shape(doc)
        compared = self.check_same_order_as_candidates(doc, stars=True)
        self.assertGreater(compared["ECMWF"], 0)
        self.assertTrue(any(n["selected"] and n["regime"] == "MSM" for n in doc["requested_nights"]))   # MSM の夜もある
        self.assertGreater(self.check_stars_order(doc, self.NEW_MOON), 0)
        # 候補の夜に入らない夜にも順位が付く
        others = [n for n in doc["requested_nights"] if not n["selected"] and n["counts"]]
        self.assertTrue(any(s["night_rank"] is not None for n in others for s in n["sites"]))

    def test_milkyway_mode_in_summer(self):
        result, doc = self.run_all_nights(self.SUMMER, "milkyway")
        self.assertEqual(tci.validate(doc, tci.SCHEMA, tci.SCHEMA), [])
        self.assertGreater(len(doc["finals"]) + len(doc["outlooks"]), 0)
        self.check_rank_shape(doc)
        compared = self.check_same_order_as_candidates(doc)
        self.assertGreater(sum(compared.values()), 0)

    def test_ties_keep_site_order(self):
        # 同じ順位キーの地点は、地点の並び(sites の順)のまま。finals・outlooks の並べ方と同じ
        items = [SimpleNamespace(origin="curated", name=n, alr=1.0, lp_index=0.1, moon_free_hours=5.0) for n in "ABC"]
        got = [x.name for _g, _p, _r, x in ej.ranked_groups(items, lambda o: ex.outlook_rank_key(o, "stars"),
                                                              ex.is_primary_origin)]
        self.assertEqual(got, ["A", "B", "C"])


class PeakAltitudeTests(unittest.TestCase):
    @unittest.skipUnless(BSP.exists(), "de421.bsp が無い環境では天文計算のテストをスキップ")
    def test_same_as_scalar(self):
        ts = ex.load.timescale()
        eph = ex.load(str(BSP))
        target = ex.get_target(ex.TARGET_ID)
        site = {"name": "A", "lat": 35.9, "lon": 138.4, "elevation_m": 1300.0}
        for d in (date(2026, 4, 17), date(2026, 7, 14), date(2026, 12, 9)):
            start = datetime(d.year, d.month, d.day, 20, 7, tzinfo=JST)
            for hours in (1, 3, 8):
                end = start + timedelta(hours=hours)
                got = ex.peak_altitude(ts, eph, site, target, start, end)
                want = ex.peak_altitude_scalar(ts, eph, site, target, start, end)
                self.assertEqual(got, want)
                self.assertEqual(repr(got), repr(want))

    def test_scores_are_the_old_formula(self):
        # 1.2.0 の式(stage3_direction_filter・stage_outlook に書かれていたもの)と同じ値
        self.assertEqual(ex.final_score(12.5, 33.3, 5.0, 4.25, 1.7),
                         (100.0 - 12.5) * 1.0 + max(0.0, 33.3 - 5.0) * 0.5 + 4.25 * 3.0 - 1.7 * 10.0)
        self.assertEqual(ex.final_score(12.5, 33.3, None, 4.25, 1.7),
                         (100.0 - 12.5) * 1.0 + max(0.0, 33.3 - 0.0) * 0.5 + 4.25 * 3.0 - 1.7 * 10.0)
        self.assertEqual(ex.outlook_score(1.7, 33.3, 5.0, 6.5),
                         (100.0 - 1.7 * 10.0) + max(0.0, 33.3 - 5.0) * 0.5 + 6.5 * 3.0)


class SiteOriginTests(unittest.TestCase):
    def test_site_index_has_origin(self):
        sites = ex.load_candidate_sites()
        recs = ej.site_index_records(sites, ex.is_primary_origin)
        self.assertEqual([r["origin"] for r in recs], [s["origin"] for s in sites])
        for r in recs:
            self.assertEqual(r["is_primary"], ex.is_primary_origin(r["origin"]))
            self.assertEqual(tci.validate(r, tci.SCHEMA["$defs"]["site"], tci.SCHEMA), [])

    def test_dark_night_note(self):
        self.assertIn("window_kind が dark の夜の passed は、月を条件にしていません", ej.REQUESTED_NOTE)
        desc = tci.SCHEMA["$defs"]["requested_site"]["properties"]["status"]["description"]
        self.assertIn("dark の夜の passed は、月を条件にしていない", desc)


if __name__ == "__main__":
    unittest.main()
