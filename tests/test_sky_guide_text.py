"""解説の時刻の言い回しの機械照合(skyguide/check_text.py)のテスト。通信しない。"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from skyguide.check_text import check_sentence, check_text, phrase_matches  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "sky_guide"
CORRECTED = ROOT / "docs" / "examples" / "senjogahara_20261009_commentary_corrected.json"


def _load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def _ev(name, start=None, end=None, rises=True, sets=False):
    return {"type": "planet_above_ridge", "name": name, "start": start or "00:00", "end": end or "04:18",
            "rises_over_ridge": rises, "sets_behind_ridge": sets}


class PhraseRuleTest(unittest.TestCase):
    def test_sugi_is_0_to_29_minutes_after(self):
        self.assertTrue(phrase_matches("sugi", ("1",), "01:00"))
        self.assertTrue(phrase_matches("sugi", ("1",), "01:29"))
        self.assertFalse(phrase_matches("sugi", ("1",), "01:30"))
        self.assertFalse(phrase_matches("sugi", ("1",), "01:57"))  # 見本の木星: 「1時すぎ」ではない
        self.assertFalse(phrase_matches("sugi", ("1",), "00:59"))

    def test_mae_is_up_to_30_minutes_before(self):
        self.assertTrue(phrase_matches("mae", ("2",), "01:57"))  # 木星は「2時前」
        self.assertTrue(phrase_matches("mae", ("2",), "01:30"))
        self.assertFalse(phrase_matches("mae", ("2",), "01:29"))
        self.assertFalse(phrase_matches("mae", ("2",), "02:00"))
        self.assertTrue(phrase_matches("mae", ("1",), "00:53"))  # 火星は「1時前」

    def test_goro_dai_and_minute(self):
        self.assertTrue(phrase_matches("goro", ("3",), "03:30"))
        self.assertTrue(phrase_matches("goro", ("3",), "02:30"))
        self.assertFalse(phrase_matches("goro", ("3",), "03:31"))
        self.assertTrue(phrase_matches("dai", ("3",), "03:59"))
        self.assertFalse(phrase_matches("dai", ("3",), "04:00"))
        self.assertTrue(phrase_matches("minute", ("23", "20"), "23:13"))
        self.assertFalse(phrase_matches("minute", ("23", "20"), "23:09"))

    def test_midnight_wraps(self):
        self.assertTrue(phrase_matches("mae", ("0",), "23:50"))
        self.assertTrue(phrase_matches("sugi", ("0",), "00:10"))
        self.assertTrue(phrase_matches("goro", ("0",), "23:45"))
        self.assertFalse(phrase_matches("sugi", ("0",), "23:50"))


class SentenceTest(unittest.TestCase):
    def test_two_objects_in_one_sentence_are_paired_by_clause(self):
        ev = [_ev("火星", "00:53"), _ev("木星", "01:57")]
        bad = check_sentence("火星は0時すぎ、木星は1時すぎに東から昇ります。", ev, "t")
        self.assertEqual({(f.name, f.phrase) for f in bad}, {("火星", "0時すぎ"), ("木星", "1時すぎ")})
        self.assertEqual(check_sentence("火星は1時前、木星は2時前に東から昇ります。", ev, "t"), [])
        self.assertEqual(check_sentence("1時前に火星、2時前に木星が昇ります。", ev, "t"), [])

    def test_set_uses_end_and_rise_uses_start(self):
        ev = [{"type": "gc_above_ridge", "name": "天の川の中心", "start": "18:40", "end": "20:09",
               "rises_over_ridge": False, "sets_behind_ridge": True}]
        self.assertEqual(check_sentence("天の川の中心部は20時過ぎに稜線に隠れます。", ev, "t"), [])
        self.assertEqual(len(check_sentence("天の川の中心部は21時すぎに稜線に隠れます。", ev, "t")), 1)
        self.assertEqual(len(check_sentence("天の川の中心部は20時すぎに昇ります。", ev, "t")), 1)  # 昇る出来事は無い

    def test_orion_belt_alias_and_minute_phrase(self):
        ev = [_ev("アルニタク", "23:20"), _ev("アルニラム", "23:13"), _ev("ミンタカ", "23:30")]
        self.assertEqual(check_sentence("23時20分ごろ、三つ星が山の稜線から顔を出し始めます。", ev, "t"), [])
        self.assertEqual(len(check_sentence("22時20分ごろ、三つ星が山の稜線から顔を出し始めます。", ev, "t")), 1)

    def test_not_checked_when_nothing_to_check(self):
        ev = [_ev("火星", "00:53")]
        self.assertEqual(check_sentence("0時すぎは冷え込みます。", ev, "t"), [])  # 天体なし
        self.assertEqual(check_sentence("火星が0時すぎに明るく見えます。", ev, "t"), [])  # 昇る・沈む等の動詞なし
        self.assertEqual(check_sentence("シリウスは0時すぎに昇ります。", ev, "t"), [])  # eventsにない天体は照合できない
        self.assertEqual(check_sentence("21時に南東の高度43°です。火星が昇ります。", ev, "t"), [])  # 「N時に」は対象外


class GoldenRegressionTest(unittest.TestCase):
    def setUp(self):
        self.data = _load(FIX / "senjogahara_20261009_data.json")
        self.golden = _load(FIX / "senjogahara_20261009_commentary.json")
        self.corrected = _load(CORRECTED)

    def test_sample_one_oclock_claim_is_detected(self):
        f = check_text(self.data, self.golden)
        self.assertIn(("木星", "1時すぎ"), {(x.name, x.phrase) for x in f})
        self.assertIn(("火星", "0時すぎ"), {(x.name, x.phrase) for x in f})
        self.assertEqual(len(f), 5)  # 火星3か所(構図e・山と方位・撮影メモ)と木星2か所(山と方位・撮影メモ)。他の文は誤検出しない
        self.assertEqual({x.where for x in f}, {"cards[e].list[1]", "directions[2].sky", "tips[5].body"})
        self.assertIn("01:57", str(f[0]) + str(f[1]) + str(f[2]) + str(f[3]) + str(f[4]))

    def test_corrected_example_passes(self):
        self.assertEqual(check_text(self.data, self.corrected), [])

    def test_corrected_differs_from_golden_only_in_the_three_sentences(self):
        def diff(x, y, p=""):
            if isinstance(x, dict):
                for k in x:
                    yield from diff(x[k], y[k], p + "." + k)
            elif isinstance(x, list):
                for i, (u, v) in enumerate(zip(x, y)):
                    yield from diff(u, v, p + f"[{i}]")
            elif x != y:
                yield p
        self.assertEqual(list(diff(self.golden, self.corrected)), [".cards[4].list[1]", ".directions[2].sky", ".tips[5].body"])

    def test_corrected_example_is_renderable(self):
        from skyguide.render import render_html
        render_html(self.data, self.corrected)


class CliTest(unittest.TestCase):
    def _run(self, script, *args):
        return subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "scripts" / script), *args], capture_output=True, text=True, encoding="utf-8")

    def test_check_cli_exit_codes(self):
        d = str(FIX / "senjogahara_20261009_data.json")
        self.assertEqual(self._run("check_sky_guide_text.py", "--data", d, "--commentary", str(FIX / "senjogahara_20261009_commentary.json")).returncode, 1)
        self.assertEqual(self._run("check_sky_guide_text.py", "--data", d, "--commentary", str(CORRECTED)).returncode, 0)

    def test_render_blocks_on_mismatch_unless_disabled(self):
        d, c = str(FIX / "senjogahara_20261009_data.json"), str(FIX / "senjogahara_20261009_commentary.json")
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "o.html"
            r = self._run("render_sky_guide.py", "--data", d, "--commentary", c, "--out", str(out))
            self.assertEqual(r.returncode, 1)
            self.assertFalse(out.exists())
            self.assertIn("1時すぎ", r.stderr)
            r = self._run("render_sky_guide.py", "--data", d, "--commentary", c, "--out", str(out), "--no-check-text")
            self.assertEqual(r.returncode, 0)
            self.assertTrue(out.exists())
            out2 = Path(tmp) / "o2.html"
            self.assertEqual(self._run("render_sky_guide.py", "--data", d, "--commentary", str(CORRECTED), "--out", str(out2)).returncode, 0)


if __name__ == "__main__":
    unittest.main()
