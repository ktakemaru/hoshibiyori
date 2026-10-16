"""docs/examples の訂正例(手本)のテスト。通信しない。

senjogahara_..._corrected.json は「時刻の言い回しだけ訂正した版」(読み取り専用)。
senjogahara_..._corrected_v2.json は、そのうえで数値(高度・方位表の稜線の仰角)の食い違いも直した手本。
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
from skyguide.render import render_html  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "sky_guide"
EX = ROOT / "docs" / "examples"
DATA = FIX / "senjogahara_20261009_data.json"
CORRECTED = EX / "senjogahara_20261009_commentary_corrected.json"
V2 = EX / "senjogahara_20261009_commentary_corrected_v2.json"


def _load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def _diff(x, y, p=""):
    if isinstance(x, dict):
        for k in x:
            yield from _diff(x[k], y[k], p + "." + k)
    elif isinstance(x, list):
        for i, (u, v) in enumerate(zip(x, y)):
            yield from _diff(u, v, p + f"[{i}]")
    elif x != y:
        yield p


class CorrectedV2Test(unittest.TestCase):
    def setUp(self):
        self.data = _load(DATA)
        self.v2 = _load(V2)

    def test_v2_has_no_time_phrase_findings(self):
        self.assertEqual(check_text(self.data, self.v2), [])

    def test_v2_has_no_numeric_errors_or_warnings(self):
        self.assertEqual(check_numbers(self.data, self.v2), [])
        self.assertEqual(check_all(self.data, self.v2), [])

    def test_v2_differs_from_corrected_only_in_the_fixed_places(self):
        self.assertEqual(
            list(_diff(_load(CORRECTED), self.v2)),
            [".cards[0].body", ".cards[1].body", ".cards[2].body", ".cards[4].list[0]", ".cards[5].body", ".cards[5].list[0]",
             ".directions[0].elevation", ".directions[1].elevation",
             ".directions[2].elevation", ".directions[5].elevation", ".directions[7].elevation"])

    def test_v2_has_same_structure_as_corrected(self):
        c = _load(CORRECTED)
        self.assertEqual(len(c["cards"]), len(self.v2["cards"]))
        self.assertEqual(len(c["directions"]), len(self.v2["directions"]))
        self.assertEqual(c["tips"], self.v2["tips"])

    def test_v2_is_renderable(self):
        render_html(self.data, self.v2)

    def test_v2_passes_strict_numbers_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "scripts" / "render_sky_guide.py"), "--data", str(DATA),
                                "--commentary", str(V2), "--out", str(Path(tmp) / "o.html"), "--strict-numbers"],
                               capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stderr.strip(), "")


class OriginalCorrectedStaysAsIsTest(unittest.TestCase):
    def test_original_corrected_only_passes_the_time_phrase_check(self):
        """旧い訂正例は時刻の言い回しだけ訂正した版として残してある(数値の食い違いは v2 で直した)。"""
        self.assertEqual(check_text(_load(DATA), _load(CORRECTED)), [])


if __name__ == "__main__":
    unittest.main()
