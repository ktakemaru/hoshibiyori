"""範囲表現の数値検査(skyguide/check_numbers.py の altitude_range / ridge_range_loose)と、
時間帯の高度の範囲を引く関数(skyguide/lookup.py)・scripts/sky_lookup.py --time-range のテスト。通信しない。"""
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from skyguide.check_numbers import check_all, check_numbers, check_numeric, check_ranges  # noqa: E402
from skyguide.lookup import altitude_range_in_window, frame_minutes  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "sky_guide"
EX = ROOT / "docs" / "examples"
SJ_DATA = FIX / "senjogahara_20261009_data.json"
V2 = EX / "senjogahara_20261009_commentary_corrected_v2.json"
MZ_DATA = FIX / "mizugaki_20261017_data.json"
MZ_BEFORE = FIX / "mizugaki_20261017_commentary.before_fix.json"


def _load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


TIMES = ["23:00", "23:20", "23:40", "00:00", "00:20"]
SUBARU = [40.0, 50.0, 54.0, 58.0, 62.0]
BELOW = [-10.0, -5.0, 5.0, 10.0, 12.0]


def _data():
    frames = []
    for i in range(len(TIMES)):
        frames.append({"stars": {"すばる": [100.0, SUBARU[i]], "リゲル": [110.0, BELOW[i]]}, "planets": {}, "gc": [220.0, 10.0],
                       "moon": {"az": 230.0, "alt": -30.0, "illum": 0.1, "phase_angle": 150.0, "waxing": True}})
    return {"times": TIMES, "frames": frames, "events": [], "horizon_deg": [float(i % 10) for i in range(360)]}


def _card(body="", lst=None, when="23:20〜00:10"):
    return {"id": "e", "when": when, "time": "23:40", "body": body, "list": lst or []}


def _comm(**kw):
    c = {"lead": "", "facts": [], "cards": [_card()], "directions": [], "tips": []}
    c.update(kw)
    return c


def _range_findings(comm, kind="altitude_range"):
    return [f for f in check_ranges(_data(), comm) if f.kind == kind]


class WindowLookupTest(unittest.TestCase):
    def test_minutes_cross_midnight(self):
        self.assertEqual(frame_minutes(_data()), [1380, 1400, 1420, 1440, 1460])

    def test_range_with_interpolated_end_across_midnight(self):
        # 23:20=50, 23:40=54, 00:00=58, 00:10=(58+62)/2=60
        self.assertEqual(altitude_range_in_window(_data(), "すばる", "23:20", "00:10"), (50, 60))

    def test_interpolated_start(self):
        # 23:10=(40+50)/2=45, 23:30=52
        self.assertEqual(altitude_range_in_window(_data(), "すばる", "23:10", "23:30"), (45, 52))

    def test_exact_frame_times_and_single_point(self):
        self.assertEqual(altitude_range_in_window(_data(), "すばる", "23:20", "23:40"), (50, 54))
        self.assertEqual(altitude_range_in_window(_data(), "すばる", "23:40", "23:40"), (54, 54))

    def test_below_horizon_is_clamped_to_zero(self):
        # -10→-5 は両端とも0°に切る。00:00=10, 00:20=12 と合わせて 0〜12
        self.assertEqual(altitude_range_in_window(_data(), "リゲル", "23:00", "00:20"), (0, 12))
        self.assertEqual(altitude_range_in_window(_data(), "リゲル", "23:00", "23:20"), (0, 0))

    def test_outside_frames_or_unknown_object_is_none(self):
        self.assertIsNone(altitude_range_in_window(_data(), "すばる", "10:00", "11:00"))
        self.assertIsNone(altitude_range_in_window(_data(), "すばる", "23:20", "01:00"))
        self.assertIsNone(altitude_range_in_window(_data(), "カノープス", "23:20", "00:10"))

    def test_real_data_values(self):
        d = _load(SJ_DATA)
        self.assertEqual(altitude_range_in_window(d, "すばる", "23:20", "00:10"), (50, 60))
        self.assertEqual(altitude_range_in_window(d, "木星", "02:30", "04:00"), (14, 32))
        self.assertEqual(altitude_range_in_window(d, "土星", "18:40", "19:40"), (18, 30))


class AltitudeRangeTest(unittest.TestCase):
    def test_matching_range_with_card_when(self):
        self.assertEqual(_range_findings(_comm(cards=[_card(lst=["上方にすばる(高度50〜60°)が続きます。"])])), [])

    def test_wrong_range_is_flagged(self):
        f = _range_findings(_comm(cards=[_card(lst=["上方にすばる(高度46〜58°)が続きます。"])]))
        self.assertEqual(len(f), 1)
        self.assertEqual((f[0].kind, f[0].severity, f[0].name), ("altitude_range", "error", "すばる"))
        self.assertEqual(f[0].where, "cards[e].list[0]")
        self.assertIn("50〜60°", f[0].message)
        self.assertIn("23:20〜00:10", f[0].message)
        self.assertIn("--time-range 23:20 00:10 --names すばる", f[0].message)

    def test_tolerance_is_one_degree_for_each_end(self):
        ok = lambda a, b: _range_findings(_comm(cards=[_card(body=f"すばるは高度{a}〜{b}°です。")]))  # noqa: E731
        self.assertEqual(ok(49, 61), [])
        self.assertEqual(ok(51, 59), [])
        self.assertEqual(len(ok(48, 60)), 1)
        self.assertEqual(len(ok(50, 62)), 1)
        self.assertEqual(len(ok(50, 58)), 1)

    def test_separator_variants(self):
        for sep in ("〜", "~", "～"):
            self.assertEqual(_range_findings(_comm(cards=[_card(body=f"すばるは高度50{sep}60°です。")])), [])
            self.assertEqual(len(_range_findings(_comm(cards=[_card(body=f"すばるは高度40{sep}60°です。")]))), 1)

    def test_when_not_a_time_range_is_not_checked(self):
        self.assertEqual(_range_findings(_comm(cards=[_card(body="すばるは高度10〜20°です。", when="終夜")])), [])
        self.assertEqual(_range_findings(_comm(cards=[_card(body="すばるは高度10〜20°です。", when="")])), [])

    def test_non_card_text_without_times_is_not_checked(self):
        self.assertEqual(_range_findings(_comm(lead="すばるは高度10〜20°です。")), [])
        self.assertEqual(_range_findings(_comm(tips=[{"title": "x", "body": "すばるは高度10〜20°です。"}])), [])

    def test_two_times_in_the_clause_define_the_window(self):
        self.assertEqual(_range_findings(_comm(lead="23時20分から0時10分のすばる(高度50〜60°)")), [])
        f = _range_findings(_comm(lead="23時20分から0時10分のすばる(高度40〜60°)"))
        self.assertEqual(len(f), 1)
        self.assertIn("23:20〜00:10", f[0].message)
        # 2つの時刻は when より優先する
        self.assertEqual(_range_findings(_comm(cards=[_card(body="23時10分から23時30分のすばる(高度45〜52°)", when="23:20〜00:10")])), [])

    def test_a_single_time_in_the_clause_is_not_checked(self):
        self.assertEqual(_range_findings(_comm(lead="23時20分のすばる(高度10〜20°)")), [])

    def test_time_in_another_clause_is_not_applied(self):
        # 同じ文の別の節に時刻がある → 時間帯が決まらないので検査しない(when も使わない)
        self.assertEqual(_range_findings(_comm(cards=[_card(body="23時40分に、すばる(高度10〜20°)が見えます。")])), [])

    def test_wide_time_phrase_clause_is_not_checked(self):
        self.assertEqual(_range_findings(_comm(cards=[_card(body="23時台のすばるは高度10〜20°です。")])), [])
        self.assertEqual(_range_findings(_comm(lead="23時すぎから0時前のすばるは高度10〜20°です。")), [])

    def test_no_name_unknown_name_or_name_after_range_is_not_checked(self):
        for text in ("高度10〜20°あります。", "カノープスは高度10〜20°です。", "高度10〜20°のすばるが見えます。"):
            self.assertEqual(_range_findings(_comm(cards=[_card(body=text)])), [], text)

    def test_sentence_name_is_not_inherited_by_a_clause_without_a_name(self):
        self.assertEqual(_range_findings(_comm(cards=[_card(body="東の稜線は高度10〜20°と高く、すばるが昇ります。")])), [])

    def test_terrain_height_after_a_name_is_not_checked(self):
        self.assertEqual(_range_findings(_comm(cards=[_card(body="すばるの下の東の稜線は高度10〜20°あります。")])), [])

    def test_non_altitude_ranges_are_not_picked_up(self):
        for text in ("すばるの方向は雲量20〜30%です。", "すばるは約20〜30分で昇ります。", "すばるは方位90〜100°にあります。"):
            self.assertEqual(_range_findings(_comm(cards=[_card(body=text)])), [], text)

    def test_reversed_range_is_not_checked(self):
        self.assertEqual(_range_findings(_comm(cards=[_card(body="すばるは高度60〜50°です。")])), [])

    def test_window_outside_the_night_is_not_checked(self):
        self.assertEqual(_range_findings(_comm(cards=[_card(body="すばるは高度10〜20°です。", when="10:00〜11:00")])), [])

    def test_single_altitude_check_is_not_triggered_by_ranges(self):
        c = _comm(cards=[_card(body="すばるは高度50〜60°です。")])
        self.assertEqual([f for f in check_numbers(_data(), c)], [])


class LooseRidgeTest(unittest.TestCase):
    def rows(self, *labels):
        return [{"label": l, "elevation": "0〜9°", "terrain": "", "sky": ""} for l in labels]

    def loose(self, lead, *labels):
        return _range_findings(_comm(lead=lead, directions=self.rows(*labels)), "ridge_range_loose")

    def test_matching_and_wrong(self):
        # 130〜140° の horizon は 0〜9
        self.assertEqual(self.loose("南東〜南は稜線が0〜9°と低い。", "南東〜南 130〜140°"), [])
        f = self.loose("南東〜南は稜線が1〜3°と低い。", "南東〜南 130〜140°")
        self.assertEqual(len(f), 1)
        self.assertEqual((f[0].kind, f[0].severity), ("ridge_range_loose", "error"))
        self.assertIn("南東〜南 130〜140°", f[0].message)
        self.assertIn("0〜9°", f[0].message)

    def test_single_name_and_particles(self):
        self.assertEqual(self.loose("東の稜線は0〜9°です。", "東 80〜89°"), [])
        self.assertEqual(len(self.loose("東の稜線は高度1〜9°です。", "東 80〜89°")), 1)
        self.assertEqual(len(self.loose("東の稜線が1〜9°です。", "東 80〜89°")), 1)

    def test_single_value(self):
        self.assertEqual(len(self.loose("東の稜線は4°です。", "東 83〜83°")), 1)  # 83°は3
        self.assertEqual(self.loose("東の稜線は3°です。", "東 83〜83°"), [])

    def test_no_row_or_several_rows_with_the_same_name_is_not_checked(self):
        self.assertEqual(self.loose("南西の稜線は1〜4°です。", "東 80〜89°"), [])
        self.assertEqual(self.loose("東の稜線は1〜4°です。", "東 80〜89°", "東 90〜99°"), [])

    def test_name_must_match_exactly(self):
        # 「南東〜南」の行に対して「南東」だけの言及は、別の方位名として検査しない
        self.assertEqual(self.loose("南東の稜線は1〜3°です。", "南東〜南 130〜140°"), [])

    def test_text_with_azimuth_range_is_left_to_the_existing_check(self):
        c = _comm(lead="南東(130〜140°)の稜線は1〜3°です。", directions=self.rows("南東 130〜140°"))
        self.assertEqual([f for f in check_ranges(_data(), c)], [])  # 二重に指摘しない
        self.assertEqual([f.kind for f in check_numbers(_data(), c)], ["ridge_range"])

    def test_text_without_a_number_is_not_checked(self):
        self.assertEqual(self.loose("東の稜線は低く開けています。", "東 80〜89°"), [])
        self.assertEqual(self.loose("東の稜線(約4°)の上にあります。", "東 80〜89°"), [])


class RegressionTest(unittest.TestCase):
    def test_v2_has_no_findings(self):
        d = _load(SJ_DATA)
        self.assertEqual(check_ranges(d, _load(V2)), [])
        self.assertEqual(check_all(d, _load(V2)), [])

    def test_before_fix_existing_detections_are_unchanged(self):
        d, c = _load(MZ_DATA), _load(MZ_BEFORE)
        old = check_numbers(d, c)
        self.assertEqual(len(old), 11)  # 高度3・方位表6・曖昧語1・月の形容1(警告)
        self.assertEqual(sum(f.severity == "error" for f in old), 10)
        self.assertEqual([f.kind for f in check_numeric(d, c)][:11], [f.kind for f in old])  # 既存の指摘が先頭に同じ順で残る
        self.assertEqual({f.kind for f in check_ranges(d, c)}, {"ridge_range_loose"})

    def test_check_numbers_never_returns_the_new_kinds(self):
        for comm in (_load(V2), _load(MZ_BEFORE), _load(FIX / "senjogahara_20261009_commentary.json")):
            for data in (_load(SJ_DATA), _load(MZ_DATA)):
                self.assertFalse({f.kind for f in check_numbers(data, comm)} & {"altitude_range", "ridge_range_loose"})


class SkyLookupCliTest(unittest.TestCase):
    def _run(self, *args):
        return subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "scripts" / "sky_lookup.py"), *args], capture_output=True, text=True, encoding="utf-8")

    def test_time_range(self):
        r = self._run("--data", str(SJ_DATA), "--time-range", "23:20", "00:10", "--names", "すばる")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("23:20〜00:10 すばる: 高度50〜60°", r.stdout)
        r = self._run("--data", str(SJ_DATA), "--time-range", "02:30", "04:00", "--names", "木星", "火星")
        self.assertIn("木星: 高度14〜32°", r.stdout)
        self.assertIn("火星: 高度28〜46°", r.stdout)

    def test_time_range_errors(self):
        r = self._run("--data", str(SJ_DATA), "--time-range", "10:00", "11:00", "--names", "木星")
        self.assertEqual(r.returncode, 1)
        self.assertIn("出せません", r.stderr)
        self.assertEqual(self._run("--data", str(SJ_DATA), "--time-range", "23:20", "00:10").returncode, 1)

    def test_combines_with_other_options(self):
        r = self._run("--data", str(SJ_DATA), "--az", "130", "200", "--time-range", "23:20", "00:10", "--names", "すばる")
        self.assertEqual(r.returncode, 0)
        self.assertIn("1〜4°", r.stdout)
        self.assertIn("高度50〜60°", r.stdout)


if __name__ == "__main__":
    unittest.main()
