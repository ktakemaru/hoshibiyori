"""scripts/weekend_page.py の単体テスト(通信しない)。

テスト用の report.html は generate_report.render_html に合成データ(候補カード・月齢タイムライン・フッター)を渡して作る。
generate_report.py 側のHTML構造が変わると、このテストが落ちて気づける。
"""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import generate_report as gr  # noqa: E402
import weekend_page as wp  # noqa: E402

JST = timezone(timedelta(hours=9))
SAT = datetime(2026, 10, 17, 15, 0, tzinfo=JST)  # 2026-10-17 は土曜
D17, D18 = date(2026, 10, 17), date(2026, 10, 18)


def card(name, muni, score, lat, lon, night=D17, start=(21, 15), end=(4, 15), best=(23, 0),
         obstruction=12.4, alr=2.34, rank=41.0, origin="curated"):
    ws = datetime(2026, 10, night.day, *start, tzinfo=JST)
    we = datetime(2026, 10, night.day + (1 if end < start else 0), *end, tzinfo=JST)
    return SimpleNamespace(
        site_name=name, municipality=muni, score=score, origin=origin, site_lat=lat, site_lon=lon,
        window_start=ws, window_end=we, best_time=datetime(2026, 10, night.day, *best, tzinfo=JST),
        night_date=night, mean_obstruction=obstruction, alr=alr, alr_rank_pct=rank)


# 気軽: 17日3件+18日1件。硬派: 17日(気軽と重複1・遠征圏・離島・近場)+18日なし
CASUAL = [card("奥只見ダム", "魚沼市", 119.4, 37.2, 139.3), card("枝折峠", "魚沼市", 117.2, 37.1, 139.2, alr=3.1, rank=55.0),
          card("白州", "北杜市", 100.0, 35.8, 138.3, obstruction=3.0),
          card("奥只見ダム", "魚沼市", 115.0, 37.2, 139.3, night=D18, start=(22, 29))]
HARDCORE = [card("奥只見ダム", "魚沼市", 119.4, 37.2, 139.3), card("白米千枚田", "輪島市", 118.6, 37.3, 136.8),
            card("白木峰展望台", "佐渡市", 118.0, 38.0, 138.3), card("近場の地点", "県内市", 99.0, 35.9, 139.0)]


def moon_nights(days=(17, 18, 19), hours=(6.8, 5.8, 0.0)):
    return [SimpleNamespace(night_date=date(2026, 10, d), moon_free_hours=h,
                            window_start=(datetime(2026, 10, d, 21, tzinfo=JST) if h else None))
            for d, h in zip(days, hours)]


def build_html(casual=CASUAL, hardcore=HARDCORE, generated="2026-10-17 11:20", weather_note="首都圏は晴れ間が多い見込みです。",
               nights=None, weather_map_html=""):
    nights = moon_nights() if nights is None else nights
    icons = {n.night_date: "🌓" for n in nights}
    gen = datetime.strptime(generated, "%Y-%m-%d %H:%M")
    return gr.render_html(SimpleNamespace(name="天の川銀河中心"), gen, nights, icons, {}, 0, 3, casual, hardcore,
                          weather_note, {}, [], {}, "概況", weather_map_html=weather_map_html)


GOOD_COMMENTARY = {
    "schema": wp.COMMENTARY_SCHEMA,
    "verdict": [{"title": "土曜が本命", "body": "高気圧に覆われる見込みです。", "tone": "good"},
                {"title": "日曜は一段下がる", "body": "月の入りが遅くなります。", "tone": "neutral"},
                {"title": "銀河中心は狙えない", "body": "日没直後に沈みます。", "tone": "warn"}],
    "extra_notes": ["補足の一行"],
}

WEATHER_TEXT = "17日9時の実況では、日本付近は高気圧に覆われています。"
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


def weather_commentary(based_on="2026-10-17T10:57:00+09:00", images=None, schema=None, text=WEATHER_TEXT):
    obj = {"schema": schema or gr.WEATHER_MAP_COMMENTARY_SCHEMA, "based_on": based_on, "text": text}
    if images is not None:
        obj["images"] = images
    return obj


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        orig_root = wp.WEATHER_ROOT
        wp.WEATHER_ROOT = self.dir
        self.addCleanup(setattr, wp, "WEATHER_ROOT", orig_root)
        self.images = self.make_images("1057")
        self.wc_path = self.write_json("weather_map_commentary.json", weather_commentary(images=self.rels(self.images)))
        self.report = self.dir / "report.html"
        self.report.write_text(build_html(weather_map_html=self.wmap_block(self.images)), encoding="utf-8")
        self.out = self.dir / "page.html"

    def make_images(self, stamp):
        d = self.dir / "step5" / "weather_map_cache"
        d.mkdir(parents=True, exist_ok=True)
        paths = []
        for step in gr.WEATHER_MAP_STEPS:
            p = d / f"jma_weathermap_2026-10-17_{stamp}_{step}.png"
            p.write_bytes(PNG_BYTES)
            paths.append(p)
        return paths

    def rels(self, paths):
        return dict(zip(gr.WEATHER_MAP_STEPS, (p.relative_to(self.dir).as_posix() for p in paths)))

    def wmap_block(self, images, fetched_at=None):
        """レポート本体の天気図ブロック(generate_report の実際の描画関数で作る)。解説が有効ならその時刻・画像で描かれる。"""
        return gr.render_weather_map_section(images, SAT, self.wc_path if hasattr(self, "wc_path") else None,
                                             fetched_at or datetime(2026, 10, 17, 10, 57, tzinfo=JST), self.dir)

    def set_weather(self, obj, report_images=None, fetched_at=None):
        """weather_map_commentary.json を差し替え、レポートの天気図ブロックを(指定があればその画像・時刻で)作り直す。"""
        self.write_json("weather_map_commentary.json", obj)
        self.report.write_text(build_html(weather_map_html=self.wmap_block(report_images or self.images, fetched_at)),
                               encoding="utf-8")

    def write_json(self, name, obj):
        p = self.dir / name
        p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
        return p

    def run_cli(self, *argv, now=SAT, report=None, with_out=True):
        args = ["--report", str(report or self.report), "--access-notes", str(self.dir / "no_notes.json"),
                "--weather-commentary", str(self.wc_path), "--spots", str(self.dir / "no_spots.json")]
        if with_out:
            args += ["--out", str(self.out)]
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = wp.main(args + list(argv), now=now)
        return code, out.getvalue(), err.getvalue()

    def page(self, *argv, **kw):
        code, _, err = self.run_cli(*argv, **kw)
        self.assertEqual(code, 0, err)
        return self.out.read_text(encoding="utf-8")


class DefaultDatesTest(unittest.TestCase):
    def test_saturday_includes_today(self):
        self.assertEqual(wp.default_dates(date(2026, 10, 17)), [D17, D18])

    def test_sunday_is_only_that_day(self):
        self.assertEqual(wp.default_dates(D18), [D18])

    def test_weekday_and_friday(self):
        self.assertEqual(wp.default_dates(date(2026, 10, 14)), [D17, D18])  # 水
        self.assertEqual(wp.default_dates(date(2026, 10, 16)), [D17, D18])  # 金
        self.assertEqual(wp.default_dates(date(2026, 10, 12)), [D17, D18])  # 月

    def test_dates_option_overrides(self):
        page = self.page_with_dates()
        self.assertIn("日曜の夜", page)
        self.assertNotIn("土曜の夜", page)

    def page_with_dates(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        rep, out = Path(tmp.name) / "r.html", Path(tmp.name) / "o.html"
        rep.write_text(build_html(), encoding="utf-8")
        o, e = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(o), contextlib.redirect_stderr(e):
            code = wp.main(["--report", str(rep), "--access-notes", str(Path(tmp.name) / "x.json"), "--out", str(out),
                            "--dates", "2026-10-18"], now=SAT)
        self.assertEqual(code, 0, e.getvalue())
        return out.read_text(encoding="utf-8")


class NightCardsTest(Base):
    def test_cards_by_night_and_rerank(self):
        page = self.page()
        sat, sun = page.index("土曜の夜"), page.index("日曜の夜")
        self.assertLess(sat, sun)
        sat_part, sun_part = page[sat:sun], page[sun:page.index("全候補の一覧")]
        self.assertIn("枝折峠", sat_part)
        self.assertNotIn("枝折峠", sun_part)
        # 日曜の気軽は奥只見ダム1件で、夜の中の順位は1に振り直される
        self.assertEqual(sun_part.count('<div class="rank">'), 1)
        self.assertIn('<div class="rank">1</div>', sun_part)
        self.assertIn("スコア 115", sun_part)

    def test_top_limits_cards_per_night_not_table(self):
        page = self.page("--top", "1")
        sat_part = page[page.index("土曜の夜"):page.index("日曜の夜")]
        self.assertEqual(sat_part.count('<div class="rank">'), 2)  # 気軽1+硬派1
        self.assertNotIn("枝折峠</h4>", sat_part)
        self.assertIn("枝折峠", page[page.index("全候補の一覧"):])  # 一覧表には残る

    def test_night_without_candidates_in_a_course(self):
        page = self.page()
        sun_part = page[page.index("日曜の夜"):page.index("全候補の一覧")]
        self.assertIn("この夜の上位4件に入った地点はありません", sun_part)  # 硬派(レポート内4件)。空欄で埋めない

    def test_moon_in_heading(self):
        page = self.page()
        self.assertIn("🌓 無月 6.8時間", page[page.index("土曜の夜"):page.index("日曜の夜")])
        self.assertIn("無月 5.8時間", page[page.index("日曜の夜"):])

    def test_no_moon_free_night(self):
        page = self.page("--dates", "2026-10-19")
        self.assertIn("無月時間帯なし", page)

    def test_night_missing_from_timeline(self):
        page = self.page("--dates", "2026-10-30")
        self.assertIn("月の情報はレポートにありません", page)

    def test_casual_weather_note_shown_verbatim(self):
        self.assertIn("気象メモ(レポート全期間): 首都圏は晴れ間が多い見込みです。", self.page())


class TableTest(Base):
    def test_all_candidates_listed_with_links(self):
        page = self.page("--top", "1")
        table = page[page.index("全候補の一覧"):]
        self.assertEqual(table.count("<tr><td>"), len(CASUAL) + len(HARDCORE))
        self.assertIn("<details open>", table)
        self.assertIn("10/17(土)", table)
        self.assertIn("10/18(日)", table)
        self.assertIn(f'href="{gr.maps_url(37.1, 139.2)}"', table)
        self.assertIn("tablewrap", table)  # 横スクロール用の包み


class TagsTest(Base):
    def test_far_and_island_tags_only_for_hardcore_not_in_casual(self):
        page = self.page()
        hard = page[page.index("硬派コース"):page.index("日曜の夜")]
        self.assertIn("遠征圏(東京から250km超)", hard)
        self.assertEqual(hard.count("遠征圏"), 2)  # 白米千枚田・白木峰展望台
        self.assertEqual(hard.count("離島(フェリー)"), 1)  # 佐渡市のみ
        # 気軽コースにもある奥只見ダムと、近場の地点には付かない
        okutadami = hard[hard.index("奥只見ダム"):hard.index("白米千枚田")]
        self.assertNotIn("遠征圏", okutadami)
        near = hard[hard.index("近場の地点"):]
        self.assertNotIn("遠征圏", near)
        self.assertNotIn("離島(フェリー)", near)
        casual = page[page.index("気軽コース"):page.index("硬派コース")]
        self.assertNotIn("遠征圏", casual)
        self.assertNotIn("離島(フェリー)", casual)


class AccessNotesTest(Base):
    def notes_file(self, notes):
        return self.write_json("notes.json", {"schema": wp.ACCESS_NOTES_SCHEMA, "notes": notes})

    def run_with_notes(self, notes_path):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = wp.main(["--report", str(self.report), "--access-notes", str(notes_path), "--out", str(self.out)], now=SAT)
        return code, err.getvalue()

    def test_note_and_tag_present(self):
        code, err = self.run_with_notes(self.notes_file({"奥只見ダム": "トンネル経由です。確認してください。"}))
        self.assertEqual(code, 0, err)
        page = self.out.read_text(encoding="utf-8")
        self.assertIn('<span class="tag warn">アクセス要確認</span>', page)
        self.assertIn("トンネル経由です。確認してください。", page)
        self.assertIn("確認済みの情報ではありません", page)
        self.assertNotIn("枝折峠</h4><div class=\"tags\"><span class=\"tag \">スコア 117</span><span class=\"tag \">東京から直線179km</span><span class=\"tag warn\">アクセス", page)

    def test_no_notes_no_tag(self):
        page = self.page()
        self.assertNotIn("アクセス要確認", page.split("<footer>")[0].split("出かける前に")[0])
        self.assertNotIn("確認済みの情報ではありません", page)

    def test_broken_notes_exit_5(self):
        p = self.dir / "bad_notes.json"
        p.write_text("{not json", encoding="utf-8")
        code, err = self.run_with_notes(p)
        self.assertEqual(code, 5)
        self.assertFalse(self.out.exists())

    def test_notes_escaped(self):
        code, _ = self.run_with_notes(self.notes_file({"奥只見ダム": "<script>x</script>"}))
        self.assertEqual(code, 0)
        self.assertNotIn("<script>x</script>", self.out.read_text(encoding="utf-8"))

    def test_repository_notes_match_spot_names(self):
        notes = json.loads((ROOT / "access_check_notes.json").read_text(encoding="utf-8"))
        self.assertEqual(notes["schema"], wp.ACCESS_NOTES_SCHEMA)
        self.assertIn("確認済みの事実ではありません", notes["_comment"])
        names = {s["name"] for s in json.loads((ROOT / "stargazing_spots.json").read_text(encoding="utf-8"))["spots"]}
        self.assertEqual(set(notes["notes"]) - names, set())
        self.assertEqual(len(notes["notes"]), 6)
        self.assertEqual(wp.load_access_notes(ROOT / "access_check_notes.json"), notes["notes"])


class CommentaryTest(Base):
    def run_with_commentary(self, obj, *argv):
        p = self.write_json("c.json", obj)
        return self.run_cli("--commentary", str(p), *argv)

    def test_good_commentary_rendered(self):
        code, _, err = self.run_with_commentary(GOOD_COMMENTARY)
        self.assertEqual(code, 0, err)
        self.assertEqual(err, "")  # /2 で weather 欄が無ければ警告もない
        page = self.out.read_text(encoding="utf-8")
        self.assertIn('<div class="box good"><h3>土曜が本命</h3>', page)
        self.assertIn('<div class="box "><h3>日曜は一段下がる</h3>', page)  # neutral は色クラスなし
        self.assertIn('<div class="box warn"><h3>銀河中心は狙えない</h3>', page)
        self.assertIn("補足の一行", page)
        self.assertNotIn("未作成", page)

    def test_without_commentary_says_not_written(self):
        page = self.page()
        self.assertIn("解説(結論)は未作成です。", page)
        self.assertIn("全候補の一覧", page)  # 数値の部分は出る
        self.assertIn(WEATHER_TEXT, page)  # 天気の概況は weekend-commentary と無関係に出る

    def test_html_in_commentary_is_escaped(self):
        obj = json.loads(json.dumps(GOOD_COMMENTARY))
        obj["verdict"][0]["title"] = "<img src=x onerror=alert(1)>"
        obj["verdict"][0]["body"] = "<script>alert(1)</script>&"
        obj["extra_notes"] = ["<i>x</i>"]
        code, _, err = self.run_with_commentary(obj)
        self.assertEqual(code, 0, err)
        page = self.out.read_text(encoding="utf-8")
        for raw in ("<img src=x", "<script>alert", "<i>x</i>"):
            self.assertNotIn(raw, page)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;&amp;", page)

    def test_invalid_commentary_exit_5_and_writes_nothing(self):
        def mutate(f):
            o = json.loads(json.dumps(GOOD_COMMENTARY))
            f(o)
            return o
        cases = {
            "schema違い": mutate(lambda o: o.update(schema="hoshibiyori-weekend-commentary/3")),
            "verdict欠け": mutate(lambda o: o.pop("verdict")),
            "verdictが5件": mutate(lambda o: o.update(verdict=o["verdict"] * 2)),
            "toneが不正": mutate(lambda o: o["verdict"][0].update(tone="red")),
            "titleが数値": mutate(lambda o: o["verdict"][0].update(title=3)),
            "bodyが無い": mutate(lambda o: o["verdict"][0].pop("body")),
            "extra_notesが文字列": mutate(lambda o: o.update(extra_notes="x")),
            "トップが配列": [],
        }
        for label, obj in cases.items():
            with self.subTest(label):
                code, _, err = self.run_with_commentary(obj)
                self.assertEqual(code, 5, label)
                self.assertTrue(err.strip(), label)
                self.assertFalse(self.out.exists(), label)

    def test_error_message_says_where(self):
        o = json.loads(json.dumps(GOOD_COMMENTARY))
        o["verdict"][1]["tone"] = "red"
        _, _, err = self.run_with_commentary(o)
        self.assertIn("verdict[1].tone", err)

    def test_broken_json_and_missing_file_exit_5(self):
        p = self.dir / "broken.json"
        p.write_text("{", encoding="utf-8")
        self.assertEqual(self.run_cli("--commentary", str(p))[0], 5)
        self.assertEqual(self.run_cli("--commentary", str(self.dir / "none.json"))[0], 5)

    def test_zero_verdicts_allowed(self):
        o = {"schema": wp.COMMENTARY_SCHEMA, "verdict": []}
        self.assertEqual(self.run_with_commentary(o)[0], 0)

    def test_legacy_v1_weather_is_ignored_with_warning(self):
        o = json.loads(json.dumps(GOOD_COMMENTARY))
        o["schema"] = "hoshibiyori-weekend-commentary/1"
        o["weather"] = {"bullets": ["古い実況: 6時の数値は1030hPaでした。"], "note": "旧note"}
        code, _, err = self.run_with_commentary(o)
        self.assertEqual(code, 0, err)  # エラーにしない
        self.assertIn("[警告] 解説JSONの weather 欄は廃止されたため無視しました", err)
        page = self.out.read_text(encoding="utf-8")
        self.assertNotIn("古い実況", page)
        self.assertNotIn("旧note", page)
        self.assertIn(WEATHER_TEXT, page)  # 概況は weather_map_commentary.json から

    def test_weather_field_in_v2_is_ignored_with_warning(self):
        o = json.loads(json.dumps(GOOD_COMMENTARY))
        o["weather"] = {"bullets": ["書いてはいけない"]}
        code, _, err = self.run_with_commentary(o)
        self.assertEqual(code, 0, err)
        self.assertIn("weather 欄は廃止", err)
        self.assertNotIn("書いてはいけない", self.out.read_text(encoding="utf-8"))


class VerdictCheckTest(Base):
    """verdict の施設名・時刻・件数などが候補データ(レポート)と一致するか。"""

    def setUp(self):
        super().setUp()
        # 地点マスター: レポートの候補に無い地点(ヘブンスそのはら)を語彙として持つ
        self.spots = self.write_json("spots.json", {"spots": [{"name": "奥只見ダム"}, {"name": "ヘブンスそのはら"},
                                                             {"name": "能登半島・白米千枚田"}]})

    def run_verdict(self, body, title="結論"):
        o = {"schema": wp.COMMENTARY_SCHEMA, "verdict": [{"title": title, "body": body, "tone": "good"}]}
        p = self.write_json("c.json", o)
        return self.run_cli("--commentary", str(p), "--spots", str(self.spots))

    def assertRejected(self, body, needle, title="結論"):
        self.out.unlink(missing_ok=True)
        code, _, err = self.run_verdict(body, title)
        self.assertEqual(code, 5, body)
        self.assertIn(needle, err)
        self.assertFalse(self.out.exists(), body)

    def test_correct_statements_pass(self):
        body = ("奥只見ダムは21:15から04:15まで、狙い目は23:00です。無月は6.8時間(土曜)と5.8時間(日曜)で、"
                "雲量は12%と3%、東京から174km、光害はALR 2.34です。気軽コースは4件、日曜の夜は1件です。"
                "白米千枚田は東京から250km超の遠征圏です。")
        code, _, err = self.run_verdict(body)
        self.assertEqual(code, 0, err)

    def test_unknown_facility(self):
        self.assertRejected("ヘブンスそのはらが狙い目です。", "地点「ヘブンスそのはら」はレポートの候補にありません")

    def test_alias_of_unknown_facility(self):
        self.assertRejected("ヘブンスそのはらは21:15です。", "ヘブンスそのはら")

    def test_time_not_in_any_candidate(self):
        self.assertRejected("奥只見ダムは23:45が狙い目です。", "時刻 23:45")

    def test_time_of_other_facility(self):
        # 22:29 は奥只見ダム(日曜)の見頃の始端。白州の時刻ではない
        self.assertRejected("白州は22:29からが見頃です。", "「白州」の見頃・狙い目ではありません")

    def test_count_mismatch(self):
        self.assertRejected("上位9件が条件を満たしました。", "件数「9件」")

    def test_hours_mismatch(self):
        self.assertRejected("土曜の無月は9.5時間あります。", "9.5時間")

    def test_percent_mismatch(self):
        self.assertRejected("雲量は77%です。", "77%")

    def test_distance_mismatch(self):
        self.assertRejected("東京から999kmです。", "999km")

    def test_alr_mismatch(self):
        self.assertRejected("光害はALR 9.99です。", "ALR 9.99")

    def test_magnitude_is_not_allowed(self):
        self.assertRejected("空の明るさは21.81 mag/arcsec²です。", "等級は無い")

    def test_errors_are_collected_and_title_is_checked(self):
        self.assertRejected("雲量は77%、東京から999kmです。", "999km", title="ヘブンスそのはら")
        _, _, err = self.run_verdict("雲量は77%、東京から999kmです。", title="ヘブンスそのはら")
        self.assertIn("verdict[0].title", err)
        self.assertIn("77%", err)

    def test_without_spots_master_report_names_still_checked(self):
        o = {"schema": wp.COMMENTARY_SCHEMA, "verdict": [{"title": "t", "body": "白州は22:29です。", "tone": "good"}]}
        p = self.write_json("c2.json", o)
        code, _, _ = self.run_cli("--commentary", str(p))  # 既定の --spots は存在しない
        self.assertEqual(code, 5)


class WeatherSectionTest(Base):
    """天気の概況は weather_map_commentary.json(schema /2)だけが情報源。"""

    def test_valid_v2_shows_text_and_three_images(self):
        page = self.page()
        w = page[page.index("<h2>天気の概況"):page.index("土曜の夜")]
        self.assertIn(WEATHER_TEXT, w)
        self.assertEqual(w.count('src="data:image/png;base64,'), 3)
        for label in ("実況", "24時間後の予想", "48時間後の予想"):
            self.assertIn(f"<figcaption>{label}</figcaption>", w)
        self.assertIn("天気図の取得時刻: 2026-10-17 10:57", w)
        self.assertIn("2026-10-17 10:57 取得の天気図をもとに記述した解説です。", w)
        self.assertIn("出典: 気象庁ホームページ(https://www.jma.go.jp/bosai/weather_map/)。", w)
        self.assertNotIn("未更新", w)

    def test_same_wording_as_report(self):
        # レポート本体の天気図ブロックの出典・説明の文言と同じ(generate_report の描画関数と揃っている)
        block = self.wmap_block(self.images)
        page = self.page()
        for phrase in ("出典: 気象庁ホームページ(https://www.jma.go.jp/bosai/weather_map/)。",
                       "取得の天気図をもとに記述した解説です。", "天気図の取得時刻:"):
            self.assertIn(phrase, block)
            self.assertIn(phrase, page)

    def assertNotUpdated(self, suffix=None, expect_text_absent=True):
        code, _, err = self.run_cli()
        self.assertEqual(code, 0, err)  # 終了コードは0
        page = self.out.read_text(encoding="utf-8")
        w = page[page.index("<h2>天気の概況"):page.index("土曜の夜")]
        self.assertIn("天気図の解説は未更新のため表示していません", w)
        if suffix:
            self.assertIn(suffix, w)
        self.assertNotIn("data:image/png", w)
        self.assertNotIn(WEATHER_TEXT, page)
        self.assertIn("未更新として扱います", err)
        return w

    def test_legacy_v1_is_not_shown(self):
        self.set_weather(weather_commentary(schema="hoshibiyori-weathermap-commentary/1"))
        self.assertNotUpdated("(最終更新 2026-10-17 10時)")

    def test_expired_is_not_shown(self):
        # based_on から13時間後(SAT 15:00 の13時間前は 02:00)。上限は12時間
        self.set_weather(weather_commentary(based_on="2026-10-17T01:30:00+09:00", images=self.rels(self.images)),
                         fetched_at=datetime(2026, 10, 17, 1, 30, tzinfo=JST))
        self.assertNotUpdated("(最終更新 2026-10-17 01時)")

    def test_future_based_on_is_not_shown(self):
        self.set_weather(weather_commentary(based_on="2026-10-17T16:00:00+09:00", images=self.rels(self.images)))
        self.assertNotUpdated()

    def test_missing_image_is_not_shown(self):
        rels = self.rels(self.images)
        rels["plus48h"] = "step5/weather_map_cache/nothing.png"
        self.set_weather(weather_commentary(images=rels))
        self.assertNotUpdated("(最終更新 2026-10-17 10時)")

    def test_bad_image_path_is_not_shown(self):
        rels = self.rels(self.images)
        rels["now"] = "../outside.png"
        self.set_weather(weather_commentary(images=rels))
        self.assertNotUpdated()

    def test_commentary_file_missing_shows_not_updated_without_suffix(self):
        self.wc_path.unlink()
        w = self.assertNotUpdated()
        self.assertNotIn("最終更新", w)

    def test_report_shows_different_fetch_time_is_not_shown(self):
        # 解説は有効(10:57)だが、レポートの天気図は別の取得(11:31)の画像・時刻 → 食い違い
        newer = self.make_images("1131")
        self.report.write_text(
            build_html(weather_map_html=gr.render_weather_map_section(
                newer, SAT, self.dir / "none.json", datetime(2026, 10, 17, 11, 31, tzinfo=JST), self.dir)),
            encoding="utf-8")
        self.assertNotUpdated("(最終更新 2026-10-17 10時)")

    def test_report_images_differ_but_same_time_is_not_shown(self):
        newer = self.make_images("1131")
        self.report.write_text(
            build_html(weather_map_html=gr.render_weather_map_section(
                newer, SAT, self.dir / "none.json", datetime(2026, 10, 17, 10, 57, tzinfo=JST), self.dir)),
            encoding="utf-8")
        self.assertNotUpdated()

    def test_report_without_weather_map_is_not_shown(self):
        self.report.write_text(build_html(), encoding="utf-8")
        self.assertNotUpdated("(最終更新 2026-10-17 10時)")

    def test_report_parse_of_weather_block(self):
        wm = wp.load_report(self.report.read_text(encoding="utf-8"))["wmap"]
        self.assertEqual(wm["fetched"], "2026-10-17 10:57")
        self.assertEqual(wm["srcs"], [p.relative_to(self.dir).as_posix() for p in self.images])
        self.assertIsNone(wp.load_report(build_html())["wmap"])

    def test_validation_logic_is_reused_not_copied(self):
        src = (ROOT / "scripts" / "weekend_page.py").read_text(encoding="utf-8")
        self.assertIn("gr._valid_commentary", src)
        self.assertIn("gr.load_weather_map_commentary", src)
        self.assertNotIn("WEATHER_MAP_COMMENTARY_MAX_AGE_HOURS =", src)


class OverwriteTest(Base):
    def test_existing_output_is_not_overwritten(self):
        self.out.write_text("先に作った版", encoding="utf-8")
        code, _, err = self.run_cli()
        self.assertEqual(code, 4)
        self.assertIn("既に存在します", err)
        self.assertIn("--force", err)
        self.assertEqual(self.out.read_text(encoding="utf-8"), "先に作った版")

    def test_force_overwrites(self):
        self.out.write_text("先に作った版", encoding="utf-8")
        code, _, _ = self.run_cli("--force")
        self.assertEqual(code, 0)
        self.assertIn("<!doctype html>", self.out.read_text(encoding="utf-8"))

    def test_default_path_uses_first_night(self):
        orig = wp.ROOT
        wp.ROOT = self.dir
        self.addCleanup(setattr, wp, "ROOT", orig)
        code, stdout, err = self.run_cli(with_out=False)
        self.assertEqual(code, 0, err)
        self.assertTrue((self.dir / "out" / "weekend_stargazing_20261017.html").is_file())
        self.assertEqual(self.run_cli(with_out=False)[0], 4)  # 2回目は拒否


class FreshnessAndStructureTest(Base):
    def test_stale_exit_2(self):
        self.report.write_text(build_html(generated="2026-10-16 23:59"), encoding="utf-8")
        code, _, err = self.run_cli()
        self.assertEqual(code, 2)
        self.assertIn("今日(2026-10-17)ではない", err)
        self.assertFalse(self.out.exists())

    def test_allow_stale_marks_page(self):
        self.report.write_text(build_html(generated="2026-10-16 23:59"), encoding="utf-8")
        page = self.page("--allow-stale")
        self.assertIn("【古いレポートです】", page)
        self.assertIn("2026-10-16 23:59", page)

    def test_fresh_page_has_no_stale_banner(self):
        self.assertNotIn("【古いレポートです】", self.page())

    def test_missing_report_exit_2(self):
        self.assertEqual(self.run_cli(report=self.dir / "nothing.html")[0], 2)

    def test_structure_changed_exit_3(self):
        cases = {
            "月齢タイムラインが無い": build_html().replace("moon-tick", "moon-x"),
            "コースが無い": build_html().replace("cand-group", "cand-grp"),
            "フッターが無い": build_html().replace("page-footer", "pf"),
            "ヘッダーが無い": build_html().replace("target-line", "tl"),
        }
        for label, text in cases.items():
            with self.subTest(label):
                self.report.write_text(text, encoding="utf-8")
                code, _, err = self.run_cli()
                self.assertEqual(code, 3, label)
                self.assertFalse(self.out.exists())
                self.assertIn("解析失敗", err)

    def test_footer_attribution_copied(self):
        page = self.page()
        self.assertIn("Open-Meteo.com", page.split("<footer>")[1])
        self.assertIn("気象庁その他の機関による予報・警報ではありません", page.split("<footer>")[1])

    def test_checklist_items(self):
        page = self.page()
        for key in ("予報の更新", "アクセス", "雲量の見方", "寒さ・安全"):
            self.assertIn(key, page)
        self.assertIn("2026-10-17 11:20 JST", page)


if __name__ == "__main__":
    unittest.main()
