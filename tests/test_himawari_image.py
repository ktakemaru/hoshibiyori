"""himawari_image の単体テスト。ネットワーク不使用(requests.get をモック)、キャッシュは一時ディレクトリ。

実行: py -X utf8 -m unittest discover -s tests -v
"""
import io
import json
import math
import sys
import tempfile
import unittest
from datetime import timezone
from pathlib import Path
from unittest import mock

import requests
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "step5_cloud_forecast"))

import himawari_image as hi  # noqa: E402


def tile_bounds(x, y, z):
    """タイル(x,y,z)の北西端・南東端の(lat, lon)。OSM wikiの逆変換式(forward式とは独立に書いた検算用)。"""
    n = 2 ** z

    def lat_of(yy):
        return math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * yy / n))))

    def lon_of(xx):
        return xx / n * 360.0 - 180.0

    return (lat_of(y), lon_of(x)), (lat_of(y + 1), lon_of(x + 1))


def jpeg_bytes(color=(200, 200, 200)):
    buf = io.BytesIO()
    Image.new("RGB", (hi.TILE_PX, hi.TILE_PX), color).save(buf, "JPEG")
    return buf.getvalue()


def resp(status=200, content=b"", payload=None):
    r = mock.Mock()
    r.status_code = status
    r.content = content
    r.json.return_value = payload
    if status >= 400:
        r.raise_for_status.side_effect = requests.HTTPError(str(status))
    return r


class TileMathTest(unittest.TestCase):
    POINTS = {
        "石廊崎": (34.6080, 138.8500),
        "宗谷岬": (45.5226, 141.9366),
        "那覇": (26.2124, 127.6809),
        "東京": (35.6762, 139.6503),
    }

    def test_point_lies_inside_its_tile_by_inverse_formula(self):
        for name, (lat, lon) in self.POINTS.items():
            x, y = hi.latlon_to_tile_xy(lat, lon)
            (nw_lat, nw_lon), (se_lat, se_lon) = tile_bounds(x, y, hi.ZOOM)
            self.assertTrue(se_lat <= lat <= nw_lat and nw_lon <= lon <= se_lon, name)

    def test_matches_asinh_form(self):
        n = 2 ** hi.ZOOM
        for name, (lat, lon) in self.POINTS.items():
            fy = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n
            self.assertAlmostEqual(hi.tile_float(lat, lon)[1], fy, places=9, msg=name)
            self.assertAlmostEqual(hi.tile_float(lat, lon)[0], (lon + 180) / 360 * n, places=9, msg=name)

    def test_known_tokyo_tile(self):
        self.assertEqual(hi.latlon_to_tile_xy(35.6762, 139.6503), (56, 25))  # z=6 の東京は 56/25


class WindowTest(unittest.TestCase):
    def test_even_and_odd_origin(self):
        lat, lon = 35.725, 139.35
        fx, fy = hi.tile_float(lat, lon)
        self.assertEqual(hi.window_origin(lat, lon, 3), (math.floor(fx) - 1, math.floor(fy) - 1))
        self.assertEqual(hi.window_origin(lat, lon, 2), (math.floor(fx + 0.5) - 1, math.floor(fy + 0.5) - 1))

    def test_areas_json_fits_in_2x2(self):
        data = json.loads((ROOT / "areas.json").read_text(encoding="utf-8"))["areas"]
        boxes = [(a["bbox"]["lat_min"], a["bbox"]["lat_max"], a["bbox"]["lon_min"], a["bbox"]["lon_max"])
                 for a in data]
        lat, lon, span = hi.regional_view(boxes)
        self.assertEqual(span, 2)
        x0, y0 = hi.window_origin(lat, lon, span)
        self.assertTrue(hi.window_covers(
            x0, y0, span, min(b[0] for b in boxes), max(b[1] for b in boxes),
            min(b[2] for b in boxes), max(b[3] for b in boxes)))

    def test_span_grows_when_2x2_is_too_small(self):
        # 東西11度幅の矩形は2x2(約11.25度)の窓に中心合わせでは収まらず、3x3を選ぶ
        lat, lon, span = hi.regional_view([(34.0, 37.0, 134.0, 145.0)], candidate_spans=(2, 3))
        self.assertEqual(span, 3)

    def test_basetime_to_jst(self):
        self.assertIs(hi.BASETIME_TZ, timezone.utc)  # 2026-10-12のスモークテストで確定した値
        self.assertEqual(hi.basetime_to_jst("20261012120000").strftime("%Y-%m-%d %H:%M"), "2026-10-12 21:00")

    def test_basetime_to_jst_pinned_to_live_observation(self):
        # 実測: 2026-10-12 00:47:12 UTC(=09:47 JST)に取得した最新basetimeは 20261012004000。
        # UTCとして読めば7分前で、表示は 09:40 JST になる(JSTと誤解すると 00:40 JST=9時間前になる)。
        self.assertEqual(hi.basetime_to_jst("20261012004000").strftime("%Y-%m-%d %H:%M"), "2026-10-12 09:40")


@mock.patch("himawari_image.time.sleep")
class FetchTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def fetch(self, **kw):
        return hi.fetch_regional_image(35.725, 139.35, imgtype="ir", span=2, cache_dir=self.dir, **kw)

    def test_target_times_called_once_and_mosaic_size(self, _sleep):
        def fake_get(url, **kw):
            if url.endswith("targetTimes_jp.json"):
                return resp(payload=[{"basetime": "20261012110000"}, {"basetime": "20261012120000"}])
            return resp(content=jpeg_bytes())
        with mock.patch("himawari_image.requests.get", side_effect=fake_get) as g:
            img = self.fetch()
        urls = [c.args[0] for c in g.call_args_list]
        self.assertEqual(sum(u.endswith("targetTimes_jp.json") for u in urls), 1)
        self.assertEqual(len(urls), 1 + 4)
        self.assertTrue(all("/B13/TBB/6/" in u for u in urls[1:]))
        self.assertEqual(img.basetime, "20261012120000")
        self.assertEqual((img.tiles_ok, img.tiles_total), (4, 4))
        with Image.open(img.path) as im:
            self.assertEqual(im.size, (2 * hi.TILE_PX, 2 * hi.TILE_PX))
        self.assertIn("(https://www.jma.go.jp/bosai/map.html)", img.attribution)
        for call in g.call_args_list:  # 識別可能なUser-Agent
            self.assertIn("hoshibiyori", call.kwargs["headers"]["User-Agent"])

    def test_same_basetime_uses_cache_without_tile_requests(self, _sleep):
        with mock.patch("himawari_image.requests.get", return_value=resp(content=jpeg_bytes())) as g:
            self.fetch(basetime="20261012120000")
            first = g.call_count
            self.fetch(basetime="20261012120000")
        self.assertEqual(first, 4)
        self.assertEqual(g.call_count, 4)  # 2回目はタイルを再取得しない

    def test_new_basetime_is_not_reused(self, _sleep):
        with mock.patch("himawari_image.requests.get", return_value=resp(content=jpeg_bytes())) as g:
            self.fetch(basetime="20261012120000")
            self.fetch(basetime="20261012121000")
        self.assertEqual(g.call_count, 8)

    def test_404_tile_becomes_gray_and_others_kept(self, _sleep):
        calls = {"n": 0}

        def fake_get(url, **kw):
            calls["n"] += 1
            return resp(404) if calls["n"] == 1 else resp(content=jpeg_bytes((255, 255, 255)))
        with mock.patch("himawari_image.requests.get", side_effect=fake_get):
            img = self.fetch(basetime="20261012120000")
        self.assertEqual((img.tiles_ok, img.tiles_total), (3, 4))
        with Image.open(img.path) as im:
            self.assertLess(im.convert("RGB").getpixel((10, 10))[0], 100)  # 左上は灰色

    def test_all_tiles_missing_returns_none(self, _sleep):
        with mock.patch("himawari_image.requests.get", return_value=resp(404)):
            self.assertIsNone(self.fetch(basetime="20261012120000"))
        self.assertEqual(list(self.dir.glob("mosaic_*")), [])

    def test_429_aborts_without_retry(self, sleep):
        with mock.patch("himawari_image.requests.get", return_value=resp(429)) as g:
            with self.assertRaises(hi.HimawariRateLimitError):
                self.fetch(basetime="20261012120000")
        self.assertEqual(g.call_count, 1)
        sleep.assert_not_called()

    def test_500_is_retried_then_succeeds(self, _sleep):
        with mock.patch("himawari_image.requests.get", side_effect=[resp(500), resp(200, b"x")]) as g:
            r = hi._http_get("https://example.invalid/x")
        self.assertEqual(r.content, b"x")
        self.assertEqual(g.call_count, 2)

    def test_unknown_imgtype_rejected(self, _sleep):
        with self.assertRaises(ValueError):
            hi.fetch_regional_image(35.0, 139.0, imgtype="vis", cache_dir=self.dir)

    def test_only_confirmed_image_types(self, _sleep):
        self.assertEqual(set(hi.IMG_TYPES), {"ir", "strengthen"})


class RenderSectionTest(unittest.TestCase):
    def test_section_states_it_is_observation_with_basetime(self):
        sys.path.insert(0, str(ROOT))
        import generate_report as gr
        img = hi.HimawariImage(
            path=gr.ROOT / "step5_cloud_forecast" / "himawari_cache" / "mosaic_ir_x.jpg",
            basetime="20261012120000", basetime_jst=hi.basetime_to_jst("20261012120000"),
            imgtype="ir", span=2, x0=56, y0=24, tiles_ok=4, tiles_total=4)
        out = gr.render_himawari_section(img)
        self.assertIn("現況の雲の様子(参考)", out)
        self.assertIn("2026-10-12 21:00 JST", out)
        self.assertIn("予報ではありません", out)
        self.assertIn("出典：気象庁ホームページ (https://www.jma.go.jp/bosai/map.html)", out)


if __name__ == "__main__":
    unittest.main()
