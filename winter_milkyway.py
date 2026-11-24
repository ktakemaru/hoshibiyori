"""冬の天の川の帯(カシオペヤ〜ぎょしゃ〜オリオン〜おおいぬ)の、夜ごとの見え方。2026-11-24 追加。

- 銀河座標の経度 120〜220°・緯度 0° を 10° ごとの点で代表し、基準地点の暗い時間帯のあいだ 30 分ごとに高度を計算する。
- 地点ごとには計算しない(帯の高度は関東〜中部の範囲ではほとんど変わらないため)。平らな地平線の目安で、地形・雲は見ない。
- 候補の選び方・順位・スコアには使わない(情報を足すだけ)。
- 銀河座標→赤道座標は skyguide.astro.galactic_to_radec、高度・方位は sky_engine.altaz_at_time(銀河中心と同じ計算)。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

BAND_L_DEG = tuple(range(120, 221, 10))     # 帯を代表する銀経(度)
HIGH_ALT_DEG = 20.0                         # これ以上を「高く出ている」とする(仮の値)
HIGH_FRACTION = 0.5                         # 帯の点のうち、この割合以上が高く出ている時間帯を採る(指示書「半分以上」)
SAMPLE_MIN = 30
DISPLAY_STEP_MIN = 30                       # 画面・レポートの時刻の刻み(分)
_ZENITH_ALT_DEG = 80.0                      # これ以上は方角でなく「ほぼ天頂」と書く(generate_report.render_sky_guide と同じ)


def _band_targets():
    from catalog import Target
    from skyguide.astro import galactic_to_radec
    out = []
    for l_deg in BAND_L_DEG:
        ra, dec = galactic_to_radec(l_deg, 0.0)
        out.append(Target(id=f"gal_l{l_deg}", name=f"銀経{l_deg}°", name_en="", ra_hours=ra, dec_deg=dec,
                          best_season="", best_months=[]))
    return out


def _sample_times(start: datetime, end: datetime) -> list[datetime]:
    times, t = [], start
    while t <= end:
        times.append(t)
        t += timedelta(minutes=SAMPLE_MIN)
    return times


def band_altitudes(ts, eph, lat: float, lon: float, times: list[datetime]) -> list[list[tuple[float, float]]]:
    """時刻ごとの、帯の各点の (方位, 高度)。"""
    from sky_engine import altaz_at_time
    t = ts.from_datetimes([x.astimezone(timezone.utc) for x in times])
    per_point = [altaz_at_time(t, eph, lat, lon, 0.0, target) for target in _band_targets()]
    return [[(float(az[i]), float(alt[i])) for az, alt in per_point] for i in range(len(times))]


def summarize(times: list[datetime], altaz: list[list[tuple[float, float]]]) -> dict:
    """高く出ている時間帯(いちばん長い連続)と、帯の平均の高度が最大になる時刻・そのときの帯のいちばん高い点。

    高く出ている時間帯が無い夜は全部 None(「今夜は見えない」)。"""
    none = {"high_start": None, "high_end": None, "peak_time": None, "peak_point_alt_deg": None,
            "peak_point_az_deg": None, "peak_mean_alt_deg": None}
    flags = [sum(alt >= HIGH_ALT_DEG for _, alt in pts) >= HIGH_FRACTION * len(pts) for pts in altaz]
    best, start = None, None
    for i, f in enumerate(flags + [False]):
        if f and start is None:
            start = i
        elif not f and start is not None:
            if best is None or (i - 1 - start) > (best[1] - best[0]):
                best = (start, i - 1)
            start = None
    if best is None:
        return none
    k = max(range(best[0], best[1] + 1), key=lambda i: sum(alt for _, alt in altaz[i]))
    top_az, top_alt = max(altaz[k], key=lambda p: p[1])
    return {"high_start": times[best[0]], "high_end": times[best[1]], "peak_time": times[k],
            "peak_point_alt_deg": top_alt, "peak_point_az_deg": top_az,
            "peak_mean_alt_deg": sum(alt for _, alt in altaz[k]) / len(altaz[k])}


def moon_up_intervals(ts, eph, lat: float, lon: float, start: datetime, end: datetime,
                      step_min: int = 15) -> list[tuple[datetime, datetime]]:
    """月が地平線の上にある区間(step4_moonlight.moon_position と同じ計算を時刻の配列でまとめて)。"""
    from skyfield.api import wgs84
    times, t = [], start
    while t <= end:
        times.append(t)
        t += timedelta(minutes=step_min)
    observer = eph["earth"] + wgs84.latlon(lat, lon, elevation_m=0.0)
    at = observer.at(ts.from_datetimes([x.astimezone(timezone.utc) for x in times]))
    alts = at.observe(eph["moon"]).apparent().altaz()[0].degrees
    out, begin = [], None
    for x, alt in zip(times, alts):
        if alt > 0 and begin is None:
            begin = x
        elif alt <= 0 and begin is not None:
            out.append((begin, x))
            begin = None
    if begin is not None:
        out.append((begin, end))
    return out


def night_band(ts, eph, lat: float, lon: float, dark_start: datetime | None, dark_end: datetime | None) -> dict | None:
    """1夜分。暗い時間帯が無い夜は None。"""
    if dark_start is None or dark_end is None:
        return None
    times = _sample_times(dark_start, dark_end)
    out = summarize(times, band_altitudes(ts, eph, lat, lon, times))
    out["moon_up_intervals"] = [{"start": a, "end": b}
                                for a, b in moon_up_intervals(ts, eph, lat, lon, dark_start, dark_end)]
    return out


def _hm(dt: datetime, base) -> str:
    r = dt.replace(second=0, microsecond=0)
    r = r - timedelta(minutes=r.minute % 30) + timedelta(minutes=30 if r.minute % 30 >= 15 else 0)
    return f"{'翌' if r.date() != base else ''}{r:%H:%M}"


def is_displayable(start: datetime, end: datetime, shown_start, shown_end) -> bool:
    """表示の刻み(30分)以上あり、丸めた始まりと終わりが違う区間か(月・見どころの対象で共通の決まり)。"""
    return end - start >= timedelta(minutes=DISPLAY_STEP_MIN) and shown_start != shown_end


def shown_moon_intervals(intervals: list[dict], base, fmt=_hm) -> list[str]:
    """月が出ている区間の文。表示の刻み(30分)より短い区間と、丸めると始まりと終わりが同じになる区間は出さない
    (値のほう[moon_up_intervals]は変えない)。fmt は時刻の書き方。"""
    out = []
    for m in intervals:
        start, end = fmt(m["start"], base), fmt(m["end"], base)
        if is_displayable(m["start"], m["end"], start, end):
            out.append(f"{start}〜{end}")
    return out


def _compass(az: float) -> str:
    names = ["北", "北北東", "北東", "東北東", "東", "東南東", "南東", "南南東",
             "南", "南南西", "南西", "西南西", "西", "西北西", "北西", "北北西"]
    return names[round(az / 22.5) % 16]


def band_text(night_date, band: dict | None) -> str:
    """画面・レポートの1行(時刻は30分単位に丸める)。"""
    if band is None or band["high_start"] is None:
        return "冬の天の川の帯: この夜は高く出ません"
    where = ("ほぼ天頂" if band["peak_point_alt_deg"] >= _ZENITH_ALT_DEG
             else f"{_compass(band['peak_point_az_deg'])}の高度{band['peak_point_alt_deg']:.0f}°")
    moon = shown_moon_intervals(band["moon_up_intervals"], night_date)
    moon_text = "月は出ていない" if not moon else "月は" + "・".join(moon) + "に出ている"
    return (f"冬の天の川の帯: {_hm(band['high_start'], night_date)}〜{_hm(band['high_end'], night_date)}に高く、"
            f"{_hm(band['peak_time'], night_date)}ごろ最も高い(帯のいちばん高い所は{where})。{moon_text}")
