"""2026-11-24 の片付け(標高の無い地点の --spot、地形データなしの件数の数え方)のテスト。通信しない。"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import explore_hoshibiyori as ex  # noqa: E402
from skyguide import build  # noqa: E402
from skyguide.render import SkyGuideError  # noqa: E402
from test_no_terrain_horizon import SITE, FakeTs, altitude_fn, survivor  # noqa: E402


class SpotElevationTests(unittest.TestCase):
    def test_two_spots_use_verified_elevation(self):
        for name in ("石廊崎", "ヘブンスそのはら"):
            spot = build.load_spot(name)
            self.assertEqual(spot["elevation_m"], ex.ELEVATION_BY_NAME[name])
            self.assertIn("ELEVATION_BY_NAME", spot["elevation_source"])

    def test_every_primary_spot_resolves_to_the_elevation_explore_uses(self):
        data = json.loads((ROOT / "stargazing_spots.json").read_text(encoding="utf-8"))
        for entry in data["spots"]:
            spot = build.load_spot(entry["id"])
            self.assertIsNotNone(spot["elevation_m"], entry["id"])
            if entry.get("elevation_m") is None:
                self.assertEqual(spot["elevation_m"], ex._build_site(entry)["elevation_m"], entry["id"])
            else:
                self.assertEqual(spot, entry)   # 標高のある地点はそのまま(変えない)

    def test_unknown_elevation_is_refused(self):
        with self.assertRaises(SkyGuideError) as cm:
            build.with_elevation({"name": "標高の無いテスト地点", "lat": 35.0, "lon": 139.0})
        self.assertIn("標高", str(cm.exception))


class NoTerrainCountTests(unittest.TestCase):
    def test_count_never_exceeds_passed(self):
        class Lp:
            alr_threshold = 10.66

            def get(self, lat, lon):
                ratio = ex.LP_INDEX_LIMIT * (0.2 if lat < 36 else 2.0)   # 北側の地点は光害で落ちる
                return SimpleNamespace(brightness_ratio=ratio, alr=2.0, rank_pct=20.0)
        sites = [SITE] + [dict(SITE, name=f"明るい地点{i}", lat=36.5) for i in range(5)]
        out = io.StringIO()
        with mock.patch.object(ex, "altaz_at_time", altitude_fn(lambda m: 5.0)), \
                mock.patch.object(ex, "get_target", lambda tid: SimpleNamespace(name="天の川銀河中心")), \
                contextlib.redirect_stdout(out):
            finals = ex.stage3_direction_filter(FakeTs(), None, [survivor(s) for s in sites], Lp(), "milkyway")
        self.assertEqual(len(finals), 1)
        self.assertIn("うち地形データなし(地平線を高度0°として判定して通過): 1件", out.getvalue())


if __name__ == "__main__":
    unittest.main()
