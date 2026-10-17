"""ひまわり3コマ表示と「雲域の割合」の単体テスト。通信しない(requests.get をモック)。

閾値は決め打ちにせず、合成画像で純関数の振る舞いを検査する。
"""
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "step5_cloud_forecast"))
sys.path.insert(0, str(ROOT))

import himawari_image as hi  # noqa: E402
import generate_report as gr  # noqa: E402

JST = timezone(timedelta(hours=9))


def resp(payload):
    r = mock.Mock()
    r.status_code = 200
    r.json.return_value = payload
    return r


def bts(*stamps):
    return [{"basetime": s} for s in stamps]


class RecentBasetimesTest(unittest.TestCase):
    def call(self, payload, **kw):
        with mock.patch("himawari_image.requests.get", return_value=resp(payload)) as g:
            out = hi.recent_basetimes(**kw)
        self.assertEqual(g.call_count, 1)  # 時刻一覧は1回だけ
        return out

    def test_hourly_steps(self):
        out = self.call(bts("20261017010000", "20261017020000", "20261017030000", "20261017040000"))
        self.assertEqual(out, ["20261017020000", "20261017030000", "20261017040000"])

    def test_ten_minute_steps(self):
        stamps = [f"20261017{h:02d}{m:02d}00" for h in (1, 2, 3) for m in range(0, 60, 10)]
        out = self.call(bts(*reversed(stamps)))  # 順不同でも古い順に返す
        self.assertEqual(out, ["20261017015000", "20261017025000", "20261017035000"])

    def test_gap_uses_nearest_earlier(self):
        # 60分前(02:20)ちょうどが無く、それ以前で最も近い02:00を採る。120分前(01:20)は01:10。
        out = self.call(bts("20261017011000", "20261017020000", "20261017032000"))
        self.assertEqual(out, ["20261017011000", "20261017020000", "20261017032000"])

    def test_latest_only(self):
        self.assertEqual(self.call(bts("20261017032000")), ["20261017032000"])

    def test_duplicates_merged(self):
        out = self.call(bts("20261017010000", "20261017032000"))
        self.assertEqual(out, ["20261017010000", "20261017032000"])

    def test_missing_offsets_skipped(self):
        out = self.call(bts("20261017030000", "20261017040000"))
        self.assertEqual(out, ["20261017030000", "20261017040000"])

    def test_custom_offsets(self):
        out = self.call(bts("20261017030000", "20261017040000"), offsets_min=(0,))
        self.assertEqual(out, ["20261017040000"])


class HighCloudFractionTest(unittest.TestCase):
    def img(self, color, size=(10, 10)):
        return Image.new("L", size, color)

    def test_all_white(self):
        self.assertEqual(hi.high_cloud_fraction(self.img(255), (0, 0, 10, 10), 170), 1.0)

    def test_all_black(self):
        self.assertEqual(hi.high_cloud_fraction(self.img(0), (0, 0, 10, 10), 170), 0.0)

    def test_half_white(self):
        im = self.img(0)
        im.paste(255, (0, 0, 5, 10))
        self.assertEqual(hi.high_cloud_fraction(im, (0, 0, 10, 10), 170), 0.5)

    def test_bbox_sticking_out_is_clipped(self):
        im = self.img(0)
        im.paste(255, (0, 0, 5, 10))  # 左半分が白
        # bbox (-5,-5,5,15) は画像内では (0,0,5,10) だけ → 全部白
        self.assertEqual(hi.high_cloud_fraction(im, (-5, -5, 5, 15), 170), 1.0)

    def test_bbox_fully_outside_raises(self):
        with self.assertRaises(ValueError):
            hi.high_cloud_fraction(self.img(255), (20, 20, 30, 30), 170)

    def test_threshold_pixel_counts(self):
        self.assertEqual(hi.high_cloud_fraction(self.img(170), (0, 0, 10, 10), 170), 1.0)
        self.assertEqual(hi.high_cloud_fraction(self.img(169), (0, 0, 10, 10), 170), 0.0)

    def test_rgb_and_path_input(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "a.png"
            Image.new("RGB", (4, 4), (255, 255, 255)).save(p)
            self.assertEqual(hi.high_cloud_fraction(p, (0, 0, 4, 4), 170), 1.0)
            self.assertEqual(hi.high_cloud_fraction(str(p), (0, 0, 4, 4), 170), 1.0)

    def test_draw_outline_leaves_original(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "a.png"
            Image.new("RGB", (20, 20), (0, 0, 0)).save(src)
            before = src.read_bytes()
            out = hi.draw_outline(src, (5, 5, 15, 15), Path(d) / "o.png")
            self.assertEqual(src.read_bytes(), before)
            self.assertEqual(Image.open(out).getpixel((5, 5)), (255, 214, 0))
            self.assertEqual(Image.open(out).getpixel((10, 10)), (0, 0, 0))


class SolidFillExclusionTest(unittest.TestCase):
    """純白の塗りつぶし長方形の除外(合成画像)。"""

    def canvas(self, size=100):
        return Image.new("L", (size, size), 0)

    def test_default_threshold_is_100(self):
        self.assertEqual(hi.HIGH_CLOUD_BRIGHTNESS_THRESHOLD, 100)
        im = Image.new("L", (10, 10), 120)
        self.assertEqual(hi.high_cloud_fraction(im, (0, 0, 10, 10)), 1.0)  # 既定(100)なら雲域
        self.assertEqual(hi.high_cloud_fraction(im, (0, 0, 10, 10), 130), 0.0)

    def test_big_solid_rect_excluded_from_both(self):
        im = self.canvas()
        im.paste(255, (0, 0, 60, 40))     # 2400px、充填率1.0 → 除外
        im.paste(150, (70, 0, 100, 100))  # 雲 3000px
        self.assertAlmostEqual(hi.high_cloud_fraction(im, (0, 0, 100, 100)), 3000 / 7600)

    def test_without_solid_rect(self):
        im = self.canvas()
        im.paste(150, (70, 0, 100, 100))
        self.assertAlmostEqual(hi.high_cloud_fraction(im, (0, 0, 100, 100)), 3000 / 10000)

    def test_small_white_rect_not_excluded(self):
        im = self.canvas()
        im.paste(255, (0, 0, 30, 30))     # 900px(2000未満)→ 雲として数える
        self.assertAlmostEqual(hi.high_cloud_fraction(im, (0, 0, 100, 100)), 900 / 10000)

    def test_low_fill_ratio_not_excluded(self):
        im = Image.new("L", (100, 100), 255)
        im.paste(0, (15, 15, 85, 85))     # 白い枠(5100px、外接矩形の充填率0.51)
        self.assertAlmostEqual(hi.high_cloud_fraction(im, (0, 0, 100, 100)), 5100 / 10000)

    def test_nothing_left_returns_none(self):
        self.assertIsNone(hi.high_cloud_fraction(Image.new("L", (100, 100), 255), (0, 0, 100, 100)))

    def test_exclusion_only_inside_bbox_denominator(self):
        im = self.canvas()
        im.paste(255, (0, 0, 60, 40))     # bboxの外にも半分はみ出す塗りつぶし
        im.paste(150, (70, 0, 100, 100))
        # bbox=右半分(x50〜100): 塗りつぶしはx50〜60 × y0〜40 = 400px が除外される
        self.assertAlmostEqual(hi.high_cloud_fraction(im, (50, 0, 100, 100)), 3000 / (5000 - 400))


class BboxToPxTest(unittest.TestCase):
    def test_inside_window(self):
        x0, y0, span = 56, 24, 2
        fx, fy = hi.tile_float(35.0, 139.0)
        r = hi.bbox_to_px(34.9, 35.1, 138.9, 139.1, x0, y0, span)
        left, top, right, bottom = r
        self.assertTrue(0 <= left < right <= 512 and 0 <= top < bottom <= 512)
        self.assertTrue(left <= (fx - x0) * 256 <= right)
        self.assertTrue(top <= (fy - y0) * 256 <= bottom)

    def test_clipped_to_window(self):
        r = hi.bbox_to_px(10.0, 60.0, 100.0, 170.0, 56, 24, 2)
        self.assertEqual(r, (0, 0, 512, 512))

    def test_outside_window_is_none(self):
        self.assertIsNone(hi.bbox_to_px(-10.0, -5.0, 0.0, 5.0, 56, 24, 2))

    def test_boundary_exact_tile_edges(self):
        import math

        def lat_of(yy):
            return math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * yy / 64))))

        def lon_of(xx):
            return xx / 64 * 360.0 - 180.0

        # 窓(56,24,span=2)の外縁にちょうど一致する矩形は、窓全体になる
        r = hi.bbox_to_px(lat_of(26), lat_of(24), lon_of(56), lon_of(58), 56, 24, 2)
        self.assertEqual(r, (0, 0, 512, 512))
        # 右下のタイル(57,25)だけの矩形
        r = hi.bbox_to_px(lat_of(26), lat_of(25), lon_of(57), lon_of(58), 56, 24, 2)
        self.assertEqual(r, (256, 256, 512, 512))


class FactSentenceTest(unittest.TestCase):
    S = staticmethod(gr.high_cloud_fact_sentence)

    def test_decrease(self):
        out = self.S([("2時間前", 0.38), ("1時間前", 0.25), ("現在", 0.12)])
        self.assertEqual(out, "雲域の割合: 2時間前 38% → 1時間前 25% → 現在 12%(2時間前から26ポイント減少)")

    def test_increase(self):
        out = self.S([("2時間前", 0.10), ("現在", 0.30)])
        self.assertIn("20ポイント増加", out)

    def test_flat_boundary(self):
        self.assertIn("ほぼ横ばい", self.S([("2時間前", 0.38), ("現在", 0.33)]))   # -5
        self.assertIn("ほぼ横ばい", self.S([("2時間前", 0.33), ("現在", 0.38)]))   # +5
        self.assertIn("6ポイント減少", self.S([("2時間前", 0.38), ("現在", 0.32)]))  # -6
        self.assertIn("6ポイント増加", self.S([("2時間前", 0.32), ("現在", 0.38)]))  # +6

    def test_two_and_one_and_zero(self):
        self.assertIn("1時間前 25% → 現在 12%", self.S([("1時間前", 0.25), ("現在", 0.12)]))
        self.assertEqual(self.S([("現在", 0.12)]), "雲域の割合: 現在 12%")
        self.assertEqual(self.S([]), "")

    def test_no_forecast_words(self):
        out = self.S([("2時間前", 0.38), ("1時間前", 0.25), ("現在", 0.12)])
        for w in ("今後", "見込み", "予想", "でしょう"):
            self.assertNotIn(w, out)

    def test_frame_label(self):
        base = datetime(2026, 10, 17, 12, 0, tzinfo=JST)
        self.assertEqual(gr.himawari_frame_label(base, base), "現在")
        self.assertEqual(gr.himawari_frame_label(base - timedelta(hours=1), base), "1時間前")
        self.assertEqual(gr.himawari_frame_label(base - timedelta(minutes=70), base), "70分前")


class RenderSectionTest(unittest.TestCase):
    def frame(self, hhmm, label, frac):
        bt = f"20261017{hhmm}00"
        img = hi.HimawariImage(
            path=gr.ROOT / "step5_cloud_forecast" / "himawari_cache" / f"mosaic_ir_{bt}.jpg",
            basetime=bt, basetime_jst=hi.basetime_to_jst(bt), imgtype="ir", span=2, x0=56, y0=24,
            tiles_ok=4, tiles_total=4)
        return gr.HimawariFrame(img, label, frac, img.path)

    def three(self):
        return [self.frame("0100", "2時間前", 0.38), self.frame("0200", "1時間前", 0.25),
                self.frame("0300", "現在", 0.12)]

    def test_three_frames_in_order_with_notes(self):
        out = gr.render_himawari_section(self.three())
        self.assertEqual(out.count("<figure"), 3)
        self.assertLess(out.index("2時間前("), out.index("1時間前("))
        self.assertLess(out.index("1時間前("), out.index("現在("))
        self.assertIn("雲域の割合 38%", out)
        self.assertIn("雲域の割合 12%", out)
        self.assertIn("2時間前から26ポイント減少", out)
        self.assertIn("低い雲・霧は地面との温度差が小さく見分けにくく", out)
        self.assertIn("気象庁の公式の雲量ではありません", out)
        self.assertIn("(枠線を加筆して作成)", out)
        self.assertIn(hi.ATTRIBUTION, out)

    def test_two_one_zero_frames(self):
        self.assertEqual(gr.render_himawari_section(self.three()[1:]).count("<figure"), 2)
        one = gr.render_himawari_section(self.three()[2:])
        self.assertEqual(one.count("<figure"), 1)
        self.assertIn("雲域の割合: 現在 12%", one)
        self.assertEqual(gr.render_himawari_section([]), "")

    def test_frame_without_fraction(self):
        out = gr.render_himawari_section([self.frame("0300", "現在", None)])
        self.assertIn("割合: 算出できず", out)
        self.assertNotIn("雲域の割合:", out)

    def test_html_escaped(self):
        out = gr.render_himawari_section([self.frame("0300", "<b>現在</b>", 0.1)])
        self.assertNotIn("<b>現在</b>", out)
        self.assertIn("&lt;b&gt;現在&lt;/b&gt;", out)


if __name__ == "__main__":
    unittest.main()
