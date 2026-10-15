"""星空ガイド(skyguide/)のテスト。通信しない。

天文計算を使うテストは de421.bsp(Skyfieldの暦、初回自動ダウンロード=通信)が無い環境ではスキップする。
ブラウザでの描画テストは HOSHIBIYORI_BROWSER_TESTS=1 のときだけ実行する(Playwright と Chromium が必要)。
"""
import copy
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from skyguide import render  # noqa: E402
from skyguide.render import SkyGuideError, check_html, embed_json, render_html, validate  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "sky_guide"
SAMPLE = ROOT / "docs" / "examples" / "senjogahara_sky_guide_20261009.html"
HAS_BSP = (ROOT / "step1_astronomy" / "de421.bsp").exists()


def golden():
    d = json.loads((FIX / "senjogahara_20261009_data.json").read_text(encoding="utf-8"))
    c = json.loads((FIX / "senjogahara_20261009_commentary.json").read_text(encoding="utf-8"))
    return d, c


class _Scan(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids, self.classes, self.tags, self.scripts = set(), {}, {}, []
        self._in_script = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        self.tags[tag] = self.tags.get(tag, 0) + 1
        if "id" in a:
            self.ids.add(a["id"])
        for c in a.get("class", "").split():
            self.classes[c] = self.classes.get(c, 0) + 1
        if tag == "script":
            self._in_script = True
            self.scripts.append("")

    def handle_endtag(self, tag):
        if tag == "script":
            self._in_script = False

    def handle_data(self, data):
        if self._in_script:
            self.scripts[-1] += data


def scan(doc):
    s = _Scan()
    s.feed(doc)
    return s


class RenderTest(unittest.TestCase):
    def setUp(self):
        self.data, self.comm = golden()
        self.doc = render_html(self.data, self.comm)

    def test_required_elements_and_ids(self):
        s = scan(self.doc)
        for i in render.REQUIRED_HTML_IDS + render.REQUIRED_SECTION_IDS:
            self.assertIn(i, s.ids)
        self.assertEqual(s.classes["fact"], 4)
        self.assertEqual(s.classes["card"], 6)
        self.assertEqual(s.classes["tip"], 6)

    def test_same_structure_as_sample(self):
        a, b = scan(self.doc), scan(SAMPLE.read_text(encoding="utf-8"))
        # 見本は構図カード・タグをJSで組み立てる(静的HTMLには無い)ので、静的な部分だけ比べ、カードは見本のデータ件数と比べる
        for cls in ("fact", "tip", "cwrap", "tablewrap", "controls", "readout", "cloud", "facts", "cards", "tips"):
            self.assertEqual(a.classes.get(cls, 0), b.classes.get(cls, 0), cls)
        for tag in ("tr", "canvas", "h2", "table", "section"):
            self.assertEqual(a.tags.get(tag), b.tags.get(tag), tag)
        sample = SAMPLE.read_text(encoding="utf-8")
        self.assertEqual(a.classes["card"], len(re.findall(r'title: "', sample)))
        n_tags = len(re.findall(r'\["[^"]*", "(?:hard|hot|)"\]', sample))
        self.assertEqual(a.classes["tag"], n_tags)
        for i in ("play", "slider", "facing", "readout", "allsky", "pano", "cards", "bars", "hours", "timeLabel"):
            self.assertIn(i, a.ids)
            self.assertIn(i, b.ids)

    def test_sample_sky_data_equals_golden(self):
        t = SAMPLE.read_text(encoding="utf-8")
        D = json.loads(re.search(r"var D = (\{.*?\});\n", t, re.S).group(1))
        HZ = json.loads(re.search(r"var HZ = (\[.*?\]);", t, re.S).group(1))
        self.assertEqual(D["times"], self.data["times"])
        self.assertEqual(HZ, self.data["horizon_deg"])
        self.assertEqual(D["starmag"], self.data["starmag"])
        for fs, fg in zip(D["frames"], self.data["frames"]):
            for k in ("stars", "plane", "planets", "gc"):
                self.assertEqual(fs[k], fg[k])

    def test_embedded_json_roundtrip(self):
        s = scan(self.doc)
        embedded = {}
        for body in s.scripts:
            body = body.strip()
            if body.startswith("{"):
                j = json.loads(body)
                embedded[j.get("schema")] = j
        self.assertEqual(embedded[render.DATA_SCHEMA], self.data)
        self.assertEqual(embedded[render.COMMENTARY_SCHEMA], self.comm)

    def test_script_close_tag_in_text_does_not_break(self):
        c = copy.deepcopy(self.comm)
        c["lead"] = "テスト </script><script>alert(1)</script> <!-- &   の文章"
        c["tips"][0]["body"] = "</script></body>"
        doc = render_html(self.data, c)
        s = scan(doc)
        self.assertEqual(len(s.scripts), 3)  # sg-data / sg-commentary / 本体のみ
        embedded = [json.loads(b) for b in s.scripts if b.strip().startswith("{")]
        self.assertIn(c["lead"], [e.get("lead") for e in embedded])
        self.assertNotIn("<script>alert", doc)

    def test_embed_json_escapes(self):
        out = embed_json({"a": "</script><!--& "})
        for bad in ("</script", "<!--", " "):
            self.assertNotIn(bad, out)
        self.assertEqual(json.loads(out)["a"], "</script><!--& ")

    def test_removing_simulator_is_an_error(self):
        stripped = re.sub(r'<section class="sim" id="sim">.*?</section>', "", self.doc, flags=re.S)
        with self.assertRaises(SkyGuideError):
            check_html(stripped)
        d = copy.deepcopy(self.data)
        del d["frames"]
        with self.assertRaises(SkyGuideError):
            render_html(d, self.comm)

    def test_card_time_not_in_times_is_error(self):
        c = copy.deepcopy(self.comm)
        c["cards"][0]["time"] = "12:00"
        with self.assertRaisesRegex(SkyGuideError, "times"):
            render_html(self.data, c)

    def test_out_of_range_values_are_errors(self):
        muts = (lambda c: c["cards"][0].update(az=400), lambda c: c["cards"][0]["frame"].update(w=0),
                lambda c: c["cards"][0]["frame"].update(alt=120), lambda c: c.update(initial_time="12:00"),
                lambda c: c.update(facts=c["facts"][:3]), lambda c: c.update(cards=[]),
                lambda c: c.update(tips=[]), lambda c: c.update(directions=[]), lambda c: c.update(lead=""))
        for mut in muts:
            c = copy.deepcopy(self.comm)
            mut(c)
            with self.assertRaises(SkyGuideError):
                render_html(self.data, c)

    def test_peak_without_basis_or_candidate_is_rejected(self):
        c = copy.deepcopy(self.comm)
        del c["peaks"][0]["basis"]
        with self.assertRaisesRegex(SkyGuideError, "basis"):
            render_html(self.data, c)
        c = copy.deepcopy(self.comm)
        c["peaks"][0]["basis"] = "たぶん"
        with self.assertRaises(SkyGuideError):
            render_html(self.data, c)
        c = copy.deepcopy(self.comm)
        c["peaks"][0]["az"] = 200
        with self.assertRaisesRegex(SkyGuideError, "ピーク候補"):
            render_html(self.data, c)

    def test_cloud_omitted_needs_and_shows_reason(self):
        d = copy.deepcopy(self.data)
        d["cloud"] = None
        d["cloud_omitted_reason"] = None
        with self.assertRaisesRegex(SkyGuideError, "cloud_omitted_reason"):
            render_html(d, self.comm)
        d["cloud_omitted_reason"] = "過去の日付のため予報が取得できません"
        doc = render_html(d, self.comm)
        self.assertIn("過去の日付のため予報が取得できません", doc)
        self.assertNotIn('id="bars"', doc)

    def test_out_of_range_data_is_error(self):
        d = copy.deepcopy(self.data)
        d["horizon_deg"] = d["horizon_deg"][:359]
        with self.assertRaises(SkyGuideError):
            validate(d, self.comm)
        d = copy.deepcopy(self.data)
        d["frames"][0]["moon"]["illum"] = 2
        with self.assertRaises(SkyGuideError):
            validate(d, self.comm)
        d = copy.deepcopy(self.data)
        d["times"][1] = "25:00"
        with self.assertRaises(SkyGuideError):
            validate(d, self.comm)

    def test_variable_length_night_and_midnight_crossing(self):
        d = copy.deepcopy(self.data)
        d["times"], d["frames"] = d["times"][:5], d["frames"][:5]
        c = copy.deepcopy(self.comm)
        c["initial_time"] = d["times"][2]
        c["cards"] = [copy.deepcopy(c["cards"][0])]
        c["cards"][0]["time"] = d["times"][1]
        render_html(d, c)  # 短い夜でも検証・描画に通る
        d2 = copy.deepcopy(self.data)
        i = d2["times"].index("23:40")
        d2["times"], d2["frames"] = d2["times"][i:i + 3], d2["frames"][i:i + 3]  # 23:40, 00:00, 00:20 の日付またぎ
        c2 = copy.deepcopy(self.comm)
        c2["initial_time"] = "00:00"
        c2["cards"] = [copy.deepcopy(self.comm["cards"][4])]
        render_html(d2, c2)

    def test_template_has_no_hardcoded_night_values(self):
        js = (ROOT / "skyguide" / "sky_guide.js").read_text(encoding="utf-8")
        tpl = (ROOT / "skyguide" / "template.html").read_text(encoding="utf-8")
        self.assertNotIn('max="29"', js + tpl)
        self.assertNotRegex(js, r'\["18",\s*"19"')
        self.assertNotIn("戦場ヶ原", tpl + js)

    @unittest.skipUnless(shutil.which("node"), "node が無い")
    def test_js_syntax(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "sg.js"
            p.write_text((ROOT / "skyguide" / "sky_guide.js").read_text(encoding="utf-8"), encoding="utf-8")
            r = subprocess.run(["node", "--check", str(p)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)


@unittest.skipUnless(HAS_BSP, "de421.bsp が無い(初回は自動ダウンロード=通信が要るため、通信しないテストではスキップ)")
class AstroTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from datetime import datetime
        from skyfield.api import load
        from skyguide import astro
        cls.astro = astro
        cls.ts = load.timescale()
        cls.eph = load(str(astro.EPHEMERIS_PATH))
        cls.lat, cls.lon, cls.elev = 36.778887, 139.442674, 1392.78
        cls.times = astro.time_grid(datetime(2026, 10, 9, 18, 40, tzinfo=astro.JST), 20, 30)
        cls.frames = astro.compute_frames(cls.ts, cls.eph, cls.lat, cls.lon, cls.elev, cls.times)

    def test_polaris_altitude_close_to_latitude(self):
        for f in self.frames:
            self.assertAlmostEqual(f["stars"]["ポラリス(北極星)"][1], self.lat, delta=1.5)  # 極から約0.7°離れているため

    def test_reproduces_sample_within_half_degree(self):
        d, _ = golden()
        worst = 0.0
        for m, s in zip(self.frames, d["frames"]):
            for grp in ("stars", "planets"):
                for n, v in s[grp].items():
                    daz = abs(((m[grp][n][0] - v[0] + 180) % 360) - 180)
                    worst = max(worst, abs(m[grp][n][1] - v[1]), daz)
            worst = max(worst, abs(m["gc"][1] - s["gc"][1]))
        self.assertLess(worst, 0.5)

    def test_galactic_centre_direction(self):
        ra, dec = self.astro.galactic_to_radec(0.0, 0.0)
        self.assertAlmostEqual(ra, 17.76, delta=0.1)
        self.assertAlmostEqual(dec, -28.94, delta=0.1)

    def test_moon_has_phase_fields_and_is_down_on_sample_night(self):
        for f in self.frames:
            m = f["moon"]
            self.assertLess(m["alt"], 0)
            self.assertTrue(0 <= m["illum"] <= 1)
            self.assertIsInstance(m["waxing"], bool)
        self.assertFalse(self.frames[0]["moon"]["waxing"])  # 新月前日は欠けていく

    def test_deterministic_events_and_peaks(self):
        from datetime import datetime
        import explore_hoshibiyori as ex
        d, _ = golden()
        hz = d["horizon_deg"]
        ds, de = ex.find_astro_dark_events(self.ts, self.eph, self.lat, self.lon, datetime(2026, 10, 9, tzinfo=self.astro.JST))
        e1 = self.astro.compute_events(self.ts, self.eph, self.lat, self.lon, self.elev, ds, de, hz)
        e2 = self.astro.compute_events(self.ts, self.eph, self.lat, self.lon, self.elev, ds, de, hz)
        self.assertEqual(e1, e2)
        self.assertEqual(e1, d["events"])
        types = {e["type"] for e in e1}
        self.assertTrue({"gc_above_ridge", "polaris_altitude", "planet_above_ridge", "moon_below_horizon_all_night"} <= types)
        peaks = self.astro.detect_ridge_peaks(hz)
        self.assertEqual(peaks, d["peak_candidates"])
        self.assertTrue(any(abs(p["az"] - 107) <= 1 and abs(p["alt"] - 14.4) < 0.2 for p in peaks))  # 男体山

    def test_build_data_offline_is_deterministic_and_omits_cloud_with_reason(self):
        from datetime import date
        from skyguide import build
        spot = build.load_spot("戦場ヶ原")
        with mock.patch("requests.get", side_effect=AssertionError("network used")), \
             mock.patch("requests.Session.get", side_effect=AssertionError("network used")):
            a = build.build_data(spot=spot, night_date=date(2026, 10, 9))
            b = build.build_data(spot=spot, night_date=date(2026, 10, 9))
        for x in (a, b):
            x.pop("generated_at")
        self.assertEqual(a, b)
        g, gc = golden()
        self.assertEqual(a["times"], g["times"])
        self.assertEqual(a["horizon_deg"], g["horizon_deg"])
        if a["cloud"] is None:
            self.assertTrue(a["cloud_omitted_reason"])
        a["generated_at"] = "x"
        render_html(a, gc)  # 数値JSONは、そのまま解説と組み合わせて描画できる


@unittest.skipUnless(os.environ.get("HOSHIBIYORI_BROWSER_TESTS") == "1", "HOSHIBIYORI_BROWSER_TESTS=1 のときだけ実行")
class BrowserTest(unittest.TestCase):
    def test_render_at_two_widths(self):
        from playwright.sync_api import sync_playwright
        d, c = golden()
        js = """s=>{const c=document.querySelector(s);const d=c.getContext('2d').getImageData(0,0,c.width,c.height).data;
                 let n=0;for(let i=0;i<d.length;i+=4){if(d[i]>60||d[i+1]>60||d[i+2]>60)n++}return n}"""
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "g.html"
            f.write_text(render_html(d, c), encoding="utf-8")
            with sync_playwright() as p:
                b = p.chromium.launch()
                for w in (390, 980):
                    pg = b.new_page(viewport={"width": w, "height": 900})
                    errs = []
                    pg.on("pageerror", lambda e: errs.append(str(e)))
                    pg.on("console", lambda m: errs.append(m.text) if m.type == "error" and "ERR_FAILED" not in m.text else None)
                    pg.route("**/*", lambda r: r.continue_() if r.request.url.startswith("file:") else r.abort())  # 外部(フォント)へは出ない
                    pg.goto(f.as_uri())
                    pg.wait_for_timeout(300)
                    self.assertGreater(pg.evaluate(js, "#allsky"), 1000)
                    self.assertGreater(pg.evaluate(js, "#pano"), 1000)
                    self.assertTrue(pg.evaluate("document.documentElement.scrollWidth <= window.innerWidth"))
                    for i, card in enumerate(c["cards"]):
                        pg.locator("button[data-card]").nth(i).click()
                        pg.wait_for_timeout(200)
                        self.assertEqual(pg.inner_text("#timeLabel"), card["time"])
                        self.assertGreater(pg.evaluate(js, "#pano"), 500)
                    self.assertEqual(errs, [])
                    pg.close()
                b.close()


if __name__ == "__main__":
    unittest.main()
