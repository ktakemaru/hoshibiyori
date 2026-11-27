"""夜に見られるもの(見どころ)を --json-out に出す(2026-11-27)の単体テスト(通信しない)。

- JSON の見どころ(explore の night_highlights → explore_json.highlights_record)が、レポートの「この時期の見どころ」
  (generate_report.build_sky_guide)と同じ対象・同じ時刻・同じ高度になる(冬の夜と、銀河中心が見える夏の夜)。
- 暗い時間帯が無い夜は null。今の時期に見えない対象(冬の銀河中心など)は not_visible に ID つきで入る。
- 星表と照らしていない対象の印(coordinates_unverified)、種類の空は null、流星群の出現数は「例年の目安」。
- --json-out を付けたときだけ計算する。
天文計算は step1_astronomy/de421.bsp が無い環境ではスキップする。
"""
import contextlib
import io
import json
import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import explore_hoshibiyori as ex  # noqa: E402
import explore_json as ej  # noqa: E402
import generate_report as gr  # noqa: E402
import sky_highlights as sh  # noqa: E402
from test_explore_json import validate  # noqa: E402

JST = timezone(timedelta(hours=9))
BSP = ROOT / "step1_astronomy" / "de421.bsp"
SCHEMA = json.loads((ROOT / "schemas" / "hoshibiyori-explore.schema.json").read_text(encoding="utf-8"))
REF = {"name": "石廊崎", "lat": 34.602778, "lon": 138.845278}


def night(ts, eph, d: date):
    ds, de = ex.find_astro_dark_events(ts, eph, REF["lat"], REF["lon"], datetime(d.year, d.month, d.day, tzinfo=JST))
    return ex.NightCandidate(night_date=d, sunset=None, sunrise=None, dark_start=ds, dark_end=de,
                             window_start=None, window_end=None, moon_free_hours=0.0)


def _names_times(slots):
    return [(s["key"], [(m["id"], m["name"], m["start"], m["end"], m["peak_time"], m["peak_alt"])
                        for i in s["items"] for m in i["members"]]) for s in slots]


@unittest.skipUnless(BSP.exists(), "de421.bsp が無い環境では天文計算のテストをスキップ")
class SameAsReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ts = ex.load.timescale()
        cls.eph = ex.load(str(BSP))

    def check(self, d: date, now: datetime):
        n = night(self.ts, self.eph, d)
        report = gr.build_sky_guide(self.ts, self.eph, REF["lat"], REF["lon"], n, now)
        hl = ex.night_highlights(self.ts, self.eph, REF, [(n, None)], now)
        doc = ej.highlights_record(hl)
        self.assertEqual(validate(doc, SCHEMA["$defs"]["highlights"], SCHEMA), [])
        got = doc["by_night"][d.isoformat()]
        self.assertEqual(validate(got, SCHEMA["$defs"]["highlight_night"], SCHEMA), [])
        want_slots = ej.json_value(report["slots"])
        self.assertEqual(_names_times(got["slots"]), _names_times(want_slots))
        self.assertEqual([(s["start"], s["end"], s["moonlit"], s["moon_up_intervals"]) for s in got["slots"]],
                         [(s["start"], s["end"], s["moonlit"], s["moon_up_intervals"]) for s in want_slots])
        self.assertEqual([(x["name"], x["next_month"]) for x in got["not_visible"]],
                         [(x["name"], x["next_month"]) for x in report["not_visible"]])
        self.assertEqual([(s["id"], s["peak_time"], s["radiant_start"], s["radiant_end"], s["zhr"]) for s in doc["showers"]],
                         [(s["id"], s["peak_time"], s["radiant_start"], s["radiant_end"], s["zhr"])
                          for s in ej.json_value(report["showers"])])
        self.assertEqual(doc["basis"]["min_alt_deg"], gr.MIN_GUIDE_ALT_DEG)
        return doc, got

    def test_winter_night(self):
        doc, got = self.check(date(2026, 11, 28), datetime(2026, 11, 27, 9, 0, tzinfo=JST))
        self.assertTrue(got["slots"])
        hidden = {x["name"]: x for x in got["not_visible"]}
        self.assertIn("天の川銀河中心", hidden)                     # 見えない対象も省かない
        self.assertEqual(hidden["天の川銀河中心"]["ids"], ["galactic_center"])
        self.assertTrue(doc["showers"])                             # ふたご座流星群(12月)
        for s in doc["showers"]:
            self.assertEqual(s["kind"], "流星群")
            self.assertEqual(s["zhr_note"], ej.SHOWER_ZHR_NOTE)
            self.assertEqual(s["caveat"], sh.METEOR_CAVEAT)

    def test_summer_night_galactic_center_visible(self):
        _doc, got = self.check(date(2026, 7, 14), datetime(2026, 7, 13, 9, 0, tzinfo=JST))
        ids = {m["id"] for s in got["slots"] for i in s["items"] for m in i["members"]}
        self.assertIn("galactic_center", ids)
        self.assertNotIn("天の川銀河中心", {x["name"] for x in got["not_visible"]})

    def test_unverified_mark_and_blank_kind(self):
        _doc, got = self.check(date(2026, 11, 28), datetime(2026, 11, 27, 9, 0, tzinfo=JST))
        targets = {t.id: t for t in __import__("catalog").load_targets()}
        members = [m for s in got["slots"] for i in s["items"] for m in i["members"]]
        self.assertTrue(any(m["coordinates_unverified"] for m in members))
        for m in members:
            if m["kind"] == "惑星":
                self.assertFalse(m["coordinates_unverified"])
                continue
            t = targets[m["id"]]
            self.assertEqual(m["coordinates_unverified"], "未照合" in t.source)
            self.assertEqual(m["kind"], t.kind or None)
        self.assertEqual(sum("未照合" in t.source for t in targets.values()), 19)

    def test_no_darkness_is_null(self):
        n = ex.NightCandidate(night_date=date(2026, 11, 30), sunset=None, sunrise=None, dark_start=None, dark_end=None,
                              window_start=None, window_end=None, moon_free_hours=0.0)
        hl = ex.night_highlights(self.ts, self.eph, REF, [(n, "no_astronomical_darkness")],
                                 datetime(2026, 11, 27, 9, 0, tzinfo=JST))
        self.assertIsNone(ej.highlights_record(hl)["by_night"]["2026-11-30"])


class JsonShapeTests(unittest.TestCase):
    def test_absent_highlights_is_null_without_note(self):
        import test_explore_json as tej
        doc = tej.build([], [])
        self.assertIn("highlights", doc)
        self.assertIsNone(doc["highlights"])
        self.assertNotIn(ej.HIGHLIGHTS_NOTE, doc["notes"])
        self.assertEqual(validate(doc, SCHEMA, SCHEMA), [])

    def test_only_with_json_out(self):
        seen = []

        def fake_explore(cache, target, astro, **kw):
            seen.append(kw)
            raise ex.OpenMeteoDailyLimitError("止める")    # 中身は要らない(呼ばれ方だけを見る)

        class Cache:
            def summary(self):
                return SimpleSummary()

        class SimpleSummary:
            def console_line(self):
                return ""
        for argv, want in (([], False), (["--json-out", "x.json"], True)):
            args = ex.parse_args(argv)
            with mock.patch.object(ex, "_explore", fake_explore), contextlib.redirect_stdout(io.StringIO()):
                ex._run(Cache(), args, None, {})
            self.assertEqual(seen[-1].get("collect_highlights", False), want)


if __name__ == "__main__":
    unittest.main()
