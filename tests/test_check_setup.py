"""scripts/check_setup.py の単体テスト(ネットワーク不使用)。"""
import contextlib
import importlib.util
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_PATH = Path(__file__).resolve().parent.parent / "scripts" / "check_setup.py"
_spec = importlib.util.spec_from_file_location("check_setup", _PATH)
cs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cs)


def _run(**kw):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = cs.run(**kw)
    return code, buf.getvalue()


class CheckSetupTest(unittest.TestCase):
    def test_python_versions(self):
        self.assertEqual(cs.check_python((3, 15, 0))[0], "OK")
        self.assertEqual(cs.check_python((3, 13, 1))[0], "WARN")
        self.assertEqual(cs.check_python((3, 12, 0))[0], "NG")

    def test_missing_required_package_exits_1(self):
        real = cs.check_import
        with mock.patch.object(cs, "check_import", side_effect=lambda m: False if m == "numpy" else real(m)):
            code, out = _run()
        self.assertEqual(code, 1)
        self.assertIn("numpy", out)

    def test_missing_optional_and_ephemeris_only_warn(self):
        real = cs.check_import
        with mock.patch.object(cs, "check_import", side_effect=lambda m: False if m == "playwright" else real(m)), \
             mock.patch.object(cs, "EPHEMERIS", Path("no_such_dir") / "de421.bsp"):
            code, out = _run()
        self.assertEqual(code, 0)
        self.assertIn("自動ダウンロード", out)

    def test_not_writable_exits_1(self):
        with mock.patch.object(cs, "check_writable", return_value=False):
            code, _ = _run()
        self.assertEqual(code, 1)

    def test_check_writable_does_not_create_dirs(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "a" / "b"
            self.assertTrue(cs.check_writable(target))
            self.assertFalse((Path(d) / "a").exists())

    def test_default_run_makes_no_network_call(self):
        with mock.patch("requests.get", side_effect=AssertionError("network used")):
            _run()

    def test_network_flag_sends_one_request_and_429_is_ng(self):
        resp = mock.Mock(status_code=429, ok=False)
        with mock.patch("requests.get", return_value=resp) as g:
            code, out = _run(network=True)
        self.assertEqual(g.call_count, 1)
        self.assertEqual(code, 1)
        self.assertIn("429", out)


if __name__ == "__main__":
    unittest.main()
