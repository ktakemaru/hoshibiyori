"""HOSHIBIYORI_DATA_DIR(保存先の切り替え)の単体テスト。通信しない。

未設定・空文字なら従来(ROOT基準)と同一、設定すればその下になること。各モジュールの定数は、環境変数を設定した
別プロセスで import して確かめる(import時に決まるため)。
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import hb_paths  # noqa: E402

ENV = hb_paths.ENV_VAR

_PROBE = r"""
import json, sys
from pathlib import Path
root = Path(sys.argv[1])
sys.path.insert(0, str(root))
for sub in ["step1_astronomy", "step2_terrain", "step3_light_pollution", "step4_moonlight", "step5_cloud_forecast", "scripts"]:
    sys.path.insert(0, str(root / sub))
import grid_cache, himawari_image, jma_weather_map
import generate_report as gr
from skyguide import astro
import moon_nights, check_setup
import weekend_page as wp
print(json.dumps({
    "cloud_cache": str(grid_cache._DEFAULT_CACHE_DIR),
    "himawari_cache": str(himawari_image.DEFAULT_CACHE_DIR),
    "weather_map_cache": str(jma_weather_map.DEFAULT_OUT_DIR),
    "report_html": str(gr.OUTPUT_PATH),
    "commentary": str(gr.WEATHER_MAP_COMMENTARY_PATH),
    "ephemeris_skyguide": str(astro.EPHEMERIS_PATH),
    "ephemeris_moon": str(moon_nights.EPHEMERIS_PATH),
    "ephemeris_check": str(check_setup.EPHEMERIS),
    "weekend_weather_root": str(wp.WEATHER_ROOT),
    "default_roots": [str(gr.load_weather_map_commentary.__defaults__[1]), str(gr.collect_weather_map.__defaults__[1]),
                      str(gr.render_weather_map_section.__defaults__[2])],
    "static_root": str(gr.ROOT),
}))
"""

# 定数名 → DATA_ROOT からの相対パス
EXPECTED = {
    "cloud_cache": "step5_cloud_forecast/cloud_cache",
    "himawari_cache": "step5_cloud_forecast/himawari_cache",
    "weather_map_cache": "step5_cloud_forecast/weather_map_cache",
    "report_html": "report.html",
    "commentary": "weather_map_commentary.json",
    "ephemeris_skyguide": "step1_astronomy/de421.bsp",
    "ephemeris_moon": "step1_astronomy/de421.bsp",
    "ephemeris_check": "step1_astronomy/de421.bsp",
}


def _env(value):
    e = {k: v for k, v in os.environ.items() if k != ENV}
    if value is not None:
        e[ENV] = value
    return e


def _probe(value):
    r = subprocess.run([sys.executable, "-X", "utf8", "-c", _PROBE, str(ROOT)], capture_output=True, text=True,
                       encoding="utf-8", env=_env(value), cwd=str(ROOT))
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def _same(a, b):
    return Path(a).resolve() == Path(b).resolve()


class ResolveTest(unittest.TestCase):
    def test_unset_is_root(self):
        self.assertEqual(hb_paths.resolve_data_root(env={}), hb_paths.ROOT)

    def test_empty_and_blank_are_unset(self):
        for v in ("", "   "):
            with self.subTest(v=v):
                self.assertEqual(hb_paths.resolve_data_root(env={ENV: v}), hb_paths.ROOT)

    def test_set_is_resolved_path(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(hb_paths.resolve_data_root(env={ENV: d}), Path(d).resolve())

    def test_tilde_is_expanded(self):
        self.assertEqual(hb_paths.resolve_data_root(env={ENV: "~"}), Path.home().resolve())

    def test_default_is_used_only_when_unset(self):
        fallback = Path("somewhere")
        self.assertEqual(hb_paths.resolve_data_root(fallback, env={}), fallback)
        self.assertEqual(hb_paths.resolve_data_root(fallback, env={ENV: ""}), fallback)
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(hb_paths.resolve_data_root(fallback, env={ENV: d}), Path(d).resolve())

    def test_import_does_not_create_directory(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "not_yet"
            _probe(str(target))
            self.assertFalse(target.exists())


class ModulePathsTest(unittest.TestCase):
    def check(self, got, base):
        for key, rel in EXPECTED.items():
            self.assertTrue(_same(got[key], Path(base) / rel), f"{key}: {got[key]} (期待 {Path(base) / rel})")
        self.assertTrue(_same(got["weekend_weather_root"], base))
        for p in got["default_roots"]:
            self.assertTrue(_same(p, base), p)
        # 読み取り専用の静的データの基準は、環境変数に関係なくリポジトリ
        self.assertTrue(_same(got["static_root"], ROOT))

    def test_unset_is_same_as_before(self):
        self.check(_probe(None), ROOT)

    def test_empty_string_is_unset(self):
        self.check(_probe(""), ROOT)

    def test_set_goes_under_the_directory(self):
        with tempfile.TemporaryDirectory() as d:
            got = _probe(d)
            self.check(got, Path(d))
            for key in EXPECTED:
                self.assertFalse(_same(got[key], ROOT / EXPECTED[key]), key)


class CliDefaultsTest(unittest.TestCase):
    def run_script(self, value, *argv):
        return subprocess.run([sys.executable, "-X", "utf8", *argv], capture_output=True, text=True, encoding="utf-8",
                              env=_env(value), cwd=str(ROOT))

    def test_report_courses_and_weekend_page_default_report_follows_data_dir(self):
        with tempfile.TemporaryDirectory() as d:
            want = str(Path(d).resolve() / "report.html")
            for script in ("scripts/report_courses.py", "scripts/weekend_page.py"):
                with self.subTest(script=script):
                    r = self.run_script(d, str(ROOT / script))
                    self.assertEqual(r.returncode, 2, r.stderr)
                    self.assertIn(want, r.stderr)

    def test_check_setup_shows_data_dir_and_creates_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            sub = Path(d) / "hb_data"
            r = self.run_script(str(sub), str(ROOT / "scripts" / "check_setup.py"))
            self.assertIn(f"データ領域: {sub.resolve()}", r.stdout)
            self.assertNotIn("未設定", r.stdout)
            self.assertFalse(sub.exists())
        r = self.run_script(None, str(ROOT / "scripts" / "check_setup.py"))
        self.assertIn("未設定: リポジトリ内", r.stdout)


class EphemerisDirTest(unittest.TestCase):
    """データ領域が空(step1_astronomy/ が無い)でも、Skyfield が暦を書く先のフォルダができていること。通信しない。

    Skyfield は保存先のフォルダを作らないため、暦を取得する前に呼び出し側が mkdir する。Skyfield の load を差し替え、
    呼ばれた時点でフォルダが存在し、書き込めることを確かめる(実際のダウンロードはしない)。
    """

    class _Stop(Exception):
        pass

    def _fake_load(self, seen):
        def load(path, *a, **k):
            p = Path(path)
            seen["dir_existed"] = p.parent.is_dir()
            p.write_bytes(b"dummy")      # 保存先に書き込めること
            seen["written"] = p.is_file()
            raise self._Stop()
        fake = mock.MagicMock(side_effect=load)
        return fake

    def test_empty_data_dir_gets_ephemeris_directory(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        import moon_nights as mn
        from skyguide import astro, build
        with tempfile.TemporaryDirectory() as d:
            for label in ("moon_nights", "skyguide.build"):
                with self.subTest(label=label):
                    eph = Path(d) / label / "step1_astronomy" / "de421.bsp"   # フォルダが無い状態
                    self.assertFalse(eph.parent.exists())
                    seen = {}
                    fake = self._fake_load(seen)
                    if label == "moon_nights":
                        with mock.patch.object(mn, "EPHEMERIS_PATH", eph), mock.patch.object(mn, "load", fake):
                            with self.assertRaises(self._Stop):
                                mn.main(["--allow-network", "--days", "1"])
                    else:
                        spot = {"lat": 36.8, "lon": 139.4, "elevation_m": 1400}
                        with mock.patch.object(astro, "EPHEMERIS_PATH", eph), mock.patch("skyfield.api.load", fake):
                            with self.assertRaises(self._Stop):
                                build.build_data(spot=spot, night_date=date(2026, 10, 9), allow_network=True, cloud_mode="off")
                    self.assertTrue(seen.get("dir_existed"), "load が呼ばれた時点で保存先フォルダが無い")
                    self.assertTrue(seen.get("written"))

    def test_without_allow_network_no_directory_is_created(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        import moon_nights as mn
        with tempfile.TemporaryDirectory() as d:
            eph = Path(d) / "step1_astronomy" / "de421.bsp"
            with mock.patch.object(mn, "EPHEMERIS_PATH", eph), mock.patch.object(mn, "load", mock.MagicMock()) as load:
                self.assertNotEqual(mn.main(["--days", "1"]), 0)   # 暦が無く、通信の許可も無い → 何もせず終了
                load.assert_not_called()
            self.assertFalse(eph.parent.exists())


if __name__ == "__main__":
    unittest.main()
