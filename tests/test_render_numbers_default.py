"""render_sky_guide.py の数値の食い違いの既定(止める)と --warn-numbers・--strict-numbers のテスト。通信しない。"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "fixtures" / "sky_guide"
EX = ROOT / "docs" / "examples"
MZ_DATA = FIX / "mizugaki_20261017_data.json"
MZ_BEFORE = FIX / "mizugaki_20261017_commentary.before_fix.json"
MZ_FIXED = FIX / "mizugaki_20261017_commentary.json"
SJ_DATA = FIX / "senjogahara_20261009_data.json"
SJ_GOLDEN = FIX / "senjogahara_20261009_commentary.json"
SJ_V2 = EX / "senjogahara_20261009_commentary_corrected_v2.json"


def _run(*args):
    return subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "scripts" / "render_sky_guide.py"), *args],
                          capture_output=True, text=True, encoding="utf-8")


class DefaultBlocksNumbersTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def render(self, data, comm, name, *flags):
        out = self.tmp / name
        r = _run("--data", str(data), "--commentary", str(comm), "--out", str(out), *flags)
        return r, out

    def test_default_blocks_numeric_errors_and_writes_nothing(self):
        r, out = self.render(MZ_DATA, MZ_BEFORE, "a.html")
        self.assertEqual(r.returncode, 1)
        self.assertFalse(out.exists())
        self.assertIn("[エラー] [cards[b].body] (altitude)", r.stderr)
        self.assertIn("(vague_time)", r.stderr)
        self.assertIn("数値JSONと合いません", r.stderr)

    def test_warn_numbers_shows_warnings_and_renders(self):
        r, out = self.render(MZ_DATA, MZ_BEFORE, "b.html", "--warn-numbers")
        self.assertEqual(r.returncode, 0)
        self.assertTrue(out.exists())
        self.assertNotIn("[エラー]", r.stderr)
        self.assertIn("[警告] [cards[b].body] (altitude)", r.stderr)

    def test_strict_numbers_is_accepted_and_does_nothing(self):
        r0, _ = self.render(MZ_DATA, MZ_BEFORE, "c0.html")
        r1, out1 = self.render(MZ_DATA, MZ_BEFORE, "c1.html", "--strict-numbers")
        self.assertEqual((r0.returncode, r0.stderr), (r1.returncode, r1.stderr))  # 既定と同じ結果
        self.assertFalse(out1.exists())
        f0, o0 = self.render(MZ_DATA, MZ_FIXED, "d0.html")
        f1, o1 = self.render(MZ_DATA, MZ_FIXED, "d1.html", "--strict-numbers")
        self.assertEqual((f0.returncode, f1.returncode, f0.stderr, f1.stderr), (0, 0, "", ""))
        self.assertEqual(o0.read_bytes().replace(b"d0.html", b""), o1.read_bytes().replace(b"d1.html", b""))

    def test_warn_numbers_wins_over_strict_numbers(self):
        r, out = self.render(MZ_DATA, MZ_BEFORE, "e.html", "--strict-numbers", "--warn-numbers")
        self.assertEqual(r.returncode, 0)
        self.assertTrue(out.exists())

    def test_warn_numbers_does_not_relax_time_phrase_check(self):
        r, out = self.render(SJ_DATA, SJ_GOLDEN, "f.html", "--warn-numbers")
        self.assertEqual(r.returncode, 1)
        self.assertFalse(out.exists())
        self.assertIn("1時すぎ", r.stderr)

    def test_warning_only_findings_do_not_block_by_default(self):
        comm = json.loads(MZ_FIXED.read_text(encoding="utf-8"))
        comm["lead"] = "細い月が沈みます。" + comm["lead"]
        p = self.tmp / "thin_moon.json"
        p.write_text(json.dumps(comm, ensure_ascii=False), encoding="utf-8")
        r, out = self.render(MZ_DATA, p, "g.html")
        self.assertEqual(r.returncode, 0)
        self.assertTrue(out.exists())
        self.assertIn("[警告] [lead] (moon_adjective)", r.stderr)

    def test_no_check_text_still_skips_everything(self):
        r, out = self.render(MZ_DATA, MZ_BEFORE, "h.html", "--no-check-text")
        self.assertEqual(r.returncode, 0)
        self.assertTrue(out.exists())
        self.assertEqual(r.stderr.strip(), "")

    def test_model_example_v2_renders_by_default_without_messages(self):
        r, out = self.render(SJ_DATA, SJ_V2, "i.html")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(out.exists())
        self.assertEqual(r.stderr.strip(), "")


if __name__ == "__main__":
    unittest.main()
