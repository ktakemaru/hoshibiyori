"""見本HTML(戦場ヶ原 2026-10-09 の星空ガイド)から、テスト用のゴールデン(数値JSON・解説JSON)を作る。

見本は読み取り専用。通信しない(月・出来事の計算に de421.bsp を使う)。
使い方:
    py -X utf8 scripts/extract_sky_guide_sample.py --sample <見本.html>
出力: tests/fixtures/sky_guide/senjogahara_20261009_{data,commentary}.json
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from skyfield.api import load  # noqa: E402

from skyguide import astro  # noqa: E402
from skyguide.render import COMMENTARY_SCHEMA, DATA_SCHEMA  # noqa: E402

OUT_DIR = ROOT / "tests" / "fixtures" / "sky_guide"
SPOT_ID = "curated:006"
SPOT_META = {"name": "戦場ヶ原", "prefecture": "栃木県", "municipality": "日光市"}
CONFIRMED_PEAKS = {"男体山"}  # 見本が「方位と標高が一致して確度が高い」と明記している山


def _js_literal(text: str, name: str):
    """`var NAME = <リテラル>;` をnodeで評価してJSONにする(キーが引用符なしのJSオブジェクト)。"""
    m = re.search(r"var " + name + r" = (.*?);\n\n?  (?:var|//)", text, re.S)
    src = m.group(1)
    out = subprocess.run(["node", "-e", f"console.log(JSON.stringify({src}))"], capture_output=True, text=True, check=True, encoding="utf-8")
    return json.loads(out.stdout)


class _Sections(HTMLParser):
    """見本の固定構造から文章を取り出す(タグの入れ子は浅い前提)。"""

    def __init__(self):
        super().__init__()
        self.stack, self.cur = [], None
        self.out = {"lead": "", "facts": [], "rows": [], "tips": [], "notes": [], "footer": [], "cloud_note": ""}
        self._buf, self._cls, self._in = "", None, {}

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = a.get("class", "")
        self.stack.append((tag, cls))
        if tag == "b" and self.cur in ("td",):
            self._buf += "**"
        if tag == "div" and cls == "fact":
            self.out["facts"].append({})
        if tag == "span" and cls in ("k", "v", "s"):
            self.cur = "fact_" + cls; self._buf = ""
        if tag == "tr":
            self._row = []
        if tag == "td":
            self.cur = "td"; self._buf = ""
        if tag == "div" and cls == "tip":
            self.out["tips"].append({})
        if tag == "h3" and any(c == "tip" for _, c in self.stack):
            self.cur = "tip_h3"; self._buf = ""
        if tag == "p":
            self.cur = "p"; self._buf = ""
        if tag == "footer":
            self.cur = "footer"
        if tag == "span" and any(t == "footer" for t, _ in self.stack) and cls == "":
            self.cur = "footer_span"; self._buf = ""

    def handle_endtag(self, tag):
        t, cls = self.stack.pop()
        txt = self._buf.strip()
        if tag == "b" and self.cur == "td":
            self._buf += "**"
        if tag == "span" and self.cur and self.cur.startswith("fact_"):
            self.out["facts"][-1][{"k": "key", "v": "value", "s": "sub"}[self.cur[-1]]] = txt
            self.cur = None
        elif tag == "td":
            self._row.append(txt); self.cur = None
        elif tag == "tr" and getattr(self, "_row", None):
            self.out["rows"].append(self._row); self._row = []
        elif tag == "h3" and self.cur == "tip_h3":
            self.out["tips"][-1]["title"] = txt; self.cur = None
        elif tag == "p":
            if cls == "lead" and not self.out["lead"] and any(c == "head" for _, c in self.stack):
                self.out["lead"] = txt
            elif cls == "lead":
                pass
            elif cls == "note" and any(c == "cloud" for _, c in self.stack):
                self.out["cloud_note"] = txt
            elif cls == "note":
                self.out["notes"].append(txt)
            elif any(c == "tip" for _, c in self.stack):
                self.out["tips"][-1]["body"] = txt
            self.cur = None
        elif tag == "span" and self.cur == "footer_span":
            self.out["footer"].append(txt); self.cur = None

    def handle_data(self, data):
        if self.cur:
            self._buf += data


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", required=True)
    args = ap.parse_args()
    text = Path(args.sample).read_text(encoding="utf-8")
    D = json.loads(re.search(r"var D = (\{.*?\});\n", text, re.S).group(1))
    HZ = json.loads(re.search(r"var HZ = (\[.*?\]);", text, re.S).group(1))
    CLOUD = _js_literal(text, "CLOUD")
    PEAKS = _js_literal(text, "PEAKS")
    CARDS = _js_literal(text, "CARDS")
    P = _Sections(); P.feed(text); o = P.out

    spots = json.loads((ROOT / "stargazing_spots.json").read_text(encoding="utf-8"))["spots"]
    s = next(x for x in spots if x["id"] == SPOT_ID)
    lat, lon, elev = s["lat"], s["lon"], s["elevation_m"]
    ts = load.timescale(); eph = load(str(astro.EPHEMERIS_PATH))
    start = datetime(2026, 10, 9, 18, 40, tzinfo=astro.JST)
    times_dt = astro.time_grid(start, 20, len(D["times"]))
    assert [t.strftime("%H:%M") for t in times_dt] == D["times"]
    computed = astro.compute_frames(ts, eph, lat, lon, elev, times_dt)  # 月の列だけを使う(他は見本の値を保持)
    frames = []
    for f, c in zip(D["frames"], computed):
        f = dict(f); f["moon"] = c["moon"]; frames.append(f)

    sys.path.insert(0, str(ROOT))
    import explore_hoshibiyori as ex
    ds, de = ex.find_astro_dark_events(ts, eph, lat, lon, datetime(2026, 10, 9, tzinfo=astro.JST))
    events = astro.compute_events(ts, eph, lat, lon, elev, ds, de, HZ)
    hours = [{"h": h, "pct": CLOUD[h]} for h in ["18", "19", "20", "21", "22", "23", "00", "01", "02", "03", "04", "05"]]

    data = {
        "schema": DATA_SCHEMA, "generated_at": "golden(見本 2026-10-09 から抽出。月・出来事・ピーク候補のみ再計算)",
        "spot": {**SPOT_META, "lat": lat, "lon": lon, "elevation_m": elev, "lpi": s.get("lpi"), "mpsas": s.get("mpsas"),  # 段階LP3で地点ファイルから外した(見本の抽出時のみ参照)
               
                 "coordinate_source": s["coordinate_source"], "elevation_source": "国土地理院DEM(stargazing_spots.json)"},
        "night": {"date": "2026-10-09", "dark_start": ds.strftime("%H:%M"), "dark_end": de.strftime("%H:%M"),
                  "dark_hours": round((de - ds).total_seconds() / 3600, 1)},
        "times": D["times"], "frames": frames, "starmag": D["starmag"], "horizon_deg": HZ,
        "horizon_source": s["horizon_profile"],
        "cloud": {"label": "視界遮蔽雲量 %(JMA MSM、戦場ヶ原の標高で補正)", "source": "見本から抽出", "hours": hours},
        "cloud_omitted_reason": None,
        "peak_candidates": astro.detect_ridge_peaks(HZ), "events": events,
        "attribution": [o["footer"][0]], "disclaimer": [o["footer"][1]],
    }
    peaks = [{"az": p["az"], "name": p["name"], "basis": "確認済み" if p["name"] in CONFIRMED_PEAKS else "推定"} for p in PEAKS]
    cards = [{"id": c["id"], "when": c["when"], "time": c["time"], "az": c["az"], "frame": c["fr"], "title": c["title"],
              "tags": c["tags"], "body": c["body"], "list": c["list"]} for c in CARDS]
    comm = {
        "schema": COMMENTARY_SCHEMA, "heading": "戦場ヶ原の星空", "title": "戦場ヶ原 星空ガイド",
        "lead": o["lead"], "facts": o["facts"], "cloud_note": o["cloud_note"], "initial_time": "21:20",
        "cards": cards, "peaks": peaks,
        "directions": [{"label": r[0], "elevation": r[1], "terrain": r[2], "sky": r[3]} for r in o["rows"]],
        "directions_note": o["notes"][0], "tips": o["tips"],
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "senjogahara_20261009_data.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    (OUT_DIR / "senjogahara_20261009_commentary.json").write_text(json.dumps(comm, ensure_ascii=False, indent=1), encoding="utf-8")
    print("facts", len(comm["facts"]), "cards", len(cards), "rows", len(comm["directions"]), "tips", len(comm["tips"]), "notes", len(o["notes"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
