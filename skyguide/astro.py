"""星空ガイドの数値(天体の方位・高度、月、天の川の帯、出来事の一覧、稜線のピーク候補)を計算する。

天体位置は step1_astronomy.sky_engine.altaz_at_time(Skyfield、時刻配列も可)、月は
step4_moonlight.moon_position.compute_moon_position を呼ぶ。通信はしない
(暦ファイル de421.bsp が無ければ Skyfield が自動ダウンロードするので、呼び出し側で存在を確認すること)。
"""
from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _sub in ("step1_astronomy", "step4_moonlight"):
    if str(ROOT / _sub) not in sys.path:
        sys.path.insert(0, str(ROOT / _sub))

from skyfield.api import wgs84  # noqa: E402

from catalog import Target, get_target  # noqa: E402
from moon_position import compute_moon_position  # noqa: E402
from sky_engine import altaz_at_time  # noqa: E402

JST = timezone(timedelta(hours=9))
EPHEMERIS_PATH = ROOT / "step1_astronomy" / "de421.bsp"
_PKG = Path(__file__).parent
GC_TARGET_ID = "galactic_center"
PLANETS = {"水星": "mercury", "金星": "venus", "火星": "mars barycenter", "木星": "jupiter barycenter", "土星": "saturn barycenter"}


def _load_json(name: str) -> dict:
    with open(_PKG / name, encoding="utf-8") as f:
        return json.load(f)


def load_objects() -> list[dict]:
    out = []
    for o in _load_json("objects.json")["objects"]:
        h, m, s = o["ra_hms"]
        sign = -1.0 if any(x < 0 for x in o["dec_dms"]) else 1.0
        d, dm, ds = (abs(x) for x in o["dec_dms"])
        out.append({"name": o["name"], "ra_hours": h + m / 60 + s / 3600,
                    "dec_deg": sign * (d + dm / 60 + ds / 3600), "mag": o["mag"]})
    return out


def load_plane_intensity() -> tuple[int, list[float]]:
    j = _load_json("milkyway.json")
    return j["step_deg"], j["intensity"]


def _target(name: str, ra_hours: float, dec_deg: float) -> Target:
    return Target(id=name, name=name, name_en=name, ra_hours=ra_hours, dec_deg=dec_deg, best_season="", best_months=[])


def galactic_to_radec(l_deg: float, b_deg: float = 0.0) -> tuple[float, float]:
    """銀河座標(l, b)→赤道座標J2000(ra_hours, dec_deg)。銀河北極(RA 192.85948°, Dec +27.12825°)、l_NCP=122.93192°。"""
    ra_ngp, dec_ngp, l_ncp = map(math.radians, (192.85948, 27.12825, 122.93192))
    l, b = math.radians(l_deg), math.radians(b_deg)
    dec = math.asin(math.sin(b) * math.sin(dec_ngp) + math.cos(b) * math.cos(dec_ngp) * math.cos(l_ncp - l))
    y = math.cos(b) * math.sin(l_ncp - l)
    x = math.sin(b) * math.cos(dec_ngp) - math.cos(b) * math.sin(dec_ngp) * math.cos(l_ncp - l)
    ra = (ra_ngp + math.atan2(y, x)) % (2 * math.pi)
    return math.degrees(ra) / 15.0, math.degrees(dec)


def time_grid(start: datetime, step_min: int, count: int) -> list[datetime]:
    return [start + timedelta(minutes=step_min * i) for i in range(count)]


def _r(x: float, n: int = 1) -> float:
    return round(float(x), n)


def _gc_radec() -> tuple[float, float]:
    g = get_target(GC_TARGET_ID)
    return g.ra_hours, g.dec_deg


def _skytime(ts, times: list[datetime]):
    return ts.from_datetimes([x.astimezone(timezone.utc) for x in times])


def _planet_altaz(eph, lat, lon, elev, t) -> dict[str, tuple]:
    observer = eph["earth"] + wgs84.latlon(lat, lon, elevation_m=elev)
    out = {}
    for jp, key in PLANETS.items():
        alt, az, _ = observer.at(t).observe(eph[key]).apparent().altaz()
        out[jp] = (az.degrees, alt.degrees)
    return out


def compute_frames(ts, eph, lat: float, lon: float, elev: float, times: list[datetime]) -> list[dict]:
    """各時刻の全天フレーム(恒星・惑星・銀河中心・天の川の帯・月)。"""
    t = _skytime(ts, times)
    stars = {o["name"]: altaz_at_time(t, eph, lat, lon, elev, _target(o["name"], o["ra_hours"], o["dec_deg"]))
             for o in load_objects()}
    gc = altaz_at_time(t, eph, lat, lon, elev, _target("gc", *_gc_radec()))
    planets = _planet_altaz(eph, lat, lon, elev, t)
    step, intensity = load_plane_intensity()
    plane = [(l, altaz_at_time(t, eph, lat, lon, elev, _target(f"l{l}", *galactic_to_radec(l, 0.0))))
             for l in range(0, 360, step)]
    frames = []
    for i, dt in enumerate(times):
        mp = compute_moon_position(ts, eph, lat, lon, elev, dt)
        later = compute_moon_position(ts, eph, lat, lon, elev, dt + timedelta(hours=1))
        frames.append({
            "stars": {n: [_r(v[0][i]), _r(v[1][i])] for n, v in stars.items()},
            "plane": [[l, _r(v[0][i]), _r(v[1][i]), intensity[k]] for k, (l, v) in enumerate(plane)],
            "planets": {n: [_r(v[0][i]), _r(v[1][i])] for n, v in planets.items()},
            "gc": [_r(gc[0][i]), _r(gc[1][i])],
            "moon": {"az": _r(mp.az_deg), "alt": _r(mp.alt_deg), "phase_angle": _r(mp.phase_angle_deg),
                     "illum": _r((1 + math.cos(math.radians(mp.phase_angle_deg))) / 2, 2),
                     "waxing": bool(later.phase_angle_deg < mp.phase_angle_deg)},  # 満ちていく=位相角が減っていく
        })
    return frames


def starmag() -> dict[str, float]:
    return {o["name"]: o["mag"] for o in load_objects()}


def horizon_at(horizon_deg: list[float], az: float) -> float:
    return horizon_deg[int(round(az)) % 360]


def _hhmm(dt: datetime) -> str:
    return dt.strftime("%H:%M")


def _runs(flags: list[bool]) -> list[tuple[int, int]]:
    runs, start = [], None
    for i, f in enumerate(flags):
        if f and start is None:
            start = i
        elif not f and start is not None:
            runs.append((start, i - 1))
            start = None
    if start is not None:
        runs.append((start, len(flags) - 1))
    return runs


MERGE_GAP_MIN = 10  # 稜線すれすれで出入りを繰り返す天体は、この分数以内の途切れを1つの区間にまとめる


def _merge_runs(runs: list[tuple[int, int]], gap: int) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for a, b in runs:
        if merged and a - merged[-1][1] - 1 <= gap:
            merged[-1] = (merged[-1][0], b)
        else:
            merged.append((a, b))
    return merged


def _ridge_events(kind: str, name: str, times, az, alt, horizon_deg) -> list[dict]:
    n = len(times)
    flags = [alt[i] > horizon_deg[int(round(az[i])) % 360] for i in range(n)]
    out = []
    for a, b in _merge_runs(_runs(flags), MERGE_GAP_MIN):
        k = max(range(a, b + 1), key=lambda i: alt[i])
        ev = {"type": kind, "name": name, "start": _hhmm(times[a]), "end": _hhmm(times[b]),
              "rises_over_ridge": a > 0, "sets_behind_ridge": b < n - 1,
              "max_alt": _r(alt[k]), "max_alt_time": _hhmm(times[k]), "max_alt_az": _r(az[k])}
        if a > 0:
            ev["rise_az"] = _r(az[a])
        if b < n - 1:
            ev["set_az"] = _r(az[b])
        out.append(ev)
    return out


def compute_events(ts, eph, lat, lon, elev, dark_start: datetime, dark_end: datetime, horizon_deg: list[float]) -> list[dict]:
    """決定論の出来事の一覧(暗い時間帯を1分刻みで走査)。解説の文に入れてよい数値の出どころ。"""
    n = int((dark_end - dark_start).total_seconds() // 60) + 1
    times = time_grid(dark_start, 1, n)
    t = _skytime(ts, times)
    events: list[dict] = []
    az, alt = altaz_at_time(t, eph, lat, lon, elev, _target("gc", *_gc_radec()))
    events += _ridge_events("gc_above_ridge", "天の川の中心", times, az, alt, horizon_deg)
    for o in load_objects():
        az, alt = altaz_at_time(t, eph, lat, lon, elev, _target(o["name"], o["ra_hours"], o["dec_deg"]))
        if o["name"] == "ポラリス(北極星)":
            events.append({"type": "polaris_altitude", "alt": _r(alt[n // 2]), "az": _r(az[n // 2])})
        elif o["mag"] <= 2.0:
            events += _ridge_events("star_above_ridge", o["name"], times, az, alt, horizon_deg)
    for jp, (az, alt) in _planet_altaz(eph, lat, lon, elev, t).items():
        events += _ridge_events("planet_above_ridge", jp, times, az, alt, horizon_deg)
    mt = times[::5] + ([times[-1]] if (n - 1) % 5 else [])
    moon_alt = [compute_moon_position(ts, eph, lat, lon, elev, dt).alt_deg for dt in mt]
    runs = _runs([a > 0 for a in moon_alt])
    if not runs:
        events.append({"type": "moon_below_horizon_all_night"})
    for a, b in runs:
        events.append({"type": "moon_up", "start": _hhmm(mt[a]), "end": _hhmm(mt[b]), "max_alt": _r(max(moon_alt[a:b + 1]))})
    return events


def detect_ridge_peaks(horizon_deg: list[float], min_prominence_deg: float = 1.5, min_alt_deg: float = 3.0) -> list[dict]:
    """horizon_deg(360)の極大(稜線のピーク候補)。名前はnull。左右15°以内で最大、かつ両側30°の谷より prominence 以上高いもの。"""
    n = 360
    peaks = []
    for i in range(n):
        v = horizon_deg[i]
        if v < min_alt_deg:
            continue
        if v < max(horizon_deg[(i + k) % n] for k in range(-15, 16)):
            continue
        if any(horizon_deg[(i + k) % n] == v for k in range(-15, 0)):
            continue  # 平坦な頂は最も小さい方位だけ採る
        left = min(horizon_deg[(i - k) % n] for k in range(1, 31))
        right = min(horizon_deg[(i + k) % n] for k in range(1, 31))
        if v - max(left, right) >= min_prominence_deg:
            peaks.append({"az": i, "alt": _r(v), "name": None})
    return peaks
