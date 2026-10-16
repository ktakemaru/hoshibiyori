"""解説JSONの文章中の「数値」を、数値JSON(frames・horizon_deg・events)と機械照合する。通信しない。

`skyguide/check_text.py`(時刻の言い回しだけを見る)は変えず、こちらで次の4種類を足す。`check_all()` が両方をまとめて返す。
Finding.kind で見分ける。

  altitude     : 「天体名(16方位の高度N°)」「天体名は…16方位の高度N°」の高度と方位を、その文に結びつく時刻のフレームと照合する。
                 時刻は文(節)中の「N時M分」「N時半」「N時」。無ければ cards[].time。どちらも無ければ検査しない。
                 方位名は frames の方位角を16方位にしたものと一致、高度は四捨五入して±1°以内。frames に無い天体は検査しない。
  ridge_range  : directions[].label の方位範囲(「北 345〜15°」)と elevation(「7〜10°」)を horizon_deg の同範囲の最小・最大(四捨五入)と照合する。
                 本文中の「南西(210〜255°)の稜線は1〜4°」のように方位範囲が併記された言及も同様に照合する。
                 方位範囲が書かれていない言及(「南西の稜線は1〜4°」)は検査しない。方位範囲を併記して書くこと。
  vague_time   : 天体名+昇る・沈む・隠れる・越える等の動詞がある節に「明け方・未明・夜半・宵・夕方」等があれば、events の時刻を数字で書くよう指摘する。
                 動詞が無い記述(「明け方のオリオン座」)は検査しない。
  moon_adjective: 月が出ている夜の輝面が30%を超えるのに「細い月・三日月」と書いたとき(警告。出力は止めない)。

検査しないもの: 天体名のない文、frames に無い天体、時刻が決まらない文(card.time も文中の時刻も無い)、フレームの時刻から10分以上離れた時刻、
方位範囲の無い稜線の仰角、雲量・距離・輝面など高度以外の数値。
"""
from __future__ import annotations

import re

from skyguide.check_text import Finding, _walk, check_text
from skyguide.lookup import (ridge_range, compass16, known_object_names,
                             nearest_frame_index, position_in_frame)

ALT_TOLERANCE_DEG = 1.0
MOON_THIN_ILLUM = 0.30  # 輝面がこれを超える月を「細い月」と書いたら警告

VAGUE_WORDS = ("明け方", "未明", "夜半", "宵", "夕方", "夜明け", "朝方", "日没後", "日の出前")
EVENT_VERBS = ("昇", "のぼ", "顔を出", "現れ", "沈", "隠れ", "越え")
MOON_THIN_WORDS = ("細い月", "三日月", "繊月", "極細の月")

_COMPASS = "(?:北北東|東北東|東南東|南南東|南南西|西南西|西北西|北北西|北東|南東|南西|北西|北|東|南|西)"
_TIME_RX = re.compile(r"(\d{1,2})時(?:(\d{1,2})分|(半))?")
_ALT_RX = re.compile(rf"(?:({_COMPASS})の)?高度\s*(\d{{1,2}}(?:\.\d)?)\s*°")
_RANGE_BODY_RX = re.compile(
    r"(\d{1,3})\s*[〜~～]\s*(\d{1,3})\s*°?\s*[)）]?の[^。、()（）\d]{0,10}?(?:稜線|地平線|山並み|尾根)[^。、()（）\d]{0,8}?"
    r"(\d{1,2})(?:\s*[〜~～]\s*(\d{1,2}))?\s*°")
_LABEL_RANGE_RX = re.compile(r"(\d{1,3})\s*[〜~～]\s*(\d{1,3})")
_ELEV_RX = re.compile(r"^\s*(\d{1,2})(?:\s*[〜~～]\s*(\d{1,2}))?\s*°?\s*$")
_CARD_RX = re.compile(r"^cards\[(.+?)\]")


def _fmt_range(lo: int, hi: int) -> str:
    return f"{lo}°" if lo == hi else f"{lo}〜{hi}°"


_AMBIGUOUS_TIME_RX = re.compile(r"\d{1,2}時(?:台|すぎ|過ぎ|前|ごろ|頃|ころ)")


def _time_in(text: str) -> str | None:
    """text 中の最初の正確な時刻(「N時M分」「N時半」「N時」)。「N時台」「N時すぎ」等の幅のある言い方は時刻として扱わない。"""
    m = _TIME_RX.search(_AMBIGUOUS_TIME_RX.sub("", text))
    if not m:
        return None
    h = int(m.group(1)) % 24
    mi = 30 if m.group(3) else int(m.group(2) or 0)
    return f"{h:02d}:{mi:02d}"


def _names_in(clause: str, known: set[str]) -> list[tuple[int, int, str]]:
    """clause 中の天体名の (開始, 終了, 名前)。長い名前を優先し、重なるものは除く。"""
    spans: list[tuple[int, int, str]] = []
    for n in sorted(known, key=len, reverse=True):
        for m in re.finditer(re.escape(n), clause):
            if n == "月" and (clause[max(0, m.start() - 1):m.start()].isdigit() or clause[m.end():m.end() + 1] in ("明", "齢", "相", "末", "初")):
                continue  # 「10月」「月明かり」「月齢」は天体の月ではない
            if not any(s < m.end() and m.start() < e for s, e, _ in spans):
                spans.append((m.start(), m.end(), n))
    return sorted(spans)


def _check_altitudes(data: dict, commentary: dict) -> list[Finding]:
    known = known_object_names(data)
    card_time = {str(c.get("id")): c.get("time") for c in commentary.get("cards", [])}
    out: list[Finding] = []
    for where, text in _walk(commentary):
        cm = _CARD_RX.match(where)
        default_time = card_time.get(cm.group(1)) if cm else None
        for sentence in re.split(r"(?<=[。！？])", text):
            sentence = sentence.strip()
            if not sentence:
                continue
            distinct = {n for _, _, n in _names_in(sentence, known)}
            carried: str | None = None  # 前の節までに出てきた時刻(後ろの節の時刻は前の節に使わない)
            for clause in re.split(r"[、,]", sentence):
                clause_names = _names_in(clause, known)
                if _AMBIGUOUS_TIME_RX.search(clause):
                    continue  # 「22時台に高度56°」のように時刻に幅がある節は照合しない
                own_time = _time_in(clause)
                time = own_time or carried or default_time
                carried = own_time or carried
                if time is None:
                    continue
                idx = nearest_frame_index(data, time)
                if idx is None:
                    continue
                frame = data["frames"][idx]
                for am in _ALT_RX.finditer(clause):
                    # 高度の直前にある(同じ節の)天体名に結びつける。無く、文中の天体が1つだけならその天体
                    before = [n for s, e, n in clause_names if e <= am.start()]
                    if before:
                        obj = before[-1]
                    elif not clause_names and len(distinct) == 1:
                        obj = next(iter(distinct))
                    else:
                        continue
                    pos = position_in_frame(frame, obj)
                    if pos is None:
                        continue
                    az, alt = pos
                    said_dir, said_alt = am.group(1), float(am.group(2))
                    problems = []
                    if said_dir and compass16(az) != said_dir:
                        problems.append(f"方位は{compass16(az)}(方位角{az:.0f}°)")
                    if abs(round(alt) - said_alt) > ALT_TOLERANCE_DEG:
                        problems.append(f"高度は{alt:.0f}°")
                    if problems:
                        t = data["times"][idx]
                        out.append(Finding(where, sentence, am.group(0), obj, "", [],
                                           kind="altitude",
                                           message=f"{obj}の「{am.group(0)}」は{t}のフレームと合いません。{t}では{'、'.join(problems)}。"
                                                   f"時刻の決め方: {'文中の時刻' if (own_time or carried) else 'card.time'}({t})。"))
    return out


def _horizon(data: dict) -> list[float] | None:
    h = data.get("horizon_deg")
    return h if isinstance(h, list) and h else None


def _check_ridge_ranges(data: dict, commentary: dict) -> list[Finding]:
    hz = _horizon(data)
    if hz is None:
        return []
    out: list[Finding] = []
    for i, d in enumerate(commentary.get("directions", [])):
        lm = _LABEL_RANGE_RX.search(d.get("label", ""))
        em = _ELEV_RX.match(d.get("elevation", ""))
        if not lm or not em:
            continue
        lo, hi = ridge_range(hz, int(lm.group(1)), int(lm.group(2)))
        said = (int(em.group(1)), int(em.group(2) or em.group(1)))
        if said != (lo, hi):
            out.append(Finding(f"directions[{i}].elevation", f"{d.get('label')} {d.get('elevation')}", d.get("elevation", ""),
                               "", "", [], kind="ridge_range",
                               message=f"方位{lm.group(1)}〜{lm.group(2)}°の稜線の仰角は {_fmt_range(lo, hi)}(horizon_deg)で、"
                                       f"「{d.get('elevation')}」とは合いません。"))
    for where, text in _walk(commentary):
        for sentence in re.split(r"(?<=[。！？])", text):
            for m in _RANGE_BODY_RX.finditer(sentence):
                lo, hi = ridge_range(hz, int(m.group(1)), int(m.group(2)))
                said = (int(m.group(3)), int(m.group(4) or m.group(3)))
                if said != (lo, hi):
                    out.append(Finding(where, sentence.strip(), m.group(0), "", "", [], kind="ridge_range",
                                       message=f"方位{m.group(1)}〜{m.group(2)}°の稜線の仰角は {_fmt_range(lo, hi)}(horizon_deg)で、"
                                               f"「{_fmt_range(*said)}」とは合いません。"))
    return out


def _event_times(events: list[dict], name: str) -> list[str]:
    out = []
    for e in events:
        if e.get("name") == name or (name == "天の川の中心部" and e.get("name") == "天の川の中心"):
            if e.get("rises_over_ridge"):
                out.append(f"{e['start']}に稜線を越える")
            if e.get("sets_behind_ridge"):
                out.append(f"{e['end']}に稜線に隠れる")
    return out


def _check_vague_time(data: dict, commentary: dict) -> list[Finding]:
    known = known_object_names(data)
    events = data.get("events", [])
    out: list[Finding] = []
    for where, text in _walk(commentary):
        for sentence in re.split(r"(?<=[。！？])", text):
            sentence = sentence.strip()
            for clause in re.split(r"[、,]", sentence):
                word = next((w for w in VAGUE_WORDS if w in clause), None)
                if word is None or not any(v in clause for v in EVENT_VERBS):
                    continue
                for _, _, n in _names_in(clause, known):
                    times = _event_times(events, n)
                    hint = f"events上は {'・'.join(times)}" if times else "events に稜線を越える・隠れる時刻はありません"
                    out.append(Finding(where, sentence, word, n, "", [], kind="vague_time",
                                       message=f"{n}が昇る・沈む・隠れる時刻に「{word}」を使っています。{hint}。時刻を数字で書いてください"
                                               f"(例: 「{n}は01:04に稜線を越える」)。"))
    return out


def _check_moon_adjective(data: dict, commentary: dict) -> list[Finding]:
    illums = [fr["moon"]["illum"] for fr in data.get("frames", []) if fr.get("moon") and fr["moon"].get("alt", -1) > 0]
    if not illums or max(illums) <= MOON_THIN_ILLUM:
        return []
    out: list[Finding] = []
    for where, text in _walk(commentary):
        for w in MOON_THIN_WORDS:
            if w in text:
                out.append(Finding(where, text, w, "月", "", [], kind="moon_adjective", severity="warning",
                                   message=f"月が出ている間の輝面は最大{max(illums) * 100:.0f}%で、「{w}」とは言えません"
                                           f"(基準は{MOON_THIN_ILLUM * 100:.0f}%)。輝面の数字か「上弦前の月」などにしてください。"))
    return out


def check_numbers(data: dict, commentary: dict) -> list[Finding]:
    return (_check_altitudes(data, commentary) + _check_ridge_ranges(data, commentary)
            + _check_vague_time(data, commentary) + _check_moon_adjective(data, commentary))


def check_all(data: dict, commentary: dict) -> list[Finding]:
    """時刻の言い回し(check_text)と、数値(このモジュール)の両方。"""
    return check_text(data, commentary) + check_numbers(data, commentary)
