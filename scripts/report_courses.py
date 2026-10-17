"""report.html から「気軽コース」「硬派コース」の上位候補を取り出して表示する(通信しない)。

質問「星空撮影に適した日と場所は?」に、両コースで答えるための材料(AGENTS.md 第11節)。
report.html を目視で読み写さず、このスクリプトの出力を使う。

使い方:
    py -X utf8 scripts/report_courses.py                    # 既定: リポジトリ直下の report.html、上位3件
    py -X utf8 scripts/report_courses.py --top 5 --json-out out/courses.json
    py -X utf8 scripts/report_courses.py --out out/courses.txt   # python側でUTF-8のファイルへ書く(文字化け回避)

終了コード: 0=出力した / 2=report.html が無い・生成日時が今日(JST)でない(--allow-stale で出力) /
            3=想定の構造でないため解析できなかった(推測で埋めない)。

HTMLの構造は generate_report.py の render_candidate_group / render_tier2 に合わせてある
(div.cand-group > h3.group-title / p.group-note / p.weather-note / p.empty-note / div.cand-card)。
generate_report.py 側の構造が変わると、このスクリプトは推測せず終了コード3で止まる
(tests/test_report_courses.py が実際の render 関数から作ったHTMLで検査する)。標準ライブラリのみ。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JST = timezone(timedelta(hours=9))
SCHEMA = "hoshibiyori-course-report/1"
COURSES = (("casual", "気軽コース"), ("hardcore", "硬派コース"))
EXIT_OK, EXIT_STALE, EXIT_PARSE = 0, 2, 3

_VOID = {"meta", "link", "img", "br", "hr", "input", "source", "area", "base", "col", "embed", "wbr"}


class ParseError(Exception):
    """想定の構造でない。メッセージに失敗した場所を入れる。"""


# --- 最小限のDOM(html.parserで構築) ---------------------------------------------------

@dataclass
class Node:
    tag: str
    classes: frozenset = frozenset()
    attrs: dict = field(default_factory=dict)
    children: list = field(default_factory=list)  # Node または str

    def text(self) -> str:
        return "".join(c if isinstance(c, str) else c.text() for c in self.children)

    def own_text(self) -> str:
        return "".join(c for c in self.children if isinstance(c, str))

    def walk(self):
        for c in self.children:
            if isinstance(c, Node):
                yield c
                yield from c.walk()


class _TreeBuilder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#root")
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        node = Node(tag, frozenset((a.get("class") or "").split()), a)
        self.stack[-1].children.append(node)
        if tag not in _VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        a = dict(attrs)
        self.stack[-1].children.append(Node(tag, frozenset((a.get("class") or "").split()), a))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def parse_html(text: str) -> Node:
    b = _TreeBuilder()
    b.feed(text)
    b.close()
    return b.root


def _find_all(node: Node, tag: str, cls: str | None = None) -> list[Node]:
    return [n for n in node.walk() if n.tag == tag and (cls is None or cls in n.classes)]


def _one(node: Node, tag: str, cls: str, where: str) -> Node:
    found = _find_all(node, tag, cls)
    if len(found) != 1:
        raise ParseError(f"{where}: <{tag} class=\"{cls}\"> が{len(found)}個(1個を想定)")
    return found[0]


def _opt(node: Node, tag: str, cls: str, where: str) -> Node | None:
    found = _find_all(node, tag, cls)
    if len(found) > 1:
        raise ParseError(f"{where}: <{tag} class=\"{cls}\"> が{len(found)}個(0〜1個を想定)")
    return found[0] if found else None


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


# --- 抽出 -------------------------------------------------------------------------------

def parse_generated_at(root: Node) -> datetime:
    line = _one(root, "p", "target-line", "ヘッダー").text()
    m = re.search(r"生成日時:\s*(\d{4}-\d{2}-\d{2} \d{2}:\d{2}) JST", line)
    if not m:
        raise ParseError(f"ヘッダー: 「生成日時: YYYY-MM-DD HH:MM JST」が見つからない({_norm(line)!r})")
    return datetime.strptime(m.group(1), "%Y-%m-%d %H:%M").replace(tzinfo=JST)


def _match(pattern: str, s: str, where: str) -> re.Match:
    m = re.fullmatch(pattern, s)
    if not m:
        raise ParseError(f"{where}: 想定の形式でない({s!r})")
    return m


def parse_card(card: Node, where: str) -> dict:
    rank = int(_match(r"\d+", _norm(_one(card, "div", "cand-rank", where).text()), f"{where} 順位").group())
    body = _one(card, "div", "cand-body", where)
    h3 = _find_all(body, "h3")
    if len(h3) != 1:
        raise ParseError(f"{where}: 地点名の<h3>が{len(h3)}個(1個を想定)")
    name = _norm(h3[0].own_text())
    muni_raw = _norm(_one(h3[0], "span", "cand-muni", where).text())
    muni = _match(r"[（(](.*)[）)]", muni_raw, f"{where} 市区町村").group(1)
    if not name:
        raise ParseError(f"{where}: 地点名が空")

    badges = {c: n for n in _find_all(body, "span", "badge") for c in n.classes if c != "badge"}
    for key in ("score", "dist", "origin"):
        if key not in badges:
            raise ParseError(f"{where}: バッジ「{key}」が無い")
    score = int(_match(r"スコア (-?\d+)", _norm(badges["score"].text()), f"{where} スコア").group(1))
    dist = int(_match(r"東京から直線(\d+)km", _norm(badges["dist"].text()), f"{where} 距離").group(1))

    stats = {}
    for div in _find_all(_one(body, "dl", "cand-stats", where), "div"):
        dts, dds = _find_all(div, "dt"), _find_all(div, "dd")
        if len(dts) != 1 or len(dds) != 1:
            raise ParseError(f"{where}: cand-stats の項目が dt/dd 1組ずつでない")
        stats[_norm(dts[0].text())] = _norm(dds[0].text())
    for key in ("見頃", "日付", "視界遮蔽雲量", "実効的な空の明るさ"):
        if key not in stats:
            raise ParseError(f"{where}: cand-stats に「{key}」が無い")

    mw = _match(r"(\d{2}:\d{2}〜\d{2}:\d{2}(?:\(翌\))?)\(狙い目 (\d{2}:\d{2})\)", stats["見頃"], f"{where} 見頃")
    date = _match(r"\d{4}-\d{2}-\d{2}", stats["日付"], f"{where} 日付").group()
    obstruction = int(_match(r"平均(\d+)%", stats["視界遮蔽雲量"], f"{where} 視界遮蔽雲量").group(1))
    mpsas = float(_match(r"(\d+(?:\.\d+)?) mag/arcsec²", stats["実効的な空の明るさ"], f"{where} 空の明るさ").group(1))
    maps = _one(body, "a", "btn-maps", where).attrs.get("href")
    if not maps:
        raise ParseError(f"{where}: Googleマップのリンクが無い")
    return {
        "rank": rank, "name": name, "municipality": muni, "score": score, "distance_km": dist,
        "origin": _norm(badges["origin"].text()), "date": date, "window": mw.group(1), "best_time": mw.group(2),
        "obstruction_pct": obstruction, "effective_mpsas": mpsas, "maps_url": maps,
    }


def parse_courses(root: Node) -> list[dict]:
    """気軽・硬派の2コースを(この順で)返す。どちらかが無い・構造が違えば ParseError。"""
    groups = _find_all(root, "div", "cand-group")
    out = []
    for cid, label in COURSES:
        found = [g for g in groups if _norm(_one(g, "h3", "group-title", "コース見出し").text()).startswith(label)]
        if len(found) != 1:
            raise ParseError(f"「{label}」のグループが{len(found)}個(1個を想定)")
        g = found[0]
        where = label
        title = _norm(_one(g, "h3", "group-title", where).text())
        note = _norm(_one(g, "p", "group-note", where).text())
        weather = _opt(g, "p", "weather-note", where)
        empty = _opt(g, "p", "empty-note", where)
        cards = _find_all(g, "div", "cand-card")
        if not cards and empty is None:
            raise ParseError(f"{where}: 候補も「候補なし」の理由(empty-note)も無い")
        candidates = [parse_card(c, f"{where} {i}件目") for i, c in enumerate(cards, 1)]
        out.append({
            "id": cid, "title": title, "condition_note": note,
            # 先頭の装飾絵文字(🌤)だけ除き、本文はそのまま
            "weather_note": re.sub(r"^🌤\s*", "", _norm(weather.text())) if weather is not None else None,
            "empty_note": _norm(empty.text()) if empty is not None else None,
            "candidates": candidates,
        })
    return out


# --- 出力 -------------------------------------------------------------------------------

def build_result(html_text: str, report_path: Path, top: int, stale: bool) -> dict:
    root = parse_html(html_text)
    generated = parse_generated_at(root)
    courses = parse_courses(root)
    for c in courses:
        c["total_candidates"] = len(c["candidates"])
        c["candidates"] = c["candidates"][:top]
    return {"schema": SCHEMA, "generated_at": generated.isoformat(timespec="minutes"), "stale": stale,
            "report_path": str(report_path), "top": top, "courses": courses}


def format_text(result: dict, today_label: str) -> str:
    lines = []
    gen = datetime.fromisoformat(result["generated_at"]).strftime("%Y-%m-%d %H:%M")
    if result["stale"]:
        lines.append(f"【古いレポートです】生成日時 {gen} JST は今日({today_label})ではありません。"
                     "近日分の予報は更新されている可能性があり、答えの根拠にしないでください。")
    lines.append(f"レポート生成日時: {gen} JST")
    for c in result["courses"]:
        lines += ["", f"■ {c['title']}(上位{len(c['candidates'])}件 / レポート内{c['total_candidates']}件)",
                  f"条件: {c['condition_note']}"]
        if c["weather_note"]:
            lines.append(f"気象メモ: {c['weather_note']}")
        if not c["candidates"]:
            lines.append(f"候補なし: {c['empty_note']}")
            continue
        for k in c["candidates"]:
            lines.append(f"{k['rank']}. {k['name']}({k['municipality']}) スコア{k['score']} / 東京から直線{k['distance_km']}km")
            lines.append(f"   日付 {k['date']} / 見頃 {k['window']}(狙い目 {k['best_time']}) / "
                         f"視界遮蔽雲量 平均{k['obstruction_pct']}% / 実効的な空の明るさ {k['effective_mpsas']:.2f} mag/arcsec²")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None, now: datetime | None = None) -> int:
    ap = argparse.ArgumentParser(description="report.html から気軽・硬派コースの上位候補を表示する(通信しない)")
    ap.add_argument("--report", type=Path, default=ROOT / "report.html")
    ap.add_argument("--top", type=int, default=3)
    ap.add_argument("--allow-stale", action="store_true", help="生成日時が今日でなくても、古い旨を明記して出力する")
    ap.add_argument("--json-out", type=Path)
    ap.add_argument("--out", type=Path, help="テキストをUTF-8でこのファイルへ書く(標準出力にも出す)")
    args = ap.parse_args(argv)
    if args.top < 1:
        ap.error("--top は1以上")
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    today = (now or datetime.now(JST)).astimezone(JST).date()
    if not args.report.is_file():
        print(f"[中止] {args.report} がありません。py -X utf8 generate_report.py で生成してください"
              "(10〜30分・Open-Meteo約220回。実行前にユーザーの承認を得ること)。", file=sys.stderr)
        return EXIT_STALE
    try:
        text = args.report.read_text(encoding="utf-8")
        generated = parse_generated_at(parse_html(text))
        stale = generated.date() != today
        if stale and not args.allow_stale:
            print(f"[中止] report.html の生成日時 {generated:%Y-%m-%d %H:%M} JST は今日({today})ではないため、"
                  "答えに使いません。再生成する(ユーザーの承認が必要)か、--allow-stale で古い旨つきの出力にしてください。",
                  file=sys.stderr)
            return EXIT_STALE
        result = build_result(text, args.report, args.top, stale)
    except ParseError as e:
        print(f"[解析失敗] report.html が想定の構造ではありません: {e}\n"
              "(generate_report.py の render_candidate_group / render_tier2 の構造が変わった可能性があります。"
              "推測では埋めません。)", file=sys.stderr)
        return EXIT_PARSE

    out_text = format_text(result, str(today))
    print(out_text, end="")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(out_text, encoding="utf-8")
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
