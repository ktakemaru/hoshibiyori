"""天気図の解説文の有効期限(通信しない)。"""
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import generate_report as gr  # noqa: E402

JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 18, 6, 0, tzinfo=JST)
BODY = "古いかもしれない本文XYZ"
IMG = gr.ROOT / "step5_cloud_forecast" / "weather_map_cache" / "jma_weathermap_2026-10-18_0600_now.png"


def _render(content, fetched_at=None, images=None):
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "c.json"
        if content is not None:
            path.write_text(content if isinstance(content, str) else json.dumps(content, ensure_ascii=False),
                            encoding="utf-8")
        return gr.render_weather_map_section([IMG] if images is None else images, NOW,
                                             commentary_path=path, fetched_at=fetched_at)


def _doc(based_on, schema=gr.WEATHER_MAP_COMMENTARY_SCHEMA):
    return {"schema": schema, "based_on": based_on, "text": BODY}


class CommentaryAgeTest(unittest.TestCase):
    def test_within_12h_shown(self):
        out = _render(_doc((NOW - timedelta(hours=11)).isoformat()))
        self.assertIn(BODY, out)
        self.assertIn("2026-10-17 19:00 取得の天気図をもとに記述した解説です", out)

    def test_exactly_12h_shown(self):
        self.assertIn(BODY, _render(_doc((NOW - timedelta(hours=12)).isoformat())))

    def test_over_12h_hidden(self):
        out = _render(_doc((NOW - timedelta(hours=12, minutes=1)).isoformat()))
        self.assertNotIn(BODY, out)
        self.assertIn("解説文は未更新のため表示していません(最終更新 2026-10-17 17時)", out)

    def test_future_hidden(self):
        self.assertNotIn(BODY, _render(_doc((NOW + timedelta(minutes=1)).isoformat())))

    def test_missing_file(self):
        out = _render(None)
        self.assertNotIn(BODY, out)
        self.assertIn("解説文は未更新のため表示していません</p>", out)
        self.assertIn("<img", out)

    def test_broken_json(self):
        self.assertNotIn(BODY, _render("{not json"))

    def test_wrong_schema(self):
        self.assertNotIn(BODY, _render(_doc(NOW.isoformat(), schema="other/1")))

    def test_no_timezone(self):
        self.assertNotIn(BODY, _render(_doc("2026-10-18T05:00:00")))

    def test_no_based_on(self):
        self.assertNotIn(BODY, _render({"schema": gr.WEATHER_MAP_COMMENTARY_SCHEMA, "text": BODY}))

    def test_empty_images_no_section(self):
        self.assertEqual(_render(_doc(NOW.isoformat()), images=[]), "")

    def test_fetched_at_shown(self):
        out = _render(None, fetched_at=datetime(2026, 10, 18, 5, 30, tzinfo=JST))
        self.assertIn("天気図の取得時刻: 2026-10-18 05:30", out)

    def test_gitignore_has_entry(self):
        lines = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn("/weather_map_commentary.json", lines)

    def test_old_constant_removed(self):
        self.assertFalse(hasattr(gr, "WEATHER_MAP_COMMENTARY"))
        self.assertEqual(gr.WEATHER_MAP_COMMENTARY_MAX_AGE_HOURS, 12)


if __name__ == "__main__":
    unittest.main()
