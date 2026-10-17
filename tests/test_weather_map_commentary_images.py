"""天気図の解説に画像を紐づける(schema /2)の単体テスト。通信しない(fetch_jma_weather_map はモック)。"""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import generate_report as gr  # noqa: E402

JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 18, 6, 0, tzinfo=JST)
BODY = "解説の本文ABC"
STEPS = ("now", "plus24h", "plus48h")


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "repo"
        (self.root / "cache").mkdir(parents=True)
        self.addCleanup(self._tmp.cleanup)
        self.cpath = self.root / "c.json"

    def make_images(self, prefix="old"):
        images = {}
        for step in STEPS:
            rel = f"cache/jma_weathermap_{prefix}_{step}.png"
            (self.root / rel).write_bytes(b"x")
            images[step] = rel
        return images

    def write(self, hours=1, schema=gr.WEATHER_MAP_COMMENTARY_SCHEMA, images="default"):
        doc = {"schema": schema, "based_on": (NOW - timedelta(hours=hours)).isoformat(), "text": BODY}
        if images == "default":
            images = self.make_images()
        if images is not None:
            doc["images"] = images
        self.cpath.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    def fetched(self):
        out = []
        for step in STEPS:
            p = self.root / "cache" / f"jma_weathermap_new_{step}.png"
            p.write_bytes(b"y")
            out.append(p)
        return out

    def collect(self):
        new = self.fetched()
        with mock.patch.object(gr, "fetch_jma_weather_map", return_value=new) as f, \
                mock.patch.object(gr, "read_weather_map_fetched_at",
                                  return_value=datetime(2026, 10, 18, 5, 59, tzinfo=JST)):
            paths, fetched_at = gr.collect_weather_map(NOW, commentary_path=self.cpath, root=self.root)
        return f, paths, fetched_at, new


class ValidCommentaryTest(Base):
    def test_valid_does_not_fetch_and_uses_commentary_images(self):
        self.write(hours=1)
        f, paths, fetched_at, _ = self.collect()
        f.assert_not_called()
        self.assertEqual([p.name for p in paths], [f"jma_weathermap_old_{s}.png" for s in STEPS])
        self.assertEqual(fetched_at, NOW - timedelta(hours=1))

    def test_render_uses_commentary_images_and_based_on(self):
        self.write(hours=1)
        out = gr.render_weather_map_section([], NOW, commentary_path=self.cpath, root=self.root)
        self.assertIn(BODY, out)
        self.assertIn("jma_weathermap_old_now.png", out)
        self.assertIn("天気図の取得時刻: 2026-10-18 05:00", out)
        self.assertIn("2026-10-18 05:00 取得の天気図をもとに記述した解説です", out)

    def test_render_ignores_passed_images_when_valid(self):
        self.write(hours=1)
        out = gr.render_weather_map_section(self.fetched(), NOW, commentary_path=self.cpath, root=self.root)
        self.assertIn("jma_weathermap_old_now.png", out)
        self.assertNotIn("jma_weathermap_new_now.png", out)

    def test_exactly_12h_valid(self):
        self.write(hours=12)
        f, *_ = self.collect()
        f.assert_not_called()


class InvalidCommentaryFetchesTest(Base):
    def assert_fetches_and_hides(self):
        f, paths, fetched_at, new = self.collect()
        f.assert_called_once()
        self.assertEqual(paths, new)
        out = gr.render_weather_map_section(paths, NOW, commentary_path=self.cpath, fetched_at=fetched_at,
                                            root=self.root)
        self.assertNotIn(BODY, out)
        self.assertIn("解説文は未更新のため表示していません", out)
        self.assertIn("jma_weathermap_new_now.png", out)

    def test_expired(self):
        self.write(hours=13)
        self.assert_fetches_and_hides()

    def test_future(self):
        self.write(hours=-1)
        self.assert_fetches_and_hides()

    def test_no_file(self):
        self.assert_fetches_and_hides()

    def test_broken_json(self):
        self.cpath.write_text("{broken", encoding="utf-8")
        self.assert_fetches_and_hides()

    def test_schema_v1_never_shows_commentary(self):
        self.write(hours=1, schema="hoshibiyori-weathermap-commentary/1")
        self.assert_fetches_and_hides()

    def test_images_missing_key(self):
        self.write(hours=1, images=None)
        self.assert_fetches_and_hides()

    def test_image_file_missing(self):
        images = self.make_images()
        (self.root / images["plus48h"]).unlink()
        self.write(hours=1, images=images)
        self.assert_fetches_and_hides()

    def test_one_step_missing_from_dict(self):
        images = self.make_images()
        del images["plus24h"]
        self.write(hours=1, images=images)
        self.assert_fetches_and_hides()

    def test_last_updated_shown_for_expired(self):
        self.write(hours=13)
        out = gr.render_weather_map_section(self.fetched(), NOW, commentary_path=self.cpath, root=self.root)
        self.assertIn("(最終更新 2026-10-17 17時)", out)


class ImagePathValidationTest(Base):
    def check(self, images):
        self.write(hours=1, images=images)
        _, based_on, paths = gr.load_weather_map_commentary(self.cpath, self.root)
        self.assertIsNotNone(based_on)
        return paths

    def test_absolute_path_rejected(self):
        images = self.make_images()
        images["now"] = str((self.root / images["now"]).resolve())  # 実在するが絶対パス
        self.assertIsNone(self.check(images))

    def test_dotdot_rejected(self):
        images = self.make_images()
        outside = self.root.parent / "outside.png"
        outside.write_bytes(b"x")
        images["now"] = "../outside.png"
        self.assertIsNone(self.check(images))
        images["now"] = "cache/../cache/jma_weathermap_old_now.png"  # 実在しても「..」を含むなら無効
        self.assertIsNone(self.check(images))

    def test_leading_slash_rejected(self):
        images = self.make_images()
        images["now"] = "/cache/jma_weathermap_old_now.png"
        self.assertIsNone(self.check(images))

    def test_symlink_escaping_root_rejected(self):
        images = self.make_images()
        outside = self.root.parent / "outside.png"
        outside.write_bytes(b"x")
        link = self.root / "cache" / "link.png"
        try:
            os.symlink(outside, link)
        except (OSError, NotImplementedError):
            self.skipTest("シンボリックリンクを作れない環境")
        images["now"] = "cache/link.png"
        self.assertIsNone(self.check(images))

    def test_junction_escaping_root_rejected(self):
        # Windowsでは管理者権限なしにシンボリックリンクを作れないため、ディレクトリジャンクションでも確認する。
        if os.name != "nt":
            self.skipTest("Windows専用")
        import subprocess
        outside_dir = self.root.parent / "outside_dir"
        outside_dir.mkdir()
        (outside_dir / "x.png").write_bytes(b"x")
        r = subprocess.run(["cmd", "/c", "mklink", "/J", str(self.root / "jct"), str(outside_dir)],
                           capture_output=True)
        if r.returncode != 0:
            self.skipTest("ジャンクションを作れない環境")
        images = self.make_images()
        images["now"] = "jct/x.png"
        self.assertIsNone(self.check(images))

    def test_symlink_inside_root_ok(self):
        images = self.make_images()
        link = self.root / "cache" / "inner_link.png"
        try:
            os.symlink(self.root / images["now"], link)
        except (OSError, NotImplementedError):
            self.skipTest("シンボリックリンクを作れない環境")
        images["now"] = "cache/inner_link.png"
        self.assertIsNotNone(self.check(images))

    def test_valid_relative_paths_ok(self):
        paths = self.check(self.make_images())
        self.assertEqual(len(paths), 3)


if __name__ == "__main__":
    unittest.main()
