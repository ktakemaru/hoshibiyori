"""「この時期の見どころ」(sky_highlights.py と generate_report.render_sky_guide)のテスト。2026-11-24 追加。通信しない。"""
from __future__ import annotations

import json
import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import explore_hoshibiyori as ex  # noqa: E402
import generate_report as gr  # noqa: E402
import sky_highlights as sh  # noqa: E402
from catalog import Target, load_targets  # noqa: E402

JST = timezone(timedelta(hours=9))
BSP = ex.DATA_ROOT / "step1_astronomy" / "de421.bsp"
LAT, LON = 34.602778, 138.845278      # 基準地点(石廊崎)
MIN_ALT = gr.MIN_GUIDE_ALT_DEG
T0 = datetime(2026, 11, 24, 22, 0, tzinfo=JST)
TIMES = [T0 + timedelta(minutes=15 * i) for i in range(5)]


def target(name, group="", kind="星", first=False):
    return Target(id=name, name=name, name_en="", ra_hours=0.0, dec_deg=0.0, best_season="", best_months=[],
                  kind=kind, group=group, first_magnitude=first)


RISING = [30.0, 31.0, 32.0, 33.0, 34.0]
TRANSIT = [30.0, 31.0, 32.0, 31.0, 30.0]
LOW = [5.0] * 5
AZ = [180.0] * 5


class SlotTests(unittest.TestCase):
    def test_three_slots(self):
        s = sh.night_slots(date(2026, 11, 24), T0.replace(hour=18), T0.replace(hour=5) + timedelta(days=1))
        self.assertEqual([(x[1], f"{x[2]:%d %H:%M}", f"{x[3]:%d %H:%M}") for x in s],
                         [("宵", "24 18:00", "24 22:00"), ("夜半", "24 22:00", "25 02:00"), ("明け方", "25 02:00", "25 05:00")])

    def test_short_summer_night(self):
        s = sh.night_slots(date(2027, 6, 20), datetime(2027, 6, 20, 22, 30, tzinfo=JST), datetime(2027, 6, 21, 1, 30, tzinfo=JST))
        self.assertEqual([(x[0], f"{x[2]:%H:%M}", f"{x[3]:%H:%M}") for x in s], [("midnight", "22:30", "01:30")])


class SlotItemsTests(unittest.TestCase):
    """方位・高度を手で与える(天文計算をしない)。"""

    def names(self, planets, targets, moon=False):
        return [i["name"] for i in sh.slot_items(TIMES, planets, targets, 15.0, moon)]

    def test_order_planets_then_season_then_others(self):
        got = self.names([("土星", AZ, RISING)], [(target("昇る星"), AZ, RISING), (target("南中する星"), AZ, TRANSIT)])
        self.assertEqual(got, ["惑星", "南中する星", "昇る星"])

    def test_same_class_keeps_the_file_order(self):
        self.assertEqual(self.names([], [(target("b"), AZ, TRANSIT), (target("a"), AZ, TRANSIT)]), ["b", "a"])

    def test_limit(self):
        many = [(target(f"星{i}"), AZ, TRANSIT) for i in range(10)]
        self.assertEqual(self.names([("火星", AZ, RISING), ("木星", AZ, RISING)], many), ["惑星", "星0", "星1", "星2"])
        self.assertEqual(sh.MAX_ITEMS_PER_SLOT, 4)

    def test_low_objects_are_not_shown(self):
        self.assertEqual(self.names([("金星", AZ, LOW)], [(target("低い星"), AZ, LOW)]), [])

    def test_group_is_one_item(self):
        items = sh.slot_items(TIMES, [], [(target("オリオン座", "オリオン座"), AZ, RISING),
                                          (target("リゲル", "オリオン座", first=True), AZ, TRANSIT),
                                          (target("隠れた星", "オリオン座"), AZ, LOW)], 15.0, False)
        self.assertEqual(len(items), 1)
        self.assertEqual([m["name"] for m in items[0]["members"]], ["オリオン座", "リゲル"])
        self.assertTrue(items[0]["in_season"])
        self.assertTrue(items[0]["has_first_magnitude"])

    def test_moonlight_puts_bright_first_and_marks_faint(self):
        targets = [(target("淡い銀河", kind="銀河"), AZ, TRANSIT), (target("1等星", first=True), AZ, RISING)]
        self.assertEqual(self.names([], targets, moon=False), ["淡い銀河", "1等星"])
        items = sh.slot_items(TIMES, [("土星", AZ, RISING)], targets, 15.0, True)
        self.assertEqual([i["name"] for i in items], ["惑星", "1等星", "淡い銀河"])
        self.assertTrue(items[2]["members"][0]["faint_in_moonlight"])
        self.assertFalse(items[1]["members"][0]["faint_in_moonlight"])
        self.assertIn("〈月明かりで見えにくい〉", gr.guide_item_text(items[2], T0.date())[0])


class ShortWindowTests(unittest.TestCase):
    """見える時間帯が表示の刻み(30分)より短い・丸めると始まりと終わりが同じになる対象は、その時間帯に出さない(月の区間と同じ決まり)。"""

    def items(self, planets, targets, times=TIMES):
        return sh.slot_items(times, planets, targets, 15.0, False)

    def test_only_the_last_sample(self):
        # 実物で「金星(翌05:00〜翌05:00)」になっていた形: 最後の1点だけ高度15°以上
        last = [5.0] * 4 + [18.0]
        self.assertEqual(self.items([("金星", AZ, last)], [(target("昇る星"), AZ, last)]), [])
        got = self.items([("金星", AZ, last), ("火星", AZ, RISING)], [])
        self.assertEqual([m["name"] for m in got[0]["members"]], ["火星"])

    def test_boundary(self):
        self.assertEqual(self.items([], [(target("15分"), AZ, [5.0] * 3 + [18.0] * 2)]), [])
        self.assertEqual([i["name"] for i in self.items([], [(target("30分"), AZ, [5.0] * 2 + [18.0] * 3)])], ["30分"])

    def test_rounds_to_the_same_time(self):
        # 22:45〜23:15 は30分あるが、丸めるとどちらも 23:00
        t = [datetime(2026, 11, 20, 22, 45, tzinfo=JST) + timedelta(minutes=15 * i) for i in range(3)]
        self.assertEqual(gr._guide_hm(t[0], t[0].date()), gr._guide_hm(t[-1], t[0].date()))
        self.assertEqual(self.items([], [(target("x"), AZ[:3], RISING[:3])], t), [])

    def test_short_member_leaves_the_group(self):
        last = [5.0] * 4 + [18.0]
        got = self.items([], [(target("大三角", "大三角"), AZ, last), (target("甲", "大三角", first=True), AZ, last),
                              (target("乙", "大三角"), AZ, RISING)])
        self.assertEqual([m["name"] for m in got[0]["members"]], ["乙"])
        self.assertFalse(got[0]["has_first_magnitude"])
        self.assertEqual(gr.guide_item_text(got[0], T0.date())[0], "乙(大三角)")

    def test_next_object_takes_the_place(self):
        # 件数の上限は、短い対象を外したあとで数える
        last = [5.0] * 4 + [18.0]
        got = self.items([], [(target("短い"), AZ, last)] + [(target(f"星{i}"), AZ, TRANSIT) for i in range(5)])
        self.assertEqual([i["name"] for i in got], ["星0", "星1", "星2", "星3"])


class RenderTests(unittest.TestCase):
    def guide(self, **kw):
        base = {"night_date": T0.date(), "min_alt_deg": 15.0, "slots": [], "not_visible": [], "showers": [], "winter_band": None}
        return dict(base, **kw)

    def test_empty(self):
        self.assertEqual(gr.render_sky_guide({}), "")
        self.assertEqual(gr.render_sky_guide(self.guide()), "")

    def test_slot_and_hidden(self):
        items = sh.slot_items(TIMES, [("土星", AZ, RISING)], [(target("アンタレス", "さそり座"), AZ, TRANSIT)], 15.0, True)
        html = gr.render_sky_guide(self.guide(
            slots=[{"key": "midnight", "label": "夜半", "start": TIMES[0], "end": TIMES[-1], "moonlit": True, "items": items,
                    "moon_up_intervals": [{"start": TIMES[0], "end": TIMES[2]}]}],
            not_visible=[{"name": "天の川銀河中心", "next_month": 2}, {"name": "ある星", "next_month": None}]))
        self.assertIn("夜半(22:00〜23:00、月は22:00〜22:30に出ている)", html)
        self.assertIn("<b>アンタレス(さそり座)</b>: 22:00〜23:00、22:30ごろ南の高度32°", html)
        self.assertIn("<b>惑星</b>: 土星(22:00〜23:00、23:00ごろ南の高度34°)", html)
        self.assertIn("今の時期は見えません: 天の川銀河中心(次に見えるのは2月ごろ)、ある星</p>", html)
        self.assertIn("対象地点固有の地形は考慮しない一般的な目安です", html)      # 今の注意書きを残す

    def test_empty_slot_and_note(self):
        html = gr.render_sky_guide(self.guide(
            slots=[{"key": "midnight", "label": "夜半", "start": TIMES[0], "end": TIMES[-1], "moonlit": False, "items": [],
                    "moon_up_intervals": []}]))
        self.assertIn("高度15&deg;以上に30分以上出る対象はありません", html)
        self.assertIn("見える時間が30分より短い対象は、その時間帯には出しません", html)
        self.assertIn("照らしていないのは星・星団の座標だけ", html)
        self.assertIn("流星群の値は、流星群の一覧[Wikipedia「List of meteor showers」]と2026年11月24日に照合済み", html)

    def test_degree_sign_has_no_gap(self):
        # 「56° )」のように空いて見えるのは、文字ではなくフォント(Yu Gothic の「°」は全角幅)。文に空白を入れず、「°」だけ別のフォントで出す
        items = sh.slot_items(TIMES, [("土星", AZ, RISING)], [(target("星"), AZ, TRANSIT)], 15.0, False)
        for i in items:
            self.assertNotRegex(gr.guide_item_text(i, T0.date())[1], r"°\s")
        self.assertRegex(gr.CSS, r'@font-face \{ font-family: "hb-degree";[^}]*unicode-range: U\+00B0; \}')
        self.assertRegex(gr.CSS, r'(?s)\nbody \{[^}]*font-family: "hb-degree", "Yu Gothic"')

    def test_short_moon_interval_is_not_shown(self):
        short = [{"start": TIMES[0], "end": TIMES[0] + timedelta(minutes=15)}]
        html = gr.render_sky_guide(self.guide(
            slots=[{"key": "midnight", "label": "夜半", "start": TIMES[0], "end": TIMES[-1], "moonlit": True, "items": [],
                    "moon_up_intervals": short}]))
        self.assertIn("夜半(22:00〜23:00)", html)
        self.assertEqual(gr._guide_moon(short, T0.date()), "月は出ていない")
        # 30分でも、丸めると始まりと終わりが同じ時刻になる区間は出さない(22:45〜23:15 → 23:00〜23:00)
        half = [{"start": datetime(2026, 11, 20, 22, 45, tzinfo=JST), "end": datetime(2026, 11, 20, 23, 15, tzinfo=JST)}]
        self.assertEqual(gr._guide_moon(half, date(2026, 11, 20)), "月は出ていない")

    def test_shower_always_has_the_caveat(self):
        s = {"name": "ふたご座流星群", "peak_time": datetime(2026, 12, 14, 22, 49, tzinfo=JST), "zhr": 150, "source": "x",
             "caveat": sh.METEOR_CAVEAT, "night_date": date(2026, 12, 14), "radiant_start": datetime(2026, 12, 14, 20, 5, tzinfo=JST),
             "radiant_end": datetime(2026, 12, 15, 5, 13, tzinfo=JST), "moon_up_intervals": [], "moon_illuminated_fraction": 0.25}
        html = gr.render_sky_guide(self.guide(showers=[s]))
        self.assertIn("極大は12月14日 23:00ごろ(日本時間)", html)
        self.assertIn("20:00〜翌05:00", html)
        self.assertIn("理想の条件での目安で、実際に見える数はこれより少ない。突発的な増減は予測できない", html)
        none = gr.guide_shower_text(dict(s, radiant_start=None, radiant_end=None))[1]
        self.assertIn("放射点が高度20°以上に出ない", none)
        self.assertIn(sh.METEOR_CAVEAT, none)


class DataTests(unittest.TestCase):
    def test_sources_are_marked(self):
        old = {"galactic_center", "big_dipper", "cassiopeia", "orion", "summer_triangle", "winter_triangle", "pleiades"}
        targets = load_targets()
        self.assertEqual(len({t.id for t in targets}), len(targets))
        self.assertEqual(len({t.name for t in targets}), len(targets))
        for t in targets:
            self.assertEqual("未照合" in t.source, t.id not in old, t.id)
        for s in sh.load_showers():
            self.assertIn("照合済み", s["source"])
            self.assertNotIn("未照合", s["source"])
            self.assertIn("List of meteor showers", s["source"])
            self.assertIn("2026-11-24", s["source"].split("照合済み", 1)[1])
        self.assertEqual(len(sh.load_showers()), 7)

    def test_existing_targets_unchanged(self):
        want = {"galactic_center": (17.760011, -29.007806, [6, 7, 8]), "big_dipper": (12.900486, 55.959833, [3, 4, 5]),
                "cassiopeia": (0.945139, 60.716667, [10, 11, 12, 1]), "orion": (5.603558, -1.201917, [12, 1, 2]),
                "summer_triangle": (19.717519, 30.977407, [7, 8, 9, 10]), "winter_triangle": (6.775680, -1.361355, [12, 1, 2]),
                "pleiades": (3.790000, 24.116667, [11, 12, 1])}
        got = {t.id: (t.ra_hours, t.dec_deg, t.best_months) for t in load_targets()}
        for k, v in want.items():
            self.assertEqual(got[k], v)

    def test_coordinates_agree_with_the_sky_guide_catalog(self):
        # 星空ガイドの恒星カタログ(skyguide/objects.json)と同じ名前のものは 0.5°以内(どちらも星表とは照らしていない)
        import math
        from skyguide.astro import load_objects
        cat = {o["name"]: o for o in load_objects()}
        checked = 0
        for t in load_targets():
            o = cat.get(t.name)
            if o is None:
                continue
            checked += 1
            d = math.hypot((t.ra_hours - o["ra_hours"]) * 15 * math.cos(math.radians(t.dec_deg)), t.dec_deg - o["dec_deg"])
            self.assertLess(d, 0.5, t.name)
        self.assertGreaterEqual(checked, 12)


@unittest.skipUnless(BSP.exists(), "de421.bsp が無い環境では天文計算のテストをスキップ")
class AstronomyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ts = ex.load.timescale()
        cls.eph = ex.load(str(BSP))
        cls.addClassCleanup(cls.eph.close)

    def guide(self, y, m, d):
        start, end = ex.find_astro_dark_events(self.ts, self.eph, LAT, LON, datetime(y, m, d, tzinfo=JST))
        return sh.build(ex, self.ts, self.eph, LAT, LON, date(y, m, d), start, end, datetime(y, m, d, 9, tzinfo=JST), MIN_ALT)

    def slot_names(self, guide, key):
        slot = next(s for s in guide["slots"] if s["key"] == key)
        return {i["name"] for i in slot["items"]} | {m["name"] for i in slot["items"] for m in i["members"]}

    def test_december_midnight(self):
        names = self.slot_names(self.guide(2026, 12, 15), "midnight")
        self.assertLessEqual({"オリオン座", "シリウス", "すばる"}, names)

    def test_june_midnight(self):
        guide = self.guide(2027, 6, 15)
        names = self.slot_names(guide, "midnight")
        self.assertLessEqual({"ベガ", "アルタイル", "アンタレス"}, names)
        self.assertEqual(names & {"オリオン座", "シリウス", "すばる"}, set())
        hidden = {n["name"]: n["next_month"] for n in guide["not_visible"]}
        self.assertIn("オリオン座", hidden)
        self.assertIn(hidden["オリオン座"], (7, 8, 9))

    @mock.patch.object(sh, "_next_visible", lambda *a: {})
    def test_no_window_starts_and_ends_at_the_same_time(self):
        # 利用者が見た夜(2026-11-24、明け方の金星は暗い時間帯の終わりの1点だけ)と、1年の中のいくつかの夜
        for y, m, d in ((2026, 11, 24), (2026, 12, 1), (2027, 3, 10), (2027, 6, 15), (2027, 9, 10)):
            for s in self.guide(y, m, d)["slots"]:
                self.assertTrue(s["items"])
                for i in s["items"]:
                    for mem in i["members"]:
                        self.assertGreaterEqual(mem["end"] - mem["start"], timedelta(minutes=30))
                        self.assertNotEqual(gr._guide_hm(mem["start"], date(y, m, d)), gr._guide_hm(mem["end"], date(y, m, d)))
        self.assertNotIn("金星", self.slot_names(self.guide(2026, 11, 24), "dawn"))

    @mock.patch.object(sh, "_next_visible", lambda *a: {})
    def test_only_listed_objects_and_counts(self):
        allowed = {t.name for t in load_targets()} | {t.group for t in load_targets()} | {n for n, _ in sh.PLANETS} | {"惑星"}
        for y, m, d in ((2026, 11, 24), (2027, 3, 10), (2027, 6, 15)):
            for s in self.guide(y, m, d)["slots"]:
                self.assertLessEqual(len(s["items"]), sh.MAX_ITEMS_PER_SLOT)
                for i in s["items"]:
                    for mem in i["members"]:
                        self.assertIn(mem["name"], allowed)
                        self.assertGreaterEqual(mem["peak_alt"], MIN_ALT)
        self.assertFalse(any("北極星" in n or "ポラリス" in n for n in allowed))

    def test_planets_match_the_sky_guide_engine(self):
        from skyguide.astro import _planet_altaz
        t = datetime(2026, 12, 15, 23, tzinfo=JST)
        want = _planet_altaz(self.eph, LAT, LON, 0.0, self.ts.from_datetime(t.astimezone(timezone.utc)))
        for name, az, alt in sh._planet_altaz(self.ts, self.eph, LAT, LON, [t]):
            self.assertAlmostEqual(alt[0], float(want[name][1]), places=6)
            self.assertAlmostEqual(az[0], float(want[name][0]), places=6)

    @mock.patch.object(sh, "_next_visible", lambda *a: {})     # 「次に見える月」の計算は省く(時間の節約)
    def test_planets_near_the_sun_are_not_shown(self):
        # 暗い時間帯の中だけで調べるので、薄明の中の惑星は出ない。出ている惑星は太陽から離れている
        shown = 0
        for m in range(1, 13):
            for s in self.guide(2027, m, 10)["slots"]:
                for i in s["items"]:
                    if i["type"] != "planets":
                        continue
                    for mem in i["members"]:
                        t = self.ts.from_datetime(mem["peak_time"].astimezone(timezone.utc))
                        at = self.eph["earth"].at(t)
                        sep = at.observe(self.eph["sun"]).apparent().separation_from(
                            at.observe(self.eph[dict(sh.PLANETS)[mem["name"]]]).apparent()).degrees
                        self.assertGreater(sep, 18.0 + MIN_ALT - 1.0)
                        shown += 1
        self.assertGreater(shown, 10)

    def test_shower_dates(self):
        # よく知られた極大の日(日本時間)と1日以内で合うこと
        known = {"ペルセウス座流星群": (datetime(2026, 8, 1, tzinfo=JST), date(2026, 8, 12), date(2026, 8, 13)),
                 "ふたご座流星群": (datetime(2026, 12, 1, tzinfo=JST), date(2026, 12, 13), date(2026, 12, 15)),
                 "しぶんぎ座流星群": (datetime(2026, 12, 25, tzinfo=JST), date(2027, 1, 3), date(2027, 1, 4))}
        by_name = {s["name"]: s for s in sh.load_showers()}
        for name, (start, lo, hi) in known.items():
            peak = sh.shower_peak(self.ts, self.eph, by_name[name]["solar_longitude_deg"], start, 30)
            self.assertIsNotNone(peak, name)
            self.assertTrue(lo - timedelta(days=1) <= peak.date() <= hi + timedelta(days=1), (name, peak))

    def test_shower_peak_is_the_requested_longitude(self):
        for s in sh.load_showers():
            lon = s["solar_longitude_deg"]
            hits = [p for k in range(13) if (p := sh.shower_peak(self.ts, self.eph, lon,
                                                                 datetime(2026, 1, 1, tzinfo=JST) + timedelta(days=28 * k), 28))]
            self.assertEqual(len(hits), 1, s["name"])
            self.assertLess(abs(sh._signed(sh.solar_longitude(self.ts, self.eph, hits[0]) - lon)), 0.01)
        with self.assertRaises(ValueError):
            sh.shower_peak(self.ts, self.eph, 10.0, datetime(2026, 1, 1, tzinfo=JST), 366)

    def test_only_within_30_days(self):
        names = [s["name"] for s in sh.upcoming_showers(ex, self.ts, self.eph, LAT, LON, datetime(2026, 11, 24, 9, tzinfo=JST))]
        self.assertEqual(names, ["ふたご座流星群"])
        names = [s["name"] for s in sh.upcoming_showers(ex, self.ts, self.eph, LAT, LON, datetime(2026, 12, 8, 9, tzinfo=JST))]
        self.assertEqual(names, ["ふたご座流星群", "しぶんぎ座流星群"])
        self.assertEqual(sh.upcoming_showers(ex, self.ts, self.eph, LAT, LON, datetime(2027, 2, 1, 9, tzinfo=JST)), [])

    def test_shower_night_is_where_the_radiant_is_up(self):
        # しぶんぎ座(極大は1月4日の昼): 放射点が高いのは明け方なので、1月3日の夜
        q = sh.upcoming_showers(ex, self.ts, self.eph, LAT, LON, datetime(2026, 12, 25, 9, tzinfo=JST))[0]
        self.assertEqual((q["name"], q["night_date"]), ("しぶんぎ座流星群", date(2027, 1, 3)))
        self.assertGreater(q["radiant_start"], datetime(2027, 1, 4, 0, 0, tzinfo=JST))
        self.assertTrue(0.0 <= q["moon_illuminated_fraction"] <= 1.0)

    def test_no_darkness(self):
        g = sh.build(ex, self.ts, self.eph, LAT, LON, date(2026, 11, 24), None, None, datetime(2026, 11, 24, 9, tzinfo=JST), MIN_ALT)
        self.assertEqual((g["slots"], g["not_visible"]), ([], []))

    def test_values_can_become_json(self):
        import explore_json as ej
        text = json.dumps(ej.json_value(self.guide(2026, 11, 24)), ensure_ascii=False, allow_nan=False)
        self.assertIn("slots", text)


if __name__ == "__main__":
    unittest.main()
