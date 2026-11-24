"""「この時期の見どころ」(季節の星座・星団・惑星・流星群)の値を作る。2026-11-24 追加。

- 文ではなく値(dict)を返す。文にするのは generate_report.render_sky_guide(あとで JSON にも出せるようにするため)。
- 基準の地点・平らな地平線の目安で、地形・雲は見ない。候補の選び方・順位・スコアには使わない。
- 対象は step1_astronomy/targets.json(星・星団など。座標の出どころは各項目の source)、惑星は de421.bsp、
  流星群は step1_astronomy/meteor_showers.json。
- 並べ方は「惑星 → 今が季節(その時間帯の中で南中する)→ そのほか」。同じ中では targets.json の並び順。
  月明かりのある時間帯は、1等星を含む対象を先にする。人気の順は作らない。
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

JST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parent
SHOWERS_PATH = ROOT / "step1_astronomy" / "meteor_showers.json"

SAMPLE_MIN = 15
EVENING_END_HOUR = 22          # 宵と夜半の境(仮の値)
MIDNIGHT_END_HOUR = 2          # 夜半と明け方の境(翌日。仮の値)
MAX_ITEMS_PER_SLOT = 4         # 時間帯ごとの件数の上限(仮の値)
METEOR_DAYS_AHEAD = 30         # これ以内に極大がある流星群を出す(仮の値)
RADIANT_MIN_ALT_DEG = 20.0     # 放射点がこの高度以上の時間帯を出す(指示書の値)
NEXT_VISIBLE_MONTHS = 12       # 「次に見えるのは○月ごろ」を探す月数

SLOTS = (("evening", "宵"), ("midnight", "夜半"), ("dawn", "明け方"))
PLANETS = (("金星", "venus"), ("火星", "mars barycenter"), ("木星", "jupiter barycenter"), ("土星", "saturn barycenter"))
FAINT_KINDS = ("星団", "星雲", "銀河", "天の川")

METEOR_CAVEAT = "理想の条件での目安で、実際に見える数はこれより少ない。突発的な増減は予測できない"


@dataclass(frozen=True)
class Member:
    name: str
    az: tuple
    alt: tuple


def _utc(ts, times):
    return ts.from_datetimes([t.astimezone(timezone.utc) for t in times])


def _grid(start: datetime, end: datetime, step_min: int = SAMPLE_MIN) -> list[datetime]:
    """start から刻みごと。終わりの時刻も必ず入れる。"""
    times, t = [], start
    while t < end:
        times.append(t)
        t += timedelta(minutes=step_min)
    times.append(end)
    return times


def night_slots(night_date: date, dark_start: datetime, dark_end: datetime) -> list[tuple[str, str, datetime, datetime]]:
    """宵(暗くなってから22時まで)・夜半(22時〜翌2時)・明け方(翌2時〜明るくなるまで)。暗い時間帯と重ならないものは出さない。"""
    midnight = datetime(night_date.year, night_date.month, night_date.day, tzinfo=JST) + timedelta(days=1)
    b1 = midnight - timedelta(hours=24 - EVENING_END_HOUR)
    b2 = midnight + timedelta(hours=MIDNIGHT_END_HOUR)
    bounds = [(dark_start, min(b1, dark_end)), (max(b1, dark_start), min(b2, dark_end)), (max(b2, dark_start), dark_end)]
    return [(key, label, a, b) for (key, label), (a, b) in zip(SLOTS, bounds) if a < b]


def _visible_range(times, az, alt, min_alt: float) -> dict | None:
    """高度 min_alt 以上の最初と最後の時刻、いちばん高い時刻(その時刻の方位・高度)。一度も無ければ None。"""
    idx = [i for i, a in enumerate(alt) if a >= min_alt]
    if not idx:
        return None
    k = max(idx, key=lambda i: alt[i])
    return {"start": times[idx[0]], "end": times[idx[-1]], "peak_time": times[k],
            "peak_az": float(az[k]), "peak_alt": float(alt[k])}


def _transits_inside(alt) -> bool:
    """その時間帯の中で、いちばん高くなる時刻(南中)がある(端が最大なら、南中は時間帯の外)。"""
    k = max(range(len(alt)), key=lambda i: alt[i])
    return 0 < k < len(alt) - 1


def _planet_altaz(ts, eph, lat, lon, times):
    from skyfield.api import wgs84
    at = (eph["earth"] + wgs84.latlon(lat, lon, elevation_m=0.0)).at(_utc(ts, times))
    out = []
    for name, key in PLANETS:
        alt, az, _ = at.observe(eph[key]).apparent().altaz()
        out.append((name, az.degrees, alt.degrees))
    return out


def moonlit(ts, eph, lat, lon, times, phase_negligible_deg: float) -> list[bool]:
    """月が地平線の上にあり、新月に近くない時刻(explore の月の判定と同じ式)。"""
    from skyfield.api import wgs84
    at = (eph["earth"] + wgs84.latlon(lat, lon, elevation_m=0.0)).at(_utc(ts, times))
    moon = at.observe(eph["moon"]).apparent()
    alt = moon.altaz()[0].degrees
    phase = 180.0 - moon.separation_from(at.observe(eph["sun"]).apparent()).degrees
    return [bool(a > 0 and p < phase_negligible_deg) for a, p in zip(alt, phase)]


def slot_items(times, planets, targets, min_alt: float, moon_up: bool) -> list[dict]:
    """1つの時間帯の見どころ(最大 MAX_ITEMS_PER_SLOT 件)。planets: [(名前, 方位, 高度)]、targets: [(Target, 方位, 高度)]。"""
    items = []
    seen = []
    for name, az, alt in planets:
        r = _visible_range(times, az, alt, min_alt)
        if r is not None:
            seen.append({"name": name, "kind": "惑星", "faint_in_moonlight": False, **r})
    if seen:
        items.append({"type": "planets", "name": "惑星", "in_season": None, "has_first_magnitude": True, "members": seen})

    groups: dict[str, dict] = {}
    for order, (target, az, alt) in enumerate(targets):
        r = _visible_range(times, az, alt, min_alt)
        if r is None:
            continue
        label = target.group or target.name
        g = groups.setdefault(label, {"type": "target", "name": label, "in_season": False, "has_first_magnitude": False,
                                      "members": [], "_order": order})
        g["members"].append({"name": target.name, "kind": target.kind,
                             "faint_in_moonlight": moon_up and target.kind in FAINT_KINDS, **r})
        g["in_season"] = g["in_season"] or _transits_inside(alt)
        g["has_first_magnitude"] = g["has_first_magnitude"] or target.first_magnitude
    ordered = sorted(groups.values(), key=lambda g: ((not g["has_first_magnitude"]) if moon_up else False,
                                                     not g["in_season"], g["_order"]))
    for g in ordered:
        g.pop("_order")
    return (items + ordered)[:MAX_ITEMS_PER_SLOT]


def _next_visible(ex, ts, eph, lat, lon, night_date: date, hidden_targets, hidden_planets, min_alt: float) -> dict[str, int]:
    """名前 → 次に見える月(各月15日の暗い時間帯に、一度でも高度 min_alt 以上に出る最初の月)。12か月で見つからなければ入れない。"""
    from sky_engine import altaz_at_time
    found: dict[str, int] = {}
    y, m = night_date.year, night_date.month
    for _ in range(NEXT_VISIBLE_MONTHS):
        if len(found) == len(hidden_targets) + len(hidden_planets):
            break
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        start, end = ex.find_astro_dark_events(ts, eph, lat, lon, datetime(y, m, 15, tzinfo=JST))
        if start is None or end is None:
            continue
        times = _grid(start, end, 30)
        t = _utc(ts, times)
        for target in hidden_targets:
            if target.name not in found and max(altaz_at_time(t, eph, lat, lon, 0.0, target)[1]) >= min_alt:
                found[target.name] = m
        if hidden_planets:
            for name, _az, alt in _planet_altaz(ts, eph, lat, lon, times):
                if name in hidden_planets and name not in found and max(alt) >= min_alt:
                    found[name] = m
    return found


# ---------- 流星群 ----------

def load_showers(path: Path = SHOWERS_PATH) -> list[dict]:
    return json.loads(Path(path).read_text(encoding="utf-8"))["showers"]


def solar_longitude(ts, eph, dt: datetime) -> float:
    """太陽の黄経(度)。春分点は J2000(流星群の一覧で使われる黄経の決まりに合わせる。未照合)。"""
    t = ts.from_datetime(dt.astimezone(timezone.utc))
    return float(eph["earth"].at(t).observe(eph["sun"]).apparent().ecliptic_latlon()[1].degrees)


def _signed(deg: float) -> float:
    return (deg + 180.0) % 360.0 - 180.0


def shower_peak(ts, eph, lon_deg: float, start: datetime, days: float) -> datetime | None:
    """start から days 日のあいだ(300日まで)に、太陽の黄経が lon_deg になる時刻(二分法)。無ければ None。"""
    if days > 300:
        raise ValueError("days は300以下(黄経が1周する手前まで)")
    end = start + timedelta(days=days)
    ahead = (lon_deg - solar_longitude(ts, eph, start)) % 360.0      # 太陽の黄経は1日に約1°ずつ増える
    if ahead > (solar_longitude(ts, eph, end) - solar_longitude(ts, eph, start)) % 360.0:
        return None
    a, b = start, end
    while (b - a) > timedelta(seconds=30):
        mid = a + (b - a) / 2
        if _signed(solar_longitude(ts, eph, mid) - lon_deg) < 0:
            a = mid
        else:
            b = mid
    return a


def upcoming_showers(ex, ts, eph, lat, lon, now: datetime, days: int = METEOR_DAYS_AHEAD) -> list[dict]:
    """これから days 日以内に極大がある流星群(極大の早い順)。"""
    import winter_milkyway as wm
    from catalog import Target
    from sky_engine import altaz_at_time
    out = []
    for s in load_showers():
        peak = shower_peak(ts, eph, s["solar_longitude_deg"], now, days)
        if peak is None:
            continue
        # 極大の夜: 放射点が高く出ている時間帯が、極大の時刻にいちばん近い夜(放射点が高く出る夜が無ければ、暗い時間帯が近い夜)
        radiant = Target(id=s["id"], name=s["name"], name_en="", ra_hours=s["radiant_ra_deg"] / 15.0,
                         dec_deg=s["radiant_dec_deg"], best_season="", best_months=[])
        best = None
        for d in (peak.date() - timedelta(days=1), peak.date()):
            start, end = ex.find_astro_dark_events(ts, eph, lat, lon, datetime(d.year, d.month, d.day, tzinfo=JST))
            if start is None or end is None:
                continue
            times = _grid(start, end)
            az, alt = altaz_at_time(_utc(ts, times), eph, lat, lon, 0.0, radiant)
            r = _visible_range(times, az, alt, RADIANT_MIN_ALT_DEG)
            lo, hi = (r["start"], r["end"]) if r else (start, end)
            key = (r is None, max(timedelta(0), lo - peak, peak - hi))
            if best is None or key < best[0]:
                best = (key, d, start, end, r)
        rec = {"name": s["name"], "peak_time": peak, "zhr": s["zhr"], "source": s["source"], "caveat": METEOR_CAVEAT,
               "night_date": None, "radiant_start": None, "radiant_end": None, "moon_up_intervals": [],
               "moon_illuminated_fraction": None}
        if best is not None:
            _key, d, start, end, r = best
            mid = ex.compute_moon_position(ts, eph, lat, lon, 0.0, start + (end - start) / 2)
            rec.update(night_date=d, radiant_start=r["start"] if r else None, radiant_end=r["end"] if r else None,
                       moon_up_intervals=[{"start": a, "end": b} for a, b in wm.moon_up_intervals(ts, eph, lat, lon, start, end)],
                       moon_illuminated_fraction=(1.0 + math.cos(math.radians(mid.phase_angle_deg))) / 2.0)
        out.append(rec)
    out.sort(key=lambda r: r["peak_time"])
    return out


def build(ex, ts, eph, lat: float, lon: float, night_date: date, dark_start: datetime | None, dark_end: datetime | None,
          now: datetime, min_alt: float, winter_band: dict | None = None) -> dict:
    """見どころの値。ex は explore_hoshibiyori モジュール(天文薄明・月の計算を借りる)。"""
    import winter_milkyway as wm
    from catalog import load_targets
    from sky_engine import altaz_at_time
    out = {"night_date": night_date, "min_alt_deg": min_alt, "slots": [], "not_visible": [],
           "showers": upcoming_showers(ex, ts, eph, lat, lon, now), "winter_band": winter_band}
    if dark_start is None or dark_end is None:
        return out
    targets = load_targets()
    visible: set[str] = set()
    for key, label, start, end in night_slots(night_date, dark_start, dark_end):
        times = _grid(start, end)
        t = _utc(ts, times)
        planets = _planet_altaz(ts, eph, lat, lon, times)
        with_altaz = [(x, *altaz_at_time(t, eph, lat, lon, 0.0, x)) for x in targets]
        for name, _az, alt in planets:
            if max(alt) >= min_alt:
                visible.add(name)
        visible |= {x.name for x, _az, alt in with_altaz if max(alt) >= min_alt}
        moon_up = any(moonlit(ts, eph, lat, lon, times, ex.MOON_PHASE_NEGLIGIBLE_DEG))
        out["slots"].append({"key": key, "label": label, "start": start, "end": end, "moonlit": moon_up,
                             "moon_up_intervals": [{"start": a, "end": b}
                                                   for a, b in wm.moon_up_intervals(ts, eph, lat, lon, start, end)],
                             "items": slot_items(times, planets, with_altaz, min_alt, moon_up)})
    # 今夜は一度も見えない対象(組は、全部の対象が見えないときだけ組の名前で1つにまとめる)
    seen_groups = {x.group or x.name for x in targets if x.name in visible}
    hidden: dict[str, list] = {}
    for x in targets:
        if (x.group or x.name) not in seen_groups:
            hidden.setdefault(x.group or x.name, []).append(x)
    hidden_planets = [name for name, _ in PLANETS if name not in visible]
    nxt = _next_visible(ex, ts, eph, lat, lon, night_date, [x for g in hidden.values() for x in g], hidden_planets, min_alt)
    out["not_visible"] = [{"name": n, "next_month": nxt.get(n)} for n in hidden_planets]
    for label, members in hidden.items():
        # 組の「次に見える」は、組の代表(組と同じ名前の対象、無ければ先頭)の月
        rep = next((x for x in members if x.name == label), members[0])
        out["not_visible"].append({"name": label, "next_month": nxt.get(rep.name)})
    return out
