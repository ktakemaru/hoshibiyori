"""「今週末の星空撮影」ページ(HTML)を report.html から生成する(通信しない)。

数値・表・カードはコードが report.html から作る(読み写さない)。結論・天気の概況などの文章は、
エージェントが書く解説JSON(hoshibiyori-weekend-commentary/2: verdict と extra_notes)から差し込む。数値→解説→描画の三層で、
星空ガイド(AGENTS.md 第10節)と同じ考え方。解説の数値は、このスクリプトや report_courses.py の出力から取ること。

使い方:
    py -X utf8 scripts/weekend_page.py
    py -X utf8 scripts/weekend_page.py --commentary out/weekend_commentary.json --top 6
    py -X utf8 scripts/weekend_page.py --dates 2026-10-17 2026-10-18 --out out/foo.html

終了コード: 0=出力した / 2=report.html が無い・生成日時が今日(JST)でない(--allow-stale で出力) /
            3=想定の構造でないため解析できなかった / 4=出力先が既にある(--force で上書き) /
            5=解説JSON(または access_check_notes.json)が不正、または verdict が候補データと食い違う。

天気の概況は weekend-commentary には書かない。generate_report.py の天気図解説(weather_map_commentary.json、schema /2)を
唯一の情報源にし、検証は generate_report._valid_commentary を再利用する(無効・期限切れ・レポートの天気図と食い違うときは
本文を出さず「未更新」の一行にする。終了コードは0)。

既存のファイルは上書きしない(別セッションが同名のファイルを上書きして、先に作った版が消えた実例がある)。
HTMLの構造は generate_report.py に合わせてあり、report_courses.py の解析関数を使う。標準ライブラリのみ
(離島の判定に generate_report.CASUAL_EXCLUDED_MUNICIPALITIES を読むだけで、generate_report には手を入れない)。
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import report_courses as rc  # noqa: E402
from hb_paths import resolve_data_root  # noqa: E402

ROOT = rc.ROOT
JST = rc.JST
EXIT_OK, EXIT_STALE, EXIT_PARSE, EXIT_EXISTS, EXIT_COMMENTARY = 0, 2, 3, 4, 5
COMMENTARY_SCHEMA = "hoshibiyori-weekend-commentary/2"
COMMENTARY_LEGACY_SCHEMAS = ("hoshibiyori-weekend-commentary/1",)  # /1 は読めるが weather 欄は無視する
ACCESS_NOTES_SCHEMA = "hoshibiyori-access-notes/1"
TONES = ("good", "neutral", "warn")
MAX_VERDICTS = 4
FAR_KM = 250  # generate_report.CASUAL_RADIUS_KM と同じ(気軽コースの距離条件)
WEEKDAYS = "月火水木金土日"
WEATHER_ROOT = resolve_data_root(ROOT)  # 天気図の画像パス(weather_map_commentary.json の images)の基準。テストで差し替える
# generate_report.render_weather_map_section と同じ文言
WEATHER_SOURCE = "出典: 気象庁ホームページ(https://www.jma.go.jp/bosai/weather_map/)。"


class CommentaryError(Exception):
    """解説JSON・アクセス注記が不正。メッセージに不正な場所を入れる。"""


# --- 日付 -------------------------------------------------------------------------------

def default_dates(generated: date) -> list[date]:
    """レポート生成日(JST)以降の最初の土曜と日曜。生成日が土・日ならその日を含む。

    日曜に生成した場合は、その日曜だけ(来週の土曜は「今週末」ではないため)。
    """
    wd = generated.weekday()  # 土=5, 日=6
    if wd == 6:
        return [generated]
    sat = generated + timedelta(days=(5 - wd) % 7)
    return [sat, sat + timedelta(days=1)]


def day_label(d: date) -> str:
    return f"{d.month}/{d.day}({WEEKDAYS[d.weekday()]})"


def night_name(d: date) -> str:
    return f"{WEEKDAYS[d.weekday()]}曜の夜"


# --- report.html の解析(report_courses.py の解析を使う) ------------------------------------------

def parse_moon_timeline(root: rc.Node, generated: date) -> dict[date, dict]:
    """月齢タイムライン(div.moon-tick)を {夜の日付: {icon, detail}} にする。年はレポート生成日から補う。"""
    ticks = rc._find_all(root, "div", "moon-tick")
    if not ticks:
        raise rc.ParseError("月齢タイムライン: div.moon-tick が1つも無い")
    out: dict[date, dict] = {}
    for t in ticks:
        where = "月齢タイムライン"
        md = rc._match(r"(\d{2})/(\d{2})", rc._norm(rc._one(t, "div", "moon-date", where).text()), f"{where} 日付")
        year = generated.year
        d = date(year, int(md.group(1)), int(md.group(2)))
        if (generated - d).days > 180:  # 年またぎ(12月生成で1月の夜)
            d = date(year + 1, d.month, d.day)
        out[d] = {"icon": rc._norm(rc._one(t, "div", "moon-icon", where).text()),
                  "detail": rc._norm(rc._one(t, "div", "moon-detail", where).text())}
    return out


def parse_footer(text: str) -> list[str]:
    """report.html のフッター(出典・免責)の各段落の内側のHTMLを返す(自分たちの generate_report.py が作った固定文)。"""
    m = re.search(r'<footer class="page-footer">(.*?)</footer>', text, re.S)
    if not m:
        raise rc.ParseError("フッター: <footer class=\"page-footer\"> が無い")
    paras = re.findall(r'<p class="attribution">(.*?)</p>', m.group(1), re.S)
    if not paras:
        raise rc.ParseError("フッター: 出典・免責の段落(p.attribution)が無い")
    return [re.sub(r"\s+", " ", p).strip() for p in paras]


def parse_weather_map(root: rc.Node) -> dict | None:
    """report.html の「地上天気図(気象庁)」ブロックから、画像のsrc(実況・+24h・+48hの順)と取得時刻を返す。
    ブロックが無ければ None(Playwright が無く天気図を省略したレポート)。あるのに形が違えば ParseError。"""
    blocks = [b for b in rc._find_all(root, "div", "wmap-block")
              if any(h.text().strip().startswith("地上天気図") for h in rc._find_all(b, "h3"))]
    if not blocks:
        return None
    if len(blocks) != 1:
        raise rc.ParseError(f"天気図: 地上天気図のブロックが{len(blocks)}個(1個を想定)")
    b = blocks[0]
    srcs = [i.attrs.get("src") for i in rc._find_all(b, "img")]
    if len(srcs) != 3 or not all(srcs):
        raise rc.ParseError(f"天気図: 画像が{len(srcs)}枚(3枚を想定)")
    fetched = None
    for p in rc._find_all(b, "p", "wmap-caveat"):
        m = re.fullmatch(r"天気図の取得時刻:\s*(\d{4}-\d{2}-\d{2} \d{2}:\d{2})", rc._norm(p.text()))
        if m:
            fetched = m.group(1)
    return {"srcs": srcs, "fetched": fetched}


def load_report(text: str, lp_source: str = "legacy") -> dict:
    root = rc.parse_html(text)
    generated = rc.parse_generated_at(root)
    courses = rc.parse_courses(root, lp_source)
    report = {"generated": generated, "courses": courses, "wmap": parse_weather_map(root),
              "moon": parse_moon_timeline(root, generated.date()), "footer": parse_footer(text)}
    if lp_source == "bm":  # legacyの戻り値は従来のまま
        report["lp_source"] = "bm"
    return report


def is_bm(report: dict) -> bool:
    return report.get("lp_source") == "bm"


# --- 解説JSON・アクセス注記 ---------------------------------------------------------------------

def _need(cond: bool, msg: str) -> None:
    if not cond:
        raise CommentaryError(msg)


def _is_str(v) -> bool:
    return isinstance(v, str) and v.strip() != ""


def validate_commentary(data) -> dict:
    """verdict と extra_notes を検査する。weather 欄は廃止(天気図の解説は weather_map_commentary.json が唯一の情報源)で、
    あっても無視して warnings に入れる(エラーにしない)。"""
    _need(isinstance(data, dict), "解説JSONのトップが{...}(オブジェクト)でない")
    schema = data.get("schema")
    _need(schema == COMMENTARY_SCHEMA or schema in COMMENTARY_LEGACY_SCHEMAS,
          f"schema が {COMMENTARY_SCHEMA!r} でない({schema!r})")
    _need("verdict" in data, "verdict(結論ボックスの配列)が無い")
    verdict = data["verdict"]
    _need(isinstance(verdict, list), "verdict が配列でない")
    _need(len(verdict) <= MAX_VERDICTS, f"verdict が{len(verdict)}件(最大{MAX_VERDICTS}件)")
    for i, v in enumerate(verdict):
        w = f"verdict[{i}]"
        _need(isinstance(v, dict), f"{w} がオブジェクトでない")
        _need(_is_str(v.get("title")), f"{w}.title が文字列でない・空")
        _need(_is_str(v.get("body")), f"{w}.body が文字列でない・空")
        _need(v.get("tone") in TONES, f"{w}.tone が {'/'.join(TONES)} のいずれかでない({v.get('tone')!r})")
    extra = data.get("extra_notes", [])
    _need(isinstance(extra, list) and all(_is_str(x) for x in extra), "extra_notes が文字列の配列でない")
    warnings = []
    if "weather" in data:
        warnings.append("解説JSONの weather 欄は廃止されたため無視しました(天気の概況は weather_map_commentary.json "
                        "[schema /2]から出します。AGENTS.md 第12節)。")
    if schema in COMMENTARY_LEGACY_SCHEMAS:
        warnings.append(f"解説JSONの schema {schema} は旧形式です。{COMMENTARY_SCHEMA} に改めてください(verdict と extra_notes のみ)。")
    return {"verdict": verdict, "extra_notes": extra, "warnings": warnings}


# --- verdict の機械検査(施設名・時刻・件数・時間・%・距離・空の明るさが候補データと一致するか) ------------------

_COUNT_RE = re.compile(r"(\d+)\s*(?:件|地点|か所|ヶ所|箇所)")
_HOURS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*時間")
_PCT_RE = re.compile(r"(\d+(?:\.\d+)?)(?:\s*[〜~～]\s*(\d+(?:\.\d+)?))?\s*%")
_KM_RE = re.compile(r"(\d+)\s*km")
_MPSAS_RE = re.compile(r"(\d+\.\d+)\s*mag")
_ALR_RE = re.compile(r"ALR\s*(\d+(?:\.\d+)?)")
_TIME_RE = re.compile(r"(?<!\d)(\d{1,2}):(\d{2})(?!\d)")
MIN_ALIAS_LEN = 3


def load_spot_names(path: Path | None) -> list[str]:
    """地点マスター(stargazing_spots.json)の spots の name。無い・読めないときは空(report の地点名だけで照合する)。"""
    if path is None or not path.is_file():
        return []
    try:
        spots = json.loads(path.read_text(encoding="utf-8")).get("spots", [])
        return [s["name"] for s in spots if isinstance(s, dict) and isinstance(s.get("name"), str)]
    except (OSError, ValueError, AttributeError):
        return []


def _aliases(name: str) -> set[str]:
    """地点名と、「・」「（）」で区切った各部分(「能登半島・白米千枚田」→「白米千枚田」など)。部分は短すぎるものを除く。"""
    parts = {p.strip() for p in re.split(r"[・（）()]", name)}
    return {name} | {p for p in parts if len(p) >= MIN_ALIAS_LEN}  # 地点名そのものは短くても(例: 白州)必ず入れる


def _hm(s: str) -> str:
    h, m = s.split(":")
    return f"{int(h):02d}:{m}"


def _window_hours(window: str) -> float | None:
    m = re.match(r"(\d{2}):(\d{2})〜(\d{2}):(\d{2})", window)
    if not m:
        return None
    a, b = int(m.group(1)) * 60 + int(m.group(2)), int(m.group(3)) * 60 + int(m.group(4))
    return round(((b - a) % (24 * 60)) / 60, 1)


def check_verdict(commentary: dict, report: dict, vocabulary: list[str]) -> None:
    """verdict の title/body を候補データと照合する。食い違いがあれば、全件をまとめて CommentaryError にする。

    - 地点名(地点マスターの name と、その「・」区切りの部分): レポートの候補にある地点だけ書ける。
    - HH:MM: いずれかの候補の見頃の始端・終端・狙い目に一致する。文中の地点が1つに決まれば、その地点の時刻に限る。
    - N件/N地点: コースの件数・夜ごとの件数・全体の件数のどれか。
    - N時間: 月齢タイムラインの無月時間か、見頃の長さ。N%: 候補の雲量かレポートの気象メモ中の%。
    - Nkm: 候補の東京からの距離。N.NN mag: 候補の空の明るさ。
    検査しないもの: 日付、地点名を含まない文での「どの地点の」時刻かの対応、extra_notes。
    """
    cands = [c for course in report["courses"] for c in course["candidates"]]
    report_names = {c["name"] for c in cands}
    owner: dict[str, set[str]] = {}
    for n in set(vocabulary) | report_names:
        for a in _aliases(n):
            owner.setdefault(a, set()).add(n)
    times: dict[str, set[str]] = {n: set() for n in report_names}
    for c in cands:
        start, end = c["window"].split("〜")
        times[c["name"]] |= {_hm(start), _hm(end[:5]), _hm(c["best_time"])}
    all_times = set().union(*times.values()) if times else set()
    counts = {len(course["candidates"]) for course in report["courses"]}
    nights = {c["date"] for c in cands}
    for course in report["courses"]:
        for d in nights:
            counts.add(sum(1 for c in course["candidates"] if c["date"] == d))
    counts |= {sum(1 for c in cands if c["date"] == d) for d in nights} | {len(cands)}
    hours = {float(re.match(r"(\d+(?:\.\d+)?)", m["detail"]).group(1)) for m in report["moon"].values()
             if re.match(r"\d", m["detail"])}
    hours |= {h for h in (_window_hours(c["window"]) for c in cands) if h is not None}
    pcts = {float(c["obstruction_pct"]) for c in cands}
    for course in report["courses"]:
        for x in _PCT_RE.finditer(course.get("weather_note") or ""):
            pcts |= {float(g) for g in x.groups() if g}
    pcts |= {float(x) for course in report["courses"] for x in re.findall(r"(\d+)\s*%以下", course.get("condition_note") or "")}
    kms = {c["distance_km"] for c in cands} | {250}
    bm = is_bm(report)
    mpsas = set() if bm else {round(c["effective_mpsas"], 2) for c in cands}  # bmには等級が無い
    alrs = {round(c["alr"], 2) for c in cands} if bm else set()

    errors = []
    for i, v in enumerate(commentary["verdict"]):
        for field in ("title", "body"):
            where = f"verdict[{i}].{field}"
            text = v[field]
            for sentence in re.split(r"(?<=[。!?])", text):
                found = set()  # この文で言及された地点(レポートの地点名に解決できたもの)
                for alias in sorted(owner, key=len, reverse=True):
                    if alias in sentence:
                        resolved = owner[alias]
                        if not resolved & report_names:
                            errors.append(f"{where}: 地点「{alias}」はレポートの候補にありません")
                        else:
                            found |= resolved & report_names
                for m in _TIME_RE.finditer(sentence):
                    t_ = _hm(f"{m.group(1)}:{m.group(2)}")
                    if t_ not in all_times:
                        errors.append(f"{where}: 時刻 {t_} はどの候補の見頃・狙い目にもありません")
                    elif len(found) == 1 and t_ not in times[next(iter(found))]:
                        errors.append(f"{where}: 時刻 {t_} は「{next(iter(found))}」の見頃・狙い目ではありません"
                                      f"({'/'.join(sorted(times[next(iter(found))]))})")
            for m in _COUNT_RE.finditer(text):
                if int(m.group(1)) not in counts:
                    errors.append(f"{where}: 件数「{m.group(0)}」はレポートの件数({'/'.join(map(str, sorted(counts)))})のどれとも違います")
            for m in _HOURS_RE.finditer(text):
                if not any(abs(float(m.group(1)) - h) < 0.05 for h in hours):
                    errors.append(f"{where}: 「{m.group(0)}」は無月時間・見頃の長さ({'/'.join(map(str, sorted(hours)))})のどれとも違います")
            for m in _PCT_RE.finditer(text):
                for g in (x for x in m.groups() if x):
                    if float(g) not in pcts:
                        errors.append(f"{where}: {g}% は候補の雲量・気象メモの%と一致しません")
            for m in _KM_RE.finditer(text):
                if int(m.group(1)) not in kms:
                    errors.append(f"{where}: 「{m.group(0)}」はどの候補の東京からの距離とも違います")
            for m in _MPSAS_RE.finditer(text):
                if bm:
                    errors.append(f"{where}: 「{m.group(0)}」は書けません(bmのレポートには空の明るさの等級が無い。相対指数ALRで書く)")
                elif round(float(m.group(1)), 2) not in mpsas:
                    errors.append(f"{where}: 空の明るさ {m.group(1)} はどの候補の値とも違います")
            for m in _ALR_RE.finditer(text):
                if round(float(m.group(1)), 2) not in alrs:
                    errors.append(f"{where}: ALR {m.group(1)} はどの候補の値とも違います"
                                  + ("" if bm else "(legacyのレポートにはALRが無い)"))
    _need(not errors, "verdict が候補データと食い違います:\n  - " + "\n  - ".join(dict.fromkeys(errors)))


def load_commentary(path: Path | None) -> dict | None:
    if path is None:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise CommentaryError(f"{path} がありません") from None
    except (OSError, ValueError) as e:
        raise CommentaryError(f"{path} を読めません({e})") from None
    return validate_commentary(data)


def load_access_notes(path: Path) -> dict[str, str]:
    """access_check_notes.json の notes を返す。ファイルが無ければ注記なし。壊れていれば CommentaryError。"""
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise CommentaryError(f"{path} を読めません({e})") from None
    _need(isinstance(data, dict) and data.get("schema") == ACCESS_NOTES_SCHEMA,
          f"{path.name}: schema が {ACCESS_NOTES_SCHEMA!r} でない")
    notes = data.get("notes")
    _need(isinstance(notes, dict) and all(_is_str(k) and _is_str(v) for k, v in notes.items()),
          f"{path.name}: notes が {{地点名: 注記}} の形でない")
    return notes


# --- 描画 -------------------------------------------------------------------------------------

def esc(s) -> str:
    return html.escape(str(s), quote=True)


def _safe_url(u: str) -> str:
    return u if re.match(r"https?://", u) else "#"


def _generate_report():
    """generate_report を読む(約0.7秒)。天気図の解説の検証と離島の定義を、複製せずここから使う。"""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    import generate_report as gr
    return gr


def _island_municipalities() -> set[str]:
    return set(_generate_report().CASUAL_EXCLUDED_MUNICIPALITIES)  # 離島の定義は気軽コースの除外リストを正とする


def card_tags(c: dict, course_id: str, casual_names: set[str], islands: set[str], notes: dict[str, str]) -> list[tuple[str, str]]:
    tags = [("", f"スコア {c['score']}"), ("", f"東京から直線{c['distance_km']}km")]
    if course_id == "hardcore" and c["name"] not in casual_names:
        if c["distance_km"] > FAR_KM:
            tags.append(("far", f"遠征圏(東京から{FAR_KM}km超)"))
        if c["municipality"] in islands:
            tags.append(("warn", "離島(フェリー)"))
    if c["name"] in notes:
        tags.append(("warn", "アクセス要確認"))
    return tags


def _lp_row(c: dict) -> str:
    """カードの光害の欄。legacyは空の明るさ(mag/arcsec²)、bm(cにalrがある)は相対指数ALRと順位。"""
    if "alr" in c:
        rank = f"暗い方から{c['alr_rank_pct']}%・" if c["alr_rank_pct"] is not None else ""
        return (f"<div><dt>光害(相対指数)</dt><dd>ALR {c['alr']:.2f}"
                f"<small>({rank}小さいほど暗い・絶対値ではない)</small></dd></div>")
    return f"<div><dt>空の明るさ</dt><dd>{c['effective_mpsas']:.2f} mag/arcsec²<small>(大きいほど暗い)</small></dd></div>"


def render_card(c: dict, rank: int, course_id: str, casual_names, islands, notes) -> str:
    tags ="".join(f'<span class="tag {cls}">{esc(t)}</span>' for cls, t in card_tags(c, course_id, casual_names, islands, notes))
    check = f'<p class="check">{esc(notes[c["name"]])}</p>' if c["name"] in notes else ""
    return f"""
    <article class="card">
      <div class="rank">{rank}</div>
      <div class="body">
        <h4>{esc(c['name'])}<span class="muni">（{esc(c['municipality'])}）</span></h4>
        <div class="tags">{tags}</div>
        <dl>
          <div><dt>見頃</dt><dd>{esc(c['window'])}(狙い目 {esc(c['best_time'])})</dd></div>
          <div><dt>雲量(全天平均)</dt><dd>{c['obstruction_pct']}%</dd></div>
          {_lp_row(c)}
        </dl>
        {check}
        <a class="map" href="{esc(_safe_url(c['maps_url']))}" target="_blank" rel="noopener">📍 Googleマップ</a>
      </div>
    </article>"""


def render_course_block(course: dict, night: date, top: int, casual_names, islands, notes) -> str:
    icon = "🚗" if course["id"] == "casual" else "🏔"
    label = "気軽コース" if course["id"] == "casual" else "硬派コース"
    cards = [c for c in course["candidates"] if c["date"] == night.isoformat()][:top]
    head = f"<h3>{icon} {esc(label)}</h3><p class=\"note\">{esc(course['condition_note'])}</p>"
    if not cards:
        n = len(course["candidates"])
        extra = f" {esc(course['empty_note'])}" if course["empty_note"] and not course["candidates"] else ""
        return head + f'<p class="empty">この夜の上位{n}件に入った地点はありません。{extra}</p>'
    body = "".join(render_card(c, i, course["id"], casual_names, islands, notes) for i, c in enumerate(cards, 1))
    memo = ""
    if course["id"] == "casual" and course["weather_note"]:
        memo = f'<p class="note">気象メモ(レポート全期間): {esc(course["weather_note"])}</p>'
    return head + f'<div class="grid">{body}</div>' + memo


def render_night(night: date, report: dict, top: int, casual_names, islands, notes) -> str:
    moon = report["moon"].get(night)
    if moon:
        moon_html = f'<span class="moon">{esc(moon["icon"])} 無月 {esc(moon["detail"])}</span>'
        if moon["detail"].endswith("なし"):
            moon_html = f'<span class="moon">{esc(moon["icon"])} {esc(moon["detail"])}</span>'
    else:
        moon_html = '<span class="moon">月の情報はレポートにありません</span>'
    blocks = "".join(render_course_block(c, night, top, casual_names, islands, notes) for c in report["courses"])
    return f'<h2>{esc(night_name(night))}({night.month}/{night.day}) {moon_html}</h2>{blocks}'


def _lp_cell(k: dict) -> str:
    return f"{k['alr']:.2f}" if "alr" in k else f"{k['effective_mpsas']:.2f}"


def render_table(report: dict) -> str:
    parts = []
    for c in report["courses"]:
        label = "気軽コース" if c["id"] == "casual" else "硬派コース"
        if not c["candidates"]:
            parts.append(f"<h3>{esc(label)}</h3><p class=\"empty\">{esc(c['empty_note'] or '候補なし')}</p>")
            continue
        rows = "".join(
            f"<tr><td>{k['rank']}</td>"
            f"<td><a href=\"{esc(_safe_url(k['maps_url']))}\" target=\"_blank\" rel=\"noopener\">{esc(k['name'])}</a>"
            f"<small>{esc(k['municipality'])}</small></td>"
            f"<td>{esc(_short_date(k['date']))}</td><td>{esc(k['window'])}</td><td>{k['obstruction_pct']}%</td>"
            f"<td>{_lp_cell(k)}</td><td>{k['distance_km']}km</td><td>{k['score']}</td></tr>"
            for k in c["candidates"])
        lp_head = ("光害(相対指数)<br>ALR" if is_bm(report) else "空の明るさ<br>mag/arcsec²")
        parts.append(f"""<h3>{esc(label)}(レポート内{len(c['candidates'])}件)</h3>
<div class="tablewrap"><table>
<thead><tr><th>順位</th><th>地点</th><th>日付</th><th>見頃</th><th>雲量</th><th>{lp_head}</th><th>東京から</th><th>スコア</th></tr></thead>
<tbody>{rows}</tbody></table></div>""")
    return ('<h2>全候補の一覧</h2><details open><summary>レポートに載った全件(夜を問わず・レポートの順位順)</summary>'
            + "".join(parts) + "</details>")


def _short_date(iso: str) -> str:
    d = date.fromisoformat(iso)
    return day_label(d)


def render_verdict(commentary: dict | None) -> str:
    if commentary is None:
        return '<p class="note">解説(結論)は未作成です。</p>'
    boxes = "".join(
        f'<div class="box {v["tone"] if v["tone"] != "neutral" else ""}"><h3>{esc(v["title"])}</h3><p>{esc(v["body"])}</p></div>'
        for v in commentary["verdict"])
    return f'<div class="verdict">{boxes}</div>' if boxes else ""


def weather_status(report: dict, now: datetime, path: Path | None = None, root: Path | None = None) -> dict:
    """天気図の解説の状態を返す。有効(generate_report._valid_commentary が通り、かつレポートが示す天気図と一致)なら
    valid=True と本文・based_on・画像パス。それ以外は valid=False と、理由(reason)・最終更新(based_on があれば)。"""
    gr = _generate_report()
    path = path or gr.WEATHER_MAP_COMMENTARY_PATH
    root = root or WEATHER_ROOT
    valid = gr._valid_commentary(now, path, root)
    if valid is None:
        _, based_on, _ = gr.load_weather_map_commentary(path, root)
        return {"valid": False, "based_on": based_on,
                "reason": "解説が無効(ファイル無し・schema /2 でない・期限切れ・画像の不備のいずれか)"}
    text, based_on, images = valid
    wmap = report.get("wmap")
    if wmap is None:
        return {"valid": False, "based_on": based_on, "reason": "レポートに地上天気図がない(解説との対応を確認できない)"}
    rels = [Path(p).resolve().relative_to(Path(root).resolve()).as_posix() for p in images]
    stamp = based_on.astimezone(JST).strftime("%Y-%m-%d %H:%M")
    if wmap["fetched"] != stamp or wmap["srcs"] != rels:
        return {"valid": False, "based_on": based_on,
                "reason": f"レポートの天気図(取得 {wmap['fetched']})と解説(based_on {stamp})の時刻または画像が食い違う"}
    return {"valid": True, "based_on": based_on, "text": text, "images": images, "reason": ""}


_WEATHER_STEP_LABELS = {"now": "実況", "plus24h": "24時間後の予想", "plus48h": "48時間後の予想"}


def render_weather(status: dict) -> str:
    """generate_report.render_weather_map_section と同じ形(3枚の図・取得時刻・解説・出典)。画像は自己完結のため埋め込む。"""
    if not status["valid"]:
        based_on = status.get("based_on")
        suffix = f"(最終更新 {based_on.astimezone(JST).strftime('%Y-%m-%d %H時')})" if based_on else ""
        return f'<h2>天気の概況</h2><p class="note">天気図の解説は未更新のため表示していません{esc(suffix)}</p>'
    import base64
    cards = []
    for step, p in zip(_WEATHER_STEP_LABELS, status["images"]):
        label = _WEATHER_STEP_LABELS[step]
        data = base64.b64encode(Path(p).read_bytes()).decode("ascii")
        cards.append(f'<figure class="wmap-card"><img src="data:image/png;base64,{data}" '
                     f'alt="JMA地上天気図({esc(label)})" loading="lazy"><figcaption>{esc(label)}</figcaption></figure>')
    stamp = status["based_on"].astimezone(JST).strftime("%Y-%m-%d %H:%M")
    return ('<h2>天気の概況</h2><div class="box"><h3>地上天気図(気象庁)</h3>'
            f'<div class="wmap-row">{"".join(cards)}</div>'
            f'<p class="note">天気図の取得時刻: {esc(stamp)}</p>'
            f'<p class="wmap-text">{esc(status["text"])}</p>'
            f'<p class="note">{esc(stamp)} 取得の天気図をもとに記述した解説です。</p>'
            f'<p class="note">{esc(WEATHER_SOURCE)}</p></div>')


def render_extra(commentary: dict | None) -> str:
    if commentary is None or not commentary["extra_notes"]:
        return ""
    return '<h2>補足</h2><ul>' + "".join(f"<li>{esc(x)}</li>" for x in commentary["extra_notes"]) + "</ul>"


def render_checklist(report: dict, has_notes: bool) -> str:
    gen = report["generated"].strftime("%Y-%m-%d %H:%M")
    access = ("カードに「アクセス要確認」と付いた地点は、夜間の通行・運行・入園の可否がデータに反映されていない可能性があります。"
              "注記は出発前に確認を促すもので、確認済みの情報ではありません。" if has_notes else
              "夜間の通行・運行・入園の可否は、データに反映されていない可能性があります。出発前に道路情報・運行情報を確認してください。")
    rows = [
        ("予報の更新", f"このページは{esc(gen)} JST生成のレポートに基づく予報です。出発前に、雲量・天気図・衛星画像を更新してください。"),
        ("アクセス", esc(access)),
        ("雲量の見方", "全天の平均です。数%でも、見たい方角に雲がかかる夜があります。"),
        ("寒さ・安全", "標高の高い地点は10月でも夜は冷え込みます。人気のない道・林道は、単独行動を避け、帰りの時刻と連絡手段を決めておいてください。"),
    ]
    trs = "".join(f"<tr><th scope=\"row\">{a}</th><td>{b}</td></tr>" for a, b in rows)
    return f'<h2>出かける前に確認すること</h2><div class="tablewrap"><table class="plain">{trs}</table></div>'


CSS = """
:root { --bg:#f6f7fb; --fg:#1b2030; --muted:#5b6478; --card:#ffffff; --line:#dde1ec; --accent:#2f5bd8; --warn:#b4540a; --warnbg:#fff3e6; --good:#1c7a4a; --goodbg:#e7f6ee; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --bg:#0f1320; --fg:#e6e9f2; --muted:#9aa3b8; --card:#171c2e; --line:#2a3150; --accent:#8fb0ff; --warn:#ffb36b; --warnbg:#2b2013; --good:#7fd8a6; --goodbg:#132a1f; } }
:root[data-theme="dark"] { --bg:#0f1320; --fg:#e6e9f2; --muted:#9aa3b8; --card:#171c2e; --line:#2a3150; --accent:#8fb0ff; --warn:#ffb36b; --warnbg:#2b2013; --good:#7fd8a6; --goodbg:#132a1f; }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--fg); font:16px/1.7 system-ui,"Hiragino Sans","Yu Gothic UI",Meiryo,sans-serif; }
main { max-width:980px; margin:0 auto; padding:24px 16px 64px; }
h1 { font-size:1.7rem; margin:.2em 0; }
h2 { font-size:1.25rem; margin:2em 0 .6em; padding-bottom:.3em; border-bottom:2px solid var(--line); }
h3 { font-size:1.05rem; margin:1.4em 0 .5em; }
p, li { margin:.4em 0; }
.lead { color:var(--muted); }
.stale { background:var(--warnbg); border:1px solid var(--warn); color:var(--warn); border-radius:10px; padding:10px 14px; font-weight:600; }
.moon { font-size:.9rem; font-weight:400; color:var(--muted); margin-left:.6em; }
.verdict { display:grid; gap:12px; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); margin:18px 0; }
.box { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:14px 16px; }
.box.good { background:var(--goodbg); border-color:var(--good); }
.box.warn { background:var(--warnbg); border-color:var(--warn); }
.box h3 { margin:.1em 0 .3em; }
.grid { display:grid; gap:12px; grid-template-columns:repeat(auto-fit,minmax(300px,1fr)); }
.card { display:flex; gap:12px; background:var(--card); border:1px solid var(--line); border-radius:12px; padding:12px 14px; }
.rank { flex:none; width:2em; height:2em; border-radius:50%; background:var(--accent); color:#fff; display:grid; place-items:center; font-weight:700; }
.body { min-width:0; flex:1; }
h4 { margin:.1em 0 .3em; font-size:1.05rem; }
.muni { font-weight:400; color:var(--muted); font-size:.9em; }
.tags { display:flex; flex-wrap:wrap; gap:6px; margin-bottom:6px; }
.tag { font-size:.78rem; padding:1px 8px; border-radius:99px; border:1px solid var(--line); color:var(--muted); }
.tag.far { color:var(--accent); border-color:var(--accent); }
.tag.warn { color:var(--warn); border-color:var(--warn); }
dl { margin:.2em 0; } dl div { display:flex; gap:8px; } dt { flex:none; width:8.5em; color:var(--muted); font-size:.88rem; } dd { margin:0; } dd small { color:var(--muted); margin-left:4px; }
.check { font-size:.86rem; color:var(--warn); margin:.4em 0; }
.map { font-size:.9rem; color:var(--accent); text-decoration:none; } .map:hover { text-decoration:underline; }
.tablewrap { overflow-x:auto; }
table { border-collapse:collapse; width:100%; min-width:640px; background:var(--card); border:1px solid var(--line); }
table.plain { min-width:0; }
th, td { text-align:left; padding:8px 12px; border-bottom:1px solid var(--line); vertical-align:top; } th { background:var(--bg); font-size:.9rem; }
td small { display:block; color:var(--muted); }
summary { cursor:pointer; color:var(--muted); margin:.4em 0; }
.note { font-size:.88rem; color:var(--muted); }
.wmap-row { display:grid; gap:10px; grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); }
.wmap-card { margin:0; } .wmap-card img { width:100%; height:auto; border:1px solid var(--line); border-radius:8px; background:#fff; }
.wmap-card figcaption { font-size:.85rem; color:var(--muted); text-align:center; }
.empty { color:var(--muted); background:var(--card); border:1px dashed var(--line); border-radius:10px; padding:10px 14px; }
footer { margin-top:3em; font-size:.82rem; color:var(--muted); border-top:1px solid var(--line); padding-top:1em; }
a { color:var(--accent); }
"""


def render_page(report: dict, nights: list[date], top: int, commentary: dict | None, notes: dict[str, str],
                stale_banner: str = "", weather: dict | None = None) -> str:
    casual_names = {c["name"] for c in next(x for x in report["courses"] if x["id"] == "casual")["candidates"]}
    islands = _island_municipalities()
    gen = report["generated"].strftime("%Y-%m-%d %H:%M")
    nights_label = "・".join(day_label(n) for n in nights)
    title = f"今週末の星空撮影 {nights[0].month}/{nights[0].day}" + (f"-{nights[-1].day}" if len(nights) > 1 else "")
    sections = "".join(render_night(n, report, top, casual_names, islands, notes) for n in nights)
    has_notes = any(c["name"] in notes for crs in report["courses"] for c in crs["candidates"])
    footer = "".join(f"<p>{p}</p>" for p in report["footer"])
    lp_note = (f'<p class="note">{esc(rc.BM_NOTE)}空の明るさ(mag/arcsec²)は表示していません。</p>'
               if is_bm(report) else "")
    return f"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<style>{CSS}</style>
</head>
<body>
<main>
<h1>今週末の星空撮影 — {esc(nights_label)}の夜</h1>
<p class="lead">hoshibiyoriの探索レポート(生成 {esc(gen)} JST)から作成。<strong>雲量は全天の平均で、方角ごとの雲は分かりません。</strong></p>
{stale_banner}{lp_note}
{render_verdict(commentary)}
{render_weather(weather) if weather is not None else ""}
{sections}
{render_table(report)}
{render_extra(commentary)}
{render_checklist(report, has_notes)}
<footer>{footer}</footer>
</main>
</body>
</html>
"""


# --- CLI --------------------------------------------------------------------------------------

def _iso_date(s: str) -> date:
    try:
        return date.fromisoformat(s)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{s!r} は YYYY-MM-DD の形式で指定してください") from None


def main(argv: list[str] | None = None, now: datetime | None = None) -> int:
    ap = argparse.ArgumentParser(description="今週末の星空撮影ページ(HTML)を report.html から生成する(通信しない)")
    ap.add_argument("--lp-source", choices=rc.LP_SOURCES, default="legacy",
                    help="読むレポートの光害の入力。legacy=report.html(既定)、bm=report_bm.html(generate_report.py --lp-source bm)")
    ap.add_argument("--report", type=Path, default=None, help="既定: legacyはreport.html、bmはreport_bm.html")
    ap.add_argument("--commentary", type=Path, help="解説JSON(hoshibiyori-weekend-commentary/2: verdict と extra_notes)。無ければ結論は出さない")
    ap.add_argument("--weather-commentary", type=Path, help="天気図の解説(既定: リポジトリ直下の weather_map_commentary.json、schema /2)")
    ap.add_argument("--spots", type=Path, default=ROOT / "stargazing_spots.json", help="verdict の地点名の照合に使う地点マスター")
    ap.add_argument("--access-notes", type=Path, default=ROOT / "access_check_notes.json")
    ap.add_argument("--dates", nargs="+", type=_iso_date, metavar="YYYY-MM-DD", help="夜の開始日。既定は生成日以降の最初の土曜と日曜")
    ap.add_argument("--top", type=int, default=6, help="夜ごと・コースごとのカード件数(既定6)。一覧表は常に全件")
    ap.add_argument("--out", type=Path, help="出力先。既定 out/weekend_stargazing_<最初の夜のYYYYMMDD>.html")
    ap.add_argument("--force", action="store_true", help="出力先が既にあっても上書きする(ユーザーの許可があるときだけ)")
    ap.add_argument("--allow-stale", action="store_true", help="生成日時が今日でなくても、古い旨を明記して出力する")
    args = ap.parse_args(argv)
    if args.top < 1:
        ap.error("--top は1以上")
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    today = (now or datetime.now(JST)).astimezone(JST).date()
    if args.report is None:
        args.report = resolve_data_root(ROOT) / ("report_bm.html" if args.lp_source == "bm" else "report.html")
    if not args.report.is_file():
        gen_cmd = "py -X utf8 generate_report.py" + (" --lp-source bm" if args.lp_source == "bm" else "")
        print(f"[中止] {args.report} がありません。{gen_cmd} で生成してください"
              "(10〜30分・Open-Meteo約220回。実行前にユーザーの承認を得ること)。", file=sys.stderr)
        return EXIT_STALE
    try:
        text = args.report.read_text(encoding="utf-8")
        report = load_report(text, args.lp_source)
    except rc.ParseError as e:
        print(f"[解析失敗] report.html が想定の構造ではありません: {e}\n"
              "(generate_report.py の構造が変わった可能性があります。推測では埋めません。)", file=sys.stderr)
        return EXIT_PARSE
    gen_date = report["generated"].date()
    stale = gen_date != today
    if stale and not args.allow_stale:
        print(f"[中止] report.html の生成日時 {report['generated']:%Y-%m-%d %H:%M} JST は今日({today})ではないため、"
              "出力しません。再生成する(ユーザーの承認が必要)か、--allow-stale で古い旨つきの出力にしてください。", file=sys.stderr)
        return EXIT_STALE

    try:
        commentary = load_commentary(args.commentary)
        notes = load_access_notes(args.access_notes)
        if commentary is not None:
            check_verdict(commentary, report, load_spot_names(args.spots))
    except CommentaryError as e:
        print(f"[解説JSON不正] {e}", file=sys.stderr)
        return EXIT_COMMENTARY
    for w in (commentary or {}).get("warnings", []):
        print(f"[警告] {w}", file=sys.stderr)
    weather = weather_status(report, (now or datetime.now(JST)).astimezone(JST), args.weather_commentary)
    if not weather["valid"]:
        print(f"[天気図の解説] 未更新として扱います: {weather['reason']}", file=sys.stderr)

    nights = sorted(set(args.dates)) if args.dates else default_dates(gen_date)
    suffix = "_bm" if args.lp_source == "bm" else ""  # bmのページはlegacyのページと別名にする
    out = args.out or resolve_data_root(ROOT) / "out" / f"weekend_stargazing_{nights[0]:%Y%m%d}{suffix}.html"
    if out.exists() and not args.force:
        print(f"[中止] {out} は既に存在します。別名にするか --force を付けてください(何も書いていません)。", file=sys.stderr)
        return EXIT_EXISTS

    banner = ""
    if stale:
        banner = (f'<p class="stale">【古いレポートです】生成日時 {esc(report["generated"].strftime("%Y-%m-%d %H:%M"))} JST は今日'
                  f'({esc(today)})ではありません。近日分の予報は更新されている可能性があり、判断の根拠にしないでください。</p>')
    page = render_page(report, nights, args.top, commentary, notes, banner, weather)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(f"保存しました: {out}")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
