"""解説の数値の機械照合(skyguide/check_numbers.py)と数値の引き方(skyguide/lookup.py、scripts/sky_lookup.py)のテスト。通信しない。

実データ(2026-10-17 みずがき山自然公園)で実際に起きた誤りを回帰テストにしている:
  before_fix = 誤りを含む解説 / mizugaki_..._commentary.json = 修正後。
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from skyguide.check_numbers import check_all, check_numbers  # noqa: E402
from skyguide.check_text import check_text  # noqa: E402
from skyguide.lookup import compass16, ridge_range  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "sky_guide"
DATA = FIX / "mizugaki_20261017_data.json"
BEFORE = FIX / "mizugaki_20261017_commentary.before_fix.json"
FIXED = FIX / "mizugaki_20261017_commentary.json"


def _load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def _mini_data():
    """方位 i° の稜線が i%10 度、21:20 と 21:40 のフレームを持つ最小の数値JSON。"""
    def frame(alt, moon_illum, moon_alt):
        return {"stars": {"アルタイル": [257.0, alt], "ベガ": [297.0, alt], "シリウス": [110.0, 10.0], "ポラリス(北極星)": [0.5, 36.4]},
                "planets": {"土星": [150.0, 54.0]}, "gc": [220.0, 11.0],
                "moon": {"az": 230.0, "alt": moon_alt, "illum": moon_illum, "phase_angle": 100.0, "waxing": True}}
    return {"times": ["21:20", "21:40"], "frames": [frame(36.0, 0.38, 5.0), frame(32.0, 0.38, -3.0)],
            "horizon_deg": [float(i % 10) for i in range(360)],
            "events": [{"type": "star_above_ridge", "name": "シリウス", "start": "01:04", "end": "04:29",
                        "rises_over_ridge": True, "sets_behind_ridge": False}]}


def _comm(**kw):
    c = {"lead": "", "facts": [], "cards": [{"id": "b", "time": "21:40", "body": ""}], "directions": [], "tips": []}
    c.update(kw)
    return c


def _kinds(findings):
    return [f.kind for f in findings]


class LookupTest(unittest.TestCase):
    def test_compass16_boundaries(self):
        self.assertEqual(compass16(0), "北")
        self.assertEqual(compass16(11.2), "北")
        self.assertEqual(compass16(11.3), "北北東")
        self.assertEqual(compass16(348.8), "北")
        self.assertEqual(compass16(257), "西南西")
        self.assertEqual(compass16(300), "西北西")
        self.assertEqual(compass16(215), "南西")

    def test_ridge_range_wraps_north_and_rounds(self):
        hz = [0.0] * 360
        hz[350], hz[5] = 7.4, 9.5
        self.assertEqual(ridge_range(hz, 345, 15), (0, 10))  # 9.5 は10に丸める
        self.assertEqual(ridge_range(hz, 0, 10), (0, 10))
        self.assertEqual(ridge_range(hz, 345, 359), (0, 7))
        self.assertEqual(ridge_range(hz, 100, 100), (0, 0))

    def test_ridge_range_on_real_data(self):
        hz = _load(DATA)["horizon_deg"]
        self.assertEqual(ridge_range(hz, 345, 15), (7, 10))
        self.assertEqual(ridge_range(hz, 30, 60), (13, 20))
        self.assertEqual(ridge_range(hz, 75, 105), (19, 25))
        self.assertEqual(ridge_range(hz, 165, 195), (3, 6))
        self.assertEqual(ridge_range(hz, 270, 285), (0, 3))
        self.assertEqual(ridge_range(hz, 300, 330), (1, 4))


class RealCaseTest(unittest.TestCase):
    """2026-10-17の実例: 誤りを含む解説で検出され、修正後では検出されない。"""

    def setUp(self):
        self.data = _load(DATA)

    def test_before_fix_is_detected(self):
        f = check_numbers(self.data, _load(BEFORE))
        alt = [x for x in f if x.kind == "altitude"]
        self.assertEqual({x.where for x in alt}, {"cards[b].body"})
        self.assertEqual({x.name for x in alt}, {"アルタイル", "ベガ", "デネブ"})
        self.assertEqual(len(alt), 3)
        ridge = [x for x in f if x.kind == "ridge_range"]
        self.assertEqual(sorted(x.where for x in ridge), [f"directions[{i}].elevation" for i in (0, 1, 2, 4, 6, 7)])  # 北・北東・東・南・西・北西
        vague = [x for x in f if x.kind == "vague_time"]
        self.assertEqual([(x.where, x.name, x.phrase) for x in vague], [("directions[3].sky", "シリウス", "明け方")])  # 南東行
        self.assertIn("01:04", vague[0].message)
        moon = [x for x in f if x.kind == "moon_adjective"]
        self.assertEqual(len(moon), 1)
        self.assertEqual(moon[0].severity, "warning")
        self.assertEqual(sum(x.severity == "error" for x in f), 10)

    def test_before_fix_altitude_message_has_the_right_values(self):
        msgs = " ".join(x.message for x in check_numbers(self.data, _load(BEFORE)) if x.kind == "altitude")
        self.assertIn("21:40", msgs)
        self.assertIn("高度は32°", msgs)
        self.assertIn("高度は56°", msgs)

    def test_fixed_has_no_findings(self):
        self.assertEqual(check_all(self.data, _load(FIXED)), [])

    def test_time_phrase_check_is_unchanged_and_only_time_phrases(self):
        golden = _load(FIX / "senjogahara_20261009_commentary.json")
        f = check_text(_load(FIX / "senjogahara_20261009_data.json"), golden)
        self.assertEqual(len(f), 5)
        self.assertEqual(set(_kinds(f)), {"time_phrase"})
        self.assertEqual(check_text(self.data, _load(BEFORE)), [])  # 時刻の言い回しの誤りはここには無い(だから素通りしていた)


class AltitudeTest(unittest.TestCase):
    def check(self, body, **kw):
        return [f for f in check_numbers(_mini_data(), _comm(cards=[{"id": "b", "time": "21:40", "body": body}], **kw)) if f.kind == "altitude"]

    def test_card_time_is_used_when_no_time_in_text(self):
        self.assertEqual(self.check("アルタイル(西南西の高度32°)が見えます。"), [])
        self.assertEqual(len(self.check("アルタイル(西南西の高度36°)が見えます。")), 1)  # 36°は21:20の値

    def test_text_time_overrides_card_time(self):
        self.assertEqual(self.check("21時20分にはアルタイル(西南西の高度36°)が見えます。"), [])

    def test_tolerance_is_one_degree(self):
        self.assertEqual(self.check("アルタイルは西南西の高度33°にあります。"), [])
        self.assertEqual(self.check("アルタイルは西南西の高度31°にあります。"), [])
        self.assertEqual(len(self.check("アルタイルは西南西の高度34°にあります。")), 1)

    def test_direction_name_must_match(self):
        f = self.check("アルタイルは南西の高度32°にあります。")
        self.assertEqual(len(f), 1)
        self.assertIn("西南西", f[0].message)

    def test_direction_is_optional(self):
        self.assertEqual(self.check("アルタイルは高度32°にあります。"), [])
        self.assertEqual(len(self.check("アルタイルは高度40°にあります。")), 1)

    def test_decimal_altitude(self):
        self.assertEqual(self.check("北極星は真北の高度36.5°にあります。"), [])

    def test_unknown_object_is_not_checked(self):
        self.assertEqual(self.check("カノープスは南の高度2°にあります。"), [])

    def test_wide_time_phrases_are_not_checked(self):
        self.assertEqual(self.check("土星は22時台に南の高度56°に達します。"), [])
        self.assertEqual(self.check("アルタイルは21時すぎに西南西の高度50°です。"), [])

    def test_later_clause_time_is_not_applied_to_an_earlier_clause(self):
        # 前の節(card.time=21:40 → 32°)に、後ろの節の「21時20分」(36°)を使わない
        self.assertEqual(self.check("アルタイルは西南西の高度32°から下がり、21時20分には高度36°でした。"), [])

    def test_no_time_no_check_outside_cards(self):
        c = _comm(tips=[{"title": "x", "body": "アルタイルは西南西の高度50°にあります。"}])
        self.assertEqual([f for f in check_numbers(_mini_data(), c) if f.kind == "altitude"], [])

    def test_single_object_sentence_inherits_name(self):
        f = self.check("アルタイルは21時に西南西の高度36°、21時40分に西南西の高度32°です。")
        self.assertEqual(f, [])

    def test_month_and_moonlight_are_not_the_moon(self):
        self.assertEqual(self.check("10月の月明かりのもと、高度60°の空を撮ります。"), [])


class RidgeRangeTest(unittest.TestCase):
    def check(self, **kw):
        return [f for f in check_numbers(_mini_data(), _comm(**kw)) if f.kind == "ridge_range"]

    def test_label_and_elevation(self):
        ok = {"label": "東 80〜89°", "elevation": "0〜9°", "terrain": "", "sky": ""}
        bad = {"label": "東 80〜89°", "elevation": "1〜9°", "terrain": "", "sky": ""}
        self.assertEqual(self.check(directions=[ok]), [])
        f = self.check(directions=[ok, bad])
        self.assertEqual([x.where for x in f], ["directions[1].elevation"])

    def test_north_wrapping_label(self):
        d = {"label": "北 355〜5°", "elevation": "0〜9°", "terrain": "", "sky": ""}
        self.assertEqual(self.check(directions=[d]), [])

    def test_single_value_elevation(self):
        d = {"label": "東 83〜83°", "elevation": "3°", "terrain": "", "sky": ""}
        self.assertEqual(self.check(directions=[d]), [])

    def test_body_range_is_checked_when_azimuth_range_is_written(self):
        self.assertEqual(self.check(lead="南西(80〜89°)の稜線は0〜9°と低い。"), [])
        f = self.check(lead="南西(80〜89°)の稜線は1〜4°と低い。")
        self.assertEqual(len(f), 1)
        self.assertIn("0〜9°", f[0].message)

    def test_body_without_azimuth_range_is_not_checked(self):
        self.assertEqual(self.check(lead="南西の稜線は1〜4°と低い。"), [])


class VagueTimeTest(unittest.TestCase):
    def check(self, text):
        return [f for f in check_numbers(_mini_data(), _comm(lead=text)) if f.kind == "vague_time"]

    def test_vague_word_with_event_verb_is_flagged(self):
        f = self.check("明け方にシリウスが昇ります。")
        self.assertEqual(len(f), 1)
        self.assertIn("01:04", f[0].message)
        self.assertEqual(len(self.check("夕方、シリウスが沈みます。")), 0)  # 節が分かれていて同じ節に天体名と動詞と曖昧語が揃わない
        self.assertEqual(len(self.check("未明にシリウスが稜線を越えます。")), 1)

    def test_no_verb_is_not_flagged(self):
        self.assertEqual(self.check("明け方のシリウスは高く輝きます。"), [])
        self.assertEqual(self.check("明け方にはシリウスが輝きます。"), [])

    def test_no_object_is_not_flagged(self):
        self.assertEqual(self.check("明け方に霧が出て、太陽が昇ります。"), [])

    def test_digits_are_fine(self):
        self.assertEqual(self.check("シリウスは01:04に稜線を越えます。"), [])


class MoonAdjectiveTest(unittest.TestCase):
    def test_flagged_above_thirty_percent_as_warning(self):
        f = check_numbers(_mini_data(), _comm(lead="細い月が沈みます。"))
        self.assertEqual(_kinds(f), ["moon_adjective"])
        self.assertEqual(f[0].severity, "warning")

    def test_not_flagged_at_or_below_thirty_percent(self):
        d = _mini_data()
        for fr in d["frames"]:
            fr["moon"]["illum"] = 0.30
        self.assertEqual(check_numbers(d, _comm(lead="細い月が沈みます。")), [])

    def test_not_flagged_when_moon_is_never_up(self):
        d = _mini_data()
        for fr in d["frames"]:
            fr["moon"]["alt"] = -20.0
        self.assertEqual(check_numbers(d, _comm(lead="三日月です。")), [])


class CliTest(unittest.TestCase):
    def _run(self, script, *args):
        return subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "scripts" / script), *args], capture_output=True, text=True, encoding="utf-8")

    def test_sky_lookup_ridge_and_time(self):
        r = self._run("sky_lookup.py", "--data", str(DATA), "--az", "345", "15")
        self.assertEqual(r.returncode, 0)
        self.assertIn("7〜10°", r.stdout)
        r = self._run("sky_lookup.py", "--data", str(DATA), "--time", "21:40", "--names", "アルタイル", "ベガ", "デネブ")
        self.assertEqual(r.returncode, 0)
        self.assertIn("アルタイル: 西南西", r.stdout)
        self.assertIn("高度32°", r.stdout)
        self.assertIn("高度56°", r.stdout)

    def test_sky_lookup_errors(self):
        r = self._run("sky_lookup.py", "--data", str(DATA), "--time", "21:41", "--names", "ベガ")
        self.assertEqual(r.returncode, 1)
        self.assertIn("times にありません", r.stderr)
        r = self._run("sky_lookup.py", "--data", str(DATA), "--time", "21:40", "--names", "カノープス")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(self._run("sky_lookup.py", "--data", str(DATA)).returncode, 2)  # 引数不足

    def test_check_cli_numbers_flag(self):
        d = str(DATA)
        self.assertEqual(self._run("check_sky_guide_text.py", "--data", d, "--commentary", str(BEFORE)).returncode, 0)  # 既定は時刻の言い回しだけ
        r = self._run("check_sky_guide_text.py", "--data", d, "--commentary", str(BEFORE), "--numbers")
        self.assertEqual(r.returncode, 1)
        self.assertIn("(altitude)", r.stdout)
        self.assertIn("[警告]", r.stdout)  # 月の形容は警告
        self.assertEqual(self._run("check_sky_guide_text.py", "--data", d, "--commentary", str(FIXED), "--numbers").returncode, 0)

    def test_render_blocks_by_default_and_warns_with_warn_numbers(self):
        d = str(DATA)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "o.html"
            r = self._run("render_sky_guide.py", "--data", d, "--commentary", str(BEFORE), "--out", str(out))
            self.assertEqual(r.returncode, 1)  # 既定で止まる
            self.assertFalse(out.exists())
            self.assertIn("(altitude)", r.stderr)
            self.assertIn("(ridge_range)", r.stderr)
            r = self._run("render_sky_guide.py", "--data", d, "--commentary", str(BEFORE), "--out", str(out), "--warn-numbers")
            self.assertEqual(r.returncode, 0)  # --warn-numbers は警告を表示するだけで止めない
            self.assertTrue(out.exists())
            self.assertIn("[警告]", r.stderr)
            self.assertIn("(altitude)", r.stderr)
            self.assertNotIn("[エラー]", r.stderr)
            out.unlink()
            r = self._run("render_sky_guide.py", "--data", d, "--commentary", str(BEFORE), "--out", str(out), "--no-check-text")
            self.assertEqual(r.returncode, 0)  # --no-check-text は従来どおり検査をすべて省く
            out2 = Path(tmp) / "o2.html"
            r = self._run("render_sky_guide.py", "--data", d, "--commentary", str(FIXED), "--out", str(out2))
            self.assertEqual(r.returncode, 0)
            self.assertEqual(r.stderr.strip(), "")


if __name__ == "__main__":
    unittest.main()
