"""数値JSON(hoshibiyori-skyguide-data/1)から、解説に書く数値を引く関数。通信しない。

`scripts/sky_lookup.py`(書き手が数値を引く)と `skyguide/check_numbers.py`(解説の数値の機械照合)が同じ関数を使う。
"""
from __future__ import annotations

COMPASS16 = ["北", "北北東", "北東", "東北東", "東", "東南東", "南東", "南南東",
             "南", "南南西", "南西", "西南西", "西", "西北西", "北西", "北北西"]

# 解説の呼び名 → (frames内の種別, frames内のキー)
GC_NAMES = ("天の川の中心部", "天の川の中心")
MOON_NAMES = ("月",)


def compass16(az: float) -> str:
    """方位角(度)を16方位名にする。北=0°、1方位=22.5°幅(北は348.75〜11.25°)。"""
    return COMPASS16[int(((az % 360) + 11.25) // 22.5) % 16]


def round_half_up(x: float) -> int:
    return int(x + 0.5) if x >= 0 else -int(-x + 0.5)


def ridge_range(horizon_deg: list[float], az_from: float, az_to: float) -> tuple[int, int]:
    """方位 az_from〜az_to(度、360をまたぐ範囲も可: 345〜15)の稜線の仰角の最小・最大(整数に四捨五入)。両端を含む。"""
    lo, hi = int(az_from) % 360, int(az_to) % 360
    n = len(horizon_deg)
    idx = list(range(lo, hi + 1)) if lo <= hi else list(range(lo, n)) + list(range(0, hi + 1))
    vals = [horizon_deg[i % n] for i in idx]
    return round_half_up(min(vals)), round_half_up(max(vals))


def frame_index(data: dict, hhmm: str) -> int | None:
    """時刻 HH:MM が数値JSONの times にあればその添字。"""
    times = data.get("times", [])
    return times.index(hhmm) if hhmm in times else None


def nearest_frame_index(data: dict, hhmm: str, within_min: int = 10) -> int | None:
    """times の中で hhmm に最も近い添字(夜をまたぐ時刻も考慮)。within_min 分より離れていれば None。"""
    def mins(s: str) -> int:
        h, m = s.split(":")
        return int(h) * 60 + int(m)
    best, best_d = None, None
    for i, t in enumerate(data.get("times", [])):
        d = abs(mins(t) - mins(hhmm))
        d = min(d, 1440 - d)
        if best_d is None or d < best_d:
            best, best_d = i, d
    return best if best_d is not None and best_d <= within_min else None


def position_in_frame(frame: dict, name: str) -> tuple[float, float] | None:
    """frame 内の天体 name の [方位, 高度]。無ければ None。"""
    if name in GC_NAMES:
        gc = frame.get("gc")
        return (gc[0], gc[1]) if gc else None
    if name in MOON_NAMES:
        m = frame.get("moon")
        return (m["az"], m["alt"]) if m else None
    if name == "北極星":
        name = "ポラリス(北極星)"
    for group in ("stars", "planets"):
        v = frame.get(group, {}).get(name)
        if v is not None:
            return (v[0], v[1])
    return None


def known_object_names(data: dict) -> set[str]:
    """frames に載っている天体の呼び名(解説の文中で使える名前)。"""
    names: set[str] = set(GC_NAMES) | set(MOON_NAMES)
    for fr in data.get("frames", []):
        names |= set(fr.get("stars", {}))
        names |= set(fr.get("planets", {}))
    if "ポラリス(北極星)" in names:
        names.add("北極星")
    return names
