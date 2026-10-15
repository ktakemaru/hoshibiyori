"""数値JSON + 解説JSON → 1ファイル完結のHTML(星空ガイド+星空シミュレーター)。

HTMLは手で書かない。固定のテンプレート(template.html・sky_guide.css・sky_guide.js)に2つのJSONを差し込む。
必須要素が欠けている・範囲外の値がある場合は SkyGuideError で止める。
"""
from __future__ import annotations

import html
import json
import re
from datetime import date, timedelta
from pathlib import Path

DATA_SCHEMA = "hoshibiyori-skyguide-data/1"
COMMENTARY_SCHEMA = "hoshibiyori-skyguide-commentary/1"
BASIS_VALUES = ("確認済み", "推定")
PEAK_MATCH_DEG = 3.0
_PKG = Path(__file__).parent

# 描画後のHTMLに必ず含まれる要素(欠けたらエラー)
REQUIRED_HTML_IDS = ("sim", "play", "slider", "facing", "readout", "allsky", "pano", "cards", "sg-data", "sg-commentary")
REQUIRED_SECTION_IDS = ("conditions", "mountains", "tips", "footer")


class SkyGuideError(ValueError):
    pass


def _need(cond: bool, msg: str) -> None:
    if not cond:
        raise SkyGuideError(msg)


def _is_hhmm(s) -> bool:
    return isinstance(s, str) and re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", s) is not None


def _num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def validate(data: dict, commentary: dict) -> None:
    _need(data.get("schema") == DATA_SCHEMA, f"数値JSONの schema は {DATA_SCHEMA} が必要です")
    _need(commentary.get("schema") == COMMENTARY_SCHEMA, f"解説JSONの schema は {COMMENTARY_SCHEMA} が必要です")
    for k in ("spot", "night", "times", "frames", "starmag", "horizon_deg", "peak_candidates", "attribution", "disclaimer"):
        _need(k in data, f"数値JSONに {k} がありません")
    times, frames = data["times"], data["frames"]
    _need(isinstance(times, list) and len(times) >= 2, "times は2件以上の配列が必要です(星空シミュレーターに必須)")
    _need(all(_is_hhmm(t) for t in times), "times は HH:MM 形式です")
    _need(len(set(times)) == len(times), "times に重複があります")
    _need(isinstance(frames, list) and len(frames) == len(times), "frames の件数が times と一致しません")
    for i, f in enumerate(frames):
        for k in ("stars", "plane", "planets", "gc", "moon"):
            _need(k in f, f"frames[{i}] に {k} がありません")
        _need(len(f["plane"]) >= 3, f"frames[{i}].plane が短すぎます")
        for n, v in f["stars"].items():
            _need(n in data["starmag"], f"starmag に {n} がありません")
            _need(len(v) == 2 and all(_num(x) for x in v) and -90 <= v[1] <= 90 and 0 <= v[0] < 360.0001, f"frames[{i}].stars[{n}] が範囲外です")
        m = f["moon"]
        _need(all(k in m for k in ("az", "alt", "illum", "waxing")), f"frames[{i}].moon に az/alt/illum/waxing が必要です")
        _need(0 <= m["illum"] <= 1, f"frames[{i}].moon.illum は0〜1です")
    hz = data["horizon_deg"]
    _need(isinstance(hz, list) and len(hz) == 360 and all(_num(x) for x in hz), "horizon_deg は360個の数値が必要です")
    cloud = data.get("cloud")
    if cloud is None:
        _need(bool(data.get("cloud_omitted_reason")), "雲量を省略するときは cloud_omitted_reason(理由)が必要です")
    else:
        _need(cloud.get("hours") and all("h" in c and _num(c.get("pct")) and 0 <= c["pct"] <= 100 for c in cloud["hours"]),
              "cloud.hours は {h, pct(0〜100)} の配列です")
    # --- 解説 ---
    _need(bool(commentary.get("lead")), "解説JSONに lead(リード文)が必要です")
    _need(isinstance(commentary.get("facts"), list) and len(commentary["facts"]) == 4, "facts(この夜の条件)はちょうど4項目です")
    for f in commentary["facts"]:
        _need(all(f.get(k) for k in ("key", "value", "sub")), "facts の各項目に key/value/sub が必要です")
    cards = commentary.get("cards")
    _need(isinstance(cards, list) and len(cards) >= 1, "cards(狙える構図)は1件以上必要です")
    ids = set()
    for c in cards:
        for k in ("id", "when", "time", "az", "frame", "title", "tags", "body", "list"):
            _need(k in c, f"card {c.get('id')} に {k} がありません")
        _need(c["id"] not in ids, f"card id が重複しています: {c['id']}")
        ids.add(c["id"])
        _need(c["time"] in times, f"card {c['id']} の time {c['time']} が times にありません")
        _need(_num(c["az"]) and 0 <= c["az"] < 360, f"card {c['id']} の az は0以上360未満です")
        fr = c["frame"]
        _need(all(_num(fr.get(k)) for k in ("az", "alt", "w", "h")) and fr.get("lens"), f"card {c['id']} の frame に az/alt/w/h/lens が必要です")
        _need(0 <= fr["az"] < 360 and -10 <= fr["alt"] <= 90 and 0 < fr["w"] <= 180 and 0 < fr["h"] <= 180,
              f"card {c['id']} の frame が範囲外です")
    if "initial_time" in commentary:
        _need(commentary["initial_time"] in times, "initial_time が times にありません")
    peaks = commentary.get("peaks", [])
    for p in peaks:
        _need(p.get("basis") in BASIS_VALUES, f"山名 {p.get('name')} の basis は {BASIS_VALUES} のいずれかが必要です")
        _need(bool(p.get("name")) and _num(p.get("az")), "peaks の各項目に name と az が必要です")
        near = [c for c in data["peak_candidates"] if abs(((c["az"] - p["az"] + 540) % 360) - 180) <= PEAK_MATCH_DEG]
        _need(bool(near), f"山名 {p['name']} (方位{p['az']}°)に対応するピーク候補が数値JSONにありません")
    dirs = commentary.get("directions")
    _need(isinstance(dirs, list) and len(dirs) >= 1, "directions(周囲の山と方位の表)は1件以上必要です")
    for d in dirs:
        _need(all(d.get(k) for k in ("label", "elevation", "terrain", "sky")), "directions の各項目に label/elevation/terrain/sky が必要です")
    tips = commentary.get("tips")
    _need(isinstance(tips, list) and len(tips) >= 1, "tips(撮影メモ)は1件以上必要です")
    for t in tips:
        _need(bool(t.get("title")) and bool(t.get("body")), "tips の各項目に title/body が必要です")


def check_html(doc: str) -> None:
    """描画後のHTMLの必須要素の検査(星空シミュレーターが無ければエラー)。"""
    for i in REQUIRED_HTML_IDS + REQUIRED_SECTION_IDS:
        _need(f'id="{i}"' in doc, f"HTMLに必須要素 id={i} がありません")


def _e(s) -> str:
    return html.escape(str(s), quote=True)


def _inline(s: str) -> str:
    """エスケープしたうえで **太字** だけを許す。"""
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", _e(s))


def embed_json(obj) -> str:
    """<script type="application/json"> に入れるJSON。`</script>` 等で壊れないようにエスケープする。"""
    s = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    return s.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def _eyebrow(data: dict) -> str:
    d = date.fromisoformat(data["night"]["date"])
    nx = d + timedelta(days=1)
    return f"hoshibiyori / {d.isoformat()} 夜 → {nx.month:02d}-{nx.day:02d} 朝"


def _header(data, comm) -> str:
    s = data["spot"]
    place = " ".join(x for x in (s.get("prefecture"), s.get("municipality")) if x)
    lpi = ""
    if s.get("lpi") is not None:
        lpi = f'<span>光害 <b>LPI {s["lpi"]:.2f}</b> / <b>{s["mpsas"]:.1f} mag/arcsec²</b></span>'
    return (f'  <header class="head" id="header">\n    <div class="eyebrow">{_e(_eyebrow(data))}</div>\n'
            f'    <h1>{_e(comm.get("heading") or s["name"] + "の星空")}</h1>\n    <p class="lead">{_inline(comm["lead"])}</p>\n'
            f'    <div class="meta">\n      <span>{_e(place)} <b>標高 {s["elevation_m"]:,.0f} m</b></span>\n'
            f'      <span>北緯 <b>{s["lat"]:.3f}°</b> 東経 <b>{s["lon"]:.3f}°</b></span>\n      {lpi}\n    </div>\n  </header>')


def _conditions(data, comm) -> str:
    facts = "\n".join(f'      <div class="fact"><span class="k">{_e(f["key"])}</span><span class="v">{_e(f["value"])}</span>'
                      f'<span class="s">{_e(f["sub"])}</span></div>' for f in comm["facts"])
    cloud = data.get("cloud")
    if cloud:
        note = comm.get("cloud_note") or "全天の平均値で、どの方角に雲が残るかは分かりません。当日の空は現地で確認してください。"
        cbox = (f'    <div class="cloud" id="cloud">\n      <div class="eyebrow">{_e(cloud.get("label", "視界遮蔽雲量 %"))}</div>\n'
                '      <div class="bars" id="bars"></div>\n      <div class="hours" id="hours"></div>\n'
                f'      <p class="note">{_e(note)}</p>\n    </div>')
    else:
        cbox = (f'    <div class="cloud-omitted" id="cloud-omitted"><div class="eyebrow">視界遮蔽雲量</div>\n'
                f'      <p class="note">雲量は表示していません。理由: {_e(data["cloud_omitted_reason"])}</p></div>')
    return f'  <section id="conditions">\n    <h2>この夜の条件</h2>\n    <div class="facts">\n{facts}\n    </div>\n{cbox}\n  </section>'


def _cards(comm) -> str:
    out = []
    for c in comm["cards"]:
        tags = "".join(f'<span class="tag {_e(t[1])}">{_e(t[0])}</span>' for t in c["tags"])
        items = "".join(f"<li>{_e(x)}</li>" for x in c["list"])
        out.append(f'      <article class="card" id="card-{_e(c["id"])}"><span class="when">{_e(c["when"])}</span><h3>{_e(c["title"])}</h3>'
                   f'<p>{_e(c["body"])}</p><ul>{items}</ul><div class="row">{tags}'
                   f'<button type="button" data-card="{_e(c["id"])}">この構図を見る</button></div></article>')
    lead = comm.get("cards_lead") or "「この構図を見る」を押すと、シミュレーターがその時刻と向きに切り替わります。画角はフルサイズ換算です。"
    return (f'  <section id="compositions">\n    <h2>狙える構図</h2>\n    <p class="lead">{_e(lead)}</p>\n'
            f'    <div class="cards" id="cards">\n' + "\n".join(out) + '\n    </div>\n  </section>')


def _mountains(comm) -> str:
    rows = "\n".join(f'          <tr><td class="n">{_e(d["label"])}</td><td class="n">{_e(d["elevation"])}</td>'
                     f'<td class="terrain">{_inline(d["terrain"])}</td><td>{_e(d["sky"])}</td></tr>' for d in comm["directions"])
    note = comm.get("directions_note") or "稜線の仰角は国土地理院の標高データから計算した値です。山の名前の確度は、各行の記述に従ってください。"
    return ('  <section id="mountains">\n    <h2>周囲の山と方位</h2>\n    <div class="tablewrap">\n      <table>\n'
            '        <thead><tr><th>方位</th><th>稜線の仰角</th><th>地形</th><th>この夜の空</th></tr></thead>\n'
            f'        <tbody>\n{rows}\n        </tbody>\n      </table>\n    </div>\n    <p class="note">{_e(note)}</p>\n  </section>')


def _tips(comm) -> str:
    items = "\n".join(f'      <div class="tip"><h3>{_e(t["title"])}</h3><p>{_e(t["body"])}</p></div>' for t in comm["tips"])
    return f'  <section id="tips">\n    <h2>撮影メモ</h2>\n    <div class="tips">\n{items}\n    </div>\n  </section>'


def _footer(data) -> str:
    spans = "\n".join(f"    <span>{_e(x)}</span>" for x in list(data["attribution"]) + list(data["disclaimer"]))
    return f'  <footer id="footer">\n{spans}\n  </footer>'


def render_html(data: dict, commentary: dict) -> str:
    validate(data, commentary)
    tpl = (_PKG / "template.html").read_text(encoding="utf-8")
    parts = {
        "TITLE": _e(commentary.get("title") or f'{data["spot"]["name"]} 星空ガイド'),
        "CSS": (_PKG / "sky_guide.css").read_text(encoding="utf-8"),
        "HEADER": _header(data, commentary), "CONDITIONS": _conditions(data, commentary),
        "SPOT": _e(data["spot"]["name"]), "CARDS": _cards(commentary), "MOUNTAINS": _mountains(commentary),
        "TIPS": _tips(commentary), "FOOTER": _footer(data),
        "DATA_JSON": embed_json(data), "COMMENTARY_JSON": embed_json(commentary),
        "JS": (_PKG / "sky_guide.js").read_text(encoding="utf-8").replace("</script", "<\\/script"),
    }
    out = tpl
    for k, v in parts.items():
        out = out.replace("{{" + k + "}}", "\x00" + k + "\x00")  # 置換結果の中の {{…}} を再置換しないため一旦マーカー化
    for k, v in parts.items():
        out = out.replace("\x00" + k + "\x00", v)
    check_html(out)
    return out
