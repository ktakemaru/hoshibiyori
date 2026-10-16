"""解説JSONの文章中の「時刻の言い回し」を、数値JSONの events と機械照合する。

対象は「天体が昇る・沈む(稜線を越える・隠れる)時刻」を述べた文だけ。次の言い回しの範囲を規則として固定する。
  N時M分ごろ : 実際の時刻が N:M の前後10分以内
  N時すぎ    : 実際の時刻が N:00 以上 N:30 未満(0〜29分後)
  N時前      : 実際の時刻が N:00 の30分前以上 N:00 未満
  N時ごろ    : 実際の時刻が N:00 の前後30分以内
  N時台      : 実際の時刻が N:00 以上 N+1:00 未満
例: 稜線を越える時刻が 01:57 の天体は「2時前」(1:30〜2:00)で、「1時すぎ」(1:00〜1:29)ではない。

照合できないもの(対象外): 天体名が文中に無い文、昇る・沈む・隠れる等の動詞が無い文、events に無い天体(等級2.0より暗い恒星)、
高度・方位の数値、「N時に」「N時から」の言い方。これらは検査せず、文章を書く側が events と frames から取ること。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# 文中の呼び名 → events の name(三つ星は3つのどれか)
ALIASES: dict[str, list[str]] = {"三つ星": ["アルニタク", "アルニラム", "ミンタカ"], "天の川の中心部": ["天の川の中心"],
                                 "北極星": ["ポラリス(北極星)"], "すばる": ["すばる"]}
RISE_VERBS = ("昇", "のぼ", "顔を出", "現れ")
SET_VERBS = ("沈", "隠れ")

_PHRASES = [
    ("minute", re.compile(r"(\d{1,2})時(\d{1,2})分(?:ごろ|頃|ころ)")),
    ("sugi", re.compile(r"(\d{1,2})時(?:すぎ|過ぎ)")),
    ("mae", re.compile(r"(\d{1,2})時前")),
    ("goro", re.compile(r"(\d{1,2})時(?:ごろ|頃|ころ)")),
    ("dai", re.compile(r"(\d{1,2})時台")),
]


@dataclass
class Finding:
    where: str
    sentence: str
    phrase: str
    name: str
    verb: str
    actual: list[str]
    # 種別: time_phrase(時刻の言い回し。このモジュールが返すのはこれだけ) / altitude / ridge_range / vague_time / moon_adjective
    # (後ろの4つは skyguide/check_numbers.py が返す)。severity が "warning" のものは出力を止めない。
    kind: str = "time_phrase"
    message: str = ""
    severity: str = "error"

    def __str__(self) -> str:
        if self.message:
            return f"[{self.where}] ({self.kind}) {self.message} 文: {self.sentence}"
        act = "・".join(self.actual) if self.actual else "該当する出来事なし"
        return f"[{self.where}] 「{self.phrase}」({self.name}が{'昇る' if self.verb == 'rise' else '沈む'}) は数値と合いません。events上は {act}。 文: {self.sentence}"


def _mins(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _circ(a: int, b: int) -> int:
    d = (a - b) % 1440
    return d if d < 720 else d - 1440  # a - b を -720..719 に


def phrase_matches(kind: str, groups: tuple[str, ...], actual: str) -> bool:
    a = _mins(actual)
    h = int(groups[0]) % 24
    base = h * 60
    if kind == "minute":
        return abs(_circ(a, base + int(groups[1]))) <= 10
    delta = _circ(a, base)  # 実際 - N:00(分)
    if kind == "sugi":
        return 0 <= delta < 30
    if kind == "mae":
        return -30 <= delta < 0
    if kind == "goro":
        return abs(delta) <= 30
    if kind == "dai":
        return 0 <= delta < 60
    raise ValueError(kind)


def _object_names(events: list[dict]) -> set[str]:
    return {e["name"] for e in events if "name" in e}


def _find_objects(clause: str, known: set[str]) -> list[str]:
    """clause 中の天体名を、events の name(の集合)に直して返す。長い呼び名を優先し、重複を除く。"""
    found: list[str] = []
    for alias, targets in ALIASES.items():
        if alias in clause:
            found.append(alias)
    for n in sorted(known, key=len, reverse=True):
        if n in clause and not any(n in a for a in found) and n not in found:
            found.append(n)
    return found


def _verb(text: str) -> str | None:
    last, kind = -1, None
    for kinds, verbs in (("rise", RISE_VERBS), ("set", SET_VERBS)):
        for v in verbs:
            i = text.rfind(v)
            if i > last:
                last, kind = i, kinds
    return kind


def _actual_times(events: list[dict], names: list[str], verb: str) -> list[str]:
    out = []
    for e in events:
        if e.get("name") in names:
            if verb == "rise" and e.get("rises_over_ridge"):
                out.append(e["start"])
            if verb == "set" and e.get("sets_behind_ridge"):
                out.append(e["end"])
    return out


def check_sentence(sentence: str, events: list[dict], where: str) -> list[Finding]:
    known = _object_names(events)
    clauses = re.split(r"[、,]", sentence)
    sentence_objs = _find_objects(sentence, known)
    sentence_verb = _verb(sentence)
    findings: list[Finding] = []
    for clause in clauses:
        phrases = [(k, m) for k, rx in _PHRASES for m in rx.finditer(clause)]
        # 「N時M分ごろ」の一部を「N時ごろ」等として二重に拾わない(分つきを優先)
        phrases = [(k, m) for k, m in phrases if not (k != "minute" and any(
            k2 == "minute" and m2.start() <= m.start() < m2.end() for k2, m2 in phrases))]
        if not phrases:
            continue
        objs = _find_objects(clause, known)
        if not objs and len(sentence_objs) == 1:
            objs = sentence_objs  # 文中の天体が1つだけなら、時刻だけの節にもその天体を当てる
        verb = _verb(clause) or sentence_verb
        if not objs or verb is None:
            continue
        for obj in objs:
            names = ALIASES.get(obj, [obj])
            if not (set(names) & known):
                continue  # eventsに無い天体は照合できない
            actual = _actual_times(events, names, verb)
            for k, m in phrases:
                if not any(phrase_matches(k, m.groups(), t) for t in actual):
                    findings.append(Finding(where, sentence, m.group(0), obj, verb, sorted(set(actual))))
    return findings


def _walk(comm: dict):
    """(場所, 文字列) を返す。照合するのは読み手に見える文章の項目だけ。"""
    yield "lead", comm.get("lead", "")
    for i, f in enumerate(comm.get("facts", [])):
        yield f"facts[{i}].sub", f.get("sub", "")
        yield f"facts[{i}].value", f.get("value", "")
    for c in comm.get("cards", []):
        yield f"cards[{c.get('id')}].body", c.get("body", "")
        for j, x in enumerate(c.get("list", [])):
            yield f"cards[{c.get('id')}].list[{j}]", x
    for i, d in enumerate(comm.get("directions", [])):
        yield f"directions[{i}].sky", d.get("sky", "")
        yield f"directions[{i}].terrain", d.get("terrain", "")
    for i, t in enumerate(comm.get("tips", [])):
        yield f"tips[{i}].body", t.get("body", "")


def check_text(data: dict, commentary: dict) -> list[Finding]:
    events = data.get("events", [])
    out: list[Finding] = []
    for where, text in _walk(commentary):
        for sentence in re.split(r"(?<=[。！？])", text):
            if sentence.strip():
                out += check_sentence(sentence.strip(), events, where)
    return out
