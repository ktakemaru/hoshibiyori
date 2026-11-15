"""--json-out の scanned_nights(走査した全部の夜と、外れた理由)のテスト。2026-11-16 追加。通信しない。

- 第1段階(stage1_moon_filter)は _reference_night を差し替えて、夜ごとの分かれ方を手で与える(天文計算をしない)。
- 選び方・並び・表示が scan_out の有無で変わらないこと、--json-out なしでは集めないことを確かめる。
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import explore_hoshibiyori as ex  # noqa: E402
import explore_json as ej  # noqa: E402
from test_explore_json import (FakeCache, SCHEMA_PATH, build, fake_result, make_night,  # noqa: E402
                               validate)

JST = timezone(timedelta(hours=9))

# 夜の番号(0〜13) → 分かれ方。無印は時間帯あり(値は月の影響が小さい時間の長さ)
NO_SUN = {2}
NO_DARK = {5}
NO_WINDOW = {9}
HOURS = {0: 1.0, 1: 2.0, 3: 9.0, 4: 8.0, 6: 7.0, 7: 6.5, 8: 3.0, 10: 6.0, 11: 0.5, 12: 4.0, 13: 5.0}


class FakeRef:
    """_reference_night の代わり。最初に呼ばれた日を0番として、番号ごとに決まった結果を返す。"""

    def __init__(self):
        self.calls: list[datetime] = []

    def __call__(self, ts, eph, lat, lon, day, astro):
        self.calls.append(day)
        i = (day - self.calls[0]).days
        out = {"sunset": None, "sunrise": None, "dark_start": None, "dark_end": None,
               "window_start": None, "window_end": None, "hours": 0.0}
        if i in NO_SUN:
            return out
        out["sunset"] = day.replace(hour=16, minute=40)
        out["sunrise"] = day.replace(hour=6, minute=10) + timedelta(days=1)
        if i in NO_DARK:
            return out
        out["dark_start"] = day.replace(hour=18, minute=5)
        out["dark_end"] = day.replace(hour=4, minute=45) + timedelta(days=1)
        if i in NO_WINDOW:
            return out
        out["window_start"] = out["dark_start"]
        out["window_end"] = out["dark_start"] + timedelta(hours=HOURS[i])
        out["hours"] = HOURS[i]
        return out


def run_stage1(scan_out=None):
    fake = FakeRef()
    out = io.StringIO()
    with mock.patch.object(ex, "_reference_night", fake), contextlib.redirect_stdout(out):
        nights = ex.stage1_moon_filter(None, None, 34.6, 138.85, None, scan_out=scan_out)
    return nights, out.getvalue(), fake


class Stage1ScanTests(unittest.TestCase):
    def test_all_nights_in_date_order_with_reasons(self):
        scan: list = []
        nights, _, fake = run_stage1(scan)
        self.assertEqual(len(scan), ex.NUM_NIGHTS_TO_SCAN)
        dates = [n.night_date for n, _ in scan]
        self.assertEqual(dates, [d.date() for d in fake.calls])   # 日付順・全部の夜
        self.assertEqual(dates, sorted(dates))
        reasons = {i: r for i, (_, r) in enumerate(scan)}
        self.assertEqual(reasons[2], ex.NOT_SELECTED_NO_SUN_EVENTS)
        self.assertEqual(reasons[5], ex.NOT_SELECTED_NO_DARKNESS)
        self.assertEqual(reasons[9], ex.NOT_SELECTED_NO_MOON_FREE)
        # 上位6夜(9.0, 8.0, 7.0, 6.5, 6.0, 5.0)= 3, 4, 6, 7, 10, 13 は理由なし、残りの時間帯ありは not_in_top_n
        selected_idx = {i for i, r in reasons.items() if r is None}
        self.assertEqual(selected_idx, {3, 4, 6, 7, 10, 13})
        for i in (0, 1, 8, 11, 12):
            self.assertEqual(reasons[i], ex.NOT_SELECTED_NOT_IN_TOP_N)
        # 選ばれた夜の集合が nights と一致
        self.assertEqual({scan[i][0].night_date for i in selected_idx}, {n.night_date for n in nights})
        self.assertEqual(set(ex.NOT_SELECTED_REASONS), {r for r in reasons.values() if r is not None})

    def test_missing_times_are_none(self):
        scan: list = []
        run_stage1(scan)
        n_sun, _ = scan[2]
        self.assertIsNone(n_sun.sunset)
        self.assertIsNone(n_sun.dark_start)
        self.assertIsNone(n_sun.window_start)
        self.assertIsNone(n_sun.moon_free_hours)
        n_dark, _ = scan[5]
        self.assertIsNotNone(n_dark.sunset)
        self.assertIsNone(n_dark.dark_start)
        self.assertIsNone(n_dark.moon_free_hours)
        n_win, _ = scan[9]
        self.assertIsNotNone(n_win.dark_start)
        self.assertIsNone(n_win.window_start)
        self.assertIsNone(n_win.window_end)
        self.assertEqual(n_win.moon_free_hours, 0.0)

    def test_selection_and_screen_unchanged_and_no_extra_calls(self):
        without, out_without, fake_without = run_stage1(None)
        scan: list = []
        with_scan, out_with, fake_with = run_stage1(scan)
        self.assertEqual(without, with_scan)            # 選び方・並び
        self.assertEqual(out_without, out_with)         # 表示
        self.assertEqual(len(fake_without.calls), len(fake_with.calls))   # 計算は増えない
        self.assertEqual(len(fake_with.calls), ex.NUM_NIGHTS_TO_SCAN)
        self.assertEqual([n.moon_free_hours for n in with_scan], [9.0, 8.0, 7.0, 6.5, 6.0, 5.0])

    def test_selected_night_objects_are_the_returned_ones(self):
        scan: list = []
        nights, _, _ = run_stage1(scan)
        chosen = [n for n, r in scan if r is None]
        self.assertEqual(sorted(chosen, key=lambda n: n.moon_free_hours, reverse=True), nights)


def scan_fixture():
    """選ばれた夜2つ(17日 MSM、20日 ECMWF)と、外れた夜3つ。"""
    sel17, sel20 = make_night(17), make_night(20)
    top_out = make_night(18, hours=1.0)
    no_win = ex.NightCandidate(date(2026, 11, 19), datetime(2026, 11, 19, 16, 35, tzinfo=JST),
                               datetime(2026, 11, 20, 6, 15, tzinfo=JST), datetime(2026, 11, 19, 18, 3, tzinfo=JST),
                               datetime(2026, 11, 20, 4, 48, tzinfo=JST), None, None, 0.0)
    no_sun = ex.NightCandidate(date(2026, 11, 21), None, None, None, None, None, None, None)
    scan = [(sel17, None), (top_out, ex.NOT_SELECTED_NOT_IN_TOP_N), (no_win, ex.NOT_SELECTED_NO_MOON_FREE),
            (sel20, None), (no_sun, ex.NOT_SELECTED_NO_SUN_EVENTS)]
    return [sel17, sel20], scan


def build_with_scan(target="milkyway"):
    nights, scan = scan_fixture()
    return ej.build_explore_json(
        generated_at=datetime(2026, 11, 16, 4, 38, tzinfo=JST), version="1.1.0", commit="0" * 40, dirty=False,
        target=target, astro_grid="ecmwf", thresholds=ex.explore_thresholds(10.66),
        reference_site={"name": "石廊崎", "lat": 34.6, "lon": 138.85}, nights=nights,
        msm_dates=[date(2026, 11, 17)], finals=[], outlooks=[],
        final_rank_key=lambda f: ex.final_rank_key(f, target), outlook_rank_key=lambda o: ex.outlook_rank_key(o, target),
        is_primary=ex.is_primary_origin, fetch_summary=FakeCache().summary(), fetch_failures=[],
        sites={"primary": 2, "reference": 1, "total": 3, "with_horizon": 1}, scanned_nights=scan)


class BuildScannedTests(unittest.TestCase):
    def test_records_and_codes(self):
        doc = build_with_scan()
        recs = doc["scanned_nights"]
        self.assertEqual([r["night_date"] for r in recs],
                         ["2026-11-17", "2026-11-18", "2026-11-19", "2026-11-20", "2026-11-21"])
        self.assertEqual([r["selected"] for r in recs], [True, False, False, True, False])
        self.assertEqual([r["regime"] for r in recs], ["MSM", None, None, "ECMWF", None])
        self.assertEqual([r["not_selected_reason"] for r in recs],
                         [None, "not_in_top_n", "no_moon_free_window", None, "no_sunset_or_sunrise"])
        self.assertIsNone(recs[2]["window_start"])
        self.assertEqual(recs[2]["moon_free_hours"], 0.0)
        self.assertIsNone(recs[4]["sunset"])
        self.assertIsNone(recs[4]["moon_free_hours"])
        # 選ばれた夜の集合が nights と一致
        self.assertEqual({r["night_date"] for r in recs if r["selected"]}, {n["night_date"] for n in doc["nights"]})

    def test_nights_unchanged_and_key_order(self):
        nights, _ = scan_fixture()
        with_scan = build_with_scan()
        without = build(nights=nights)
        self.assertEqual(with_scan["nights"], without["nights"])
        self.assertNotIn("scanned_nights", without)
        keys = list(with_scan)
        self.assertEqual(keys[keys.index("nights") + 1], "scanned_nights")
        self.assertEqual([k for k in keys if k != "scanned_nights"], list(without))

    def test_notes(self):
        self.assertEqual(build_with_scan()["notes"], ej.NOTES + [ej.SCANNED_NOTE])
        self.assertEqual(build_with_scan("stars")["notes"], ej.NOTES + [ej.SCANNED_NOTE, ej.STARS_NOTE])
        self.assertEqual(ej.SCANNED_NOTE, "scanned_nights は走査した全部の夜です。selected が false の夜は、"
                                          "not_selected_reason の理由で候補から外れています。")

    def test_schema(self):
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        doc = json.loads(ej.dumps(build_with_scan()))
        self.assertEqual(validate(doc, schema, schema), [])
        broken = dict(doc, scanned_nights=[dict(doc["scanned_nights"][1], not_selected_reason="other")])
        self.assertTrue(any("not_selected_reason" in e for e in validate(broken, schema, schema)))
        # スキーマの理由コードの一覧がコードと同じ
        codes = schema["$defs"]["scanned_night"]["properties"]["not_selected_reason"]["enum"]
        self.assertEqual(set(codes) - {None}, set(ex.NOT_SELECTED_REASONS))
        req = set(schema["$defs"]["scanned_night"]["required"]) - {"selected", "regime", "not_selected_reason"}
        import dataclasses
        self.assertEqual(req, {f.name for f in dataclasses.fields(ex.NightCandidate)})


class MainScanTests(unittest.TestCase):
    def run_main(self, argv, result):
        out = io.StringIO()
        with mock.patch.object(ex, "GridCloudCache", lambda: FakeCache()), \
                mock.patch.object(ex, "make_astro_cache", lambda mode: None), \
                mock.patch.object(ex, "_explore", return_value=result) as explore, \
                mock.patch("requests.get", side_effect=AssertionError("通信しない")), \
                mock.patch("requests.Session.get", side_effect=AssertionError("通信しない")), \
                contextlib.redirect_stdout(out):
            code = ex.main(argv)
        return code, out.getvalue(), explore

    def test_without_json_out_does_not_collect(self):
        with mock.patch.object(ej, "scanned_night_records", side_effect=AssertionError("集めない")):
            code, _, explore = self.run_main(["--target", "stars"], fake_result())
        self.assertEqual(code, 0)
        self.assertIs(explore.call_args.kwargs["collect_scan"], False)

    def test_with_json_out_collects_and_writes(self):
        nights, scan = scan_fixture()
        result = dict(fake_result(), nights=nights, scanned_nights=scan)
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "x.json"
            code, _, explore = self.run_main(["--json-out", str(path)], result)
            self.assertEqual(code, 0)
            self.assertIs(explore.call_args.kwargs["collect_scan"], True)
            doc = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(len(doc["scanned_nights"]), 5)
        self.assertIn(ej.SCANNED_NOTE, doc["notes"])

    def test_explore_passes_scan_only_when_collecting(self):
        # _explore の中で stage1_moon_filter に渡す scan_out(集めないときは None)
        seen = []

        def fake_stage1(ts, eph, lat, lon, astro=None, scan_out=None):
            seen.append(scan_out)
            raise RuntimeError("ここで止める")
        sites = [{"name": "石廊崎", "lat": 34.6, "lon": 138.85, "origin": "curated", "horizon_csv": None}]
        with mock.patch.object(ex, "stage1_moon_filter", fake_stage1), \
                mock.patch.object(ex, "load_candidate_sites", return_value=sites), \
                mock.patch.object(ex, "make_lp_store", return_value=mock.Mock(alr_threshold=10.66)), \
                mock.patch.object(ex, "load", mock.Mock()), contextlib.redirect_stdout(io.StringIO()):
            for collect in (False, True):
                with self.assertRaises(RuntimeError):
                    ex._explore(FakeCache(), "stars", None, collect_scan=collect)
        self.assertIsNone(seen[0])
        self.assertEqual(seen[1], [])


if __name__ == "__main__":
    unittest.main()
