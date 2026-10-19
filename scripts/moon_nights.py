"""月の条件だけで夜を絞る(通信しない)。「月で時期を絞る → 雲量で場所を絞る → 星空ガイド」の最初の段。

使い方:
    py -X utf8 scripts\\moon_nights.py                       # 今日から14夜(探索と同じ NUM_NIGHTS_TO_SCAN)、基準は石廊崎(レポートの概況と同じ)
    py -X utf8 scripts\\moon_nights.py --days 30
    py -X utf8 scripts\\moon_nights.py --spot 戦場ヶ原       # その地点の座標で計算(stargazing_spots.json の name または id)
    py -X utf8 scripts\\moon_nights.py --start-date 2026-11-01 --days 14
    py -X utf8 scripts\\moon_nights.py --json-out out\\moon_nights.json

月の影響が小さい時間帯は、探索と同じ explore_hoshibiyori.longest_negligible_window(天文薄明の暗い時間帯のうち、
月が地平線の下、または月相角が MOON_PHASE_NEGLIGIBLE_DEG 以上の最長区間)。閾値はここでは再定義しない。
雲量は予報の取得(通信)が要るため扱わない。天文暦 step1_astronomy/de421.bsp が無いときは自動ダウンロードせず終了する
(--allow-network を付けたときだけダウンロードを許可。ダウンロードは通信なので、事前に承認を得ること)。
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
for _sub in ["step1_astronomy", "step2_terrain", "step3_light_pollution", "step4_moonlight", "step5_cloud_forecast"]:
    sys.path.insert(0, str(ROOT / _sub))


import explore_hoshibiyori as ex  # noqa: E402
from hb_paths import DATA_ROOT, ephemeris_load as load  # noqa: E402

JST = timezone(timedelta(hours=9))
EPHEMERIS_PATH = DATA_ROOT / "step1_astronomy" / "de421.bsp"
SCHEMA = "hoshibiyori-moon-nights/1"
DEFAULT_REF_SPOT = "石廊崎"  # generate_report.py の概況タイムラインの基準地点
DEFAULT_TOP = 5
WEEKDAYS = "月火水木金土日"
NOTE = ("月の条件のみ。雲量は未評価(予報の取得が要るため)。雲量で場所を絞るには generate_report.py の探索を実行する"
        "(AGENTS.md 第5節、実行前に承認)。")


class MoonNightsError(Exception):
    pass


@dataclass
class NightRow:
    night_date: date
    moon_icon: str
    moon_phase_deg: float  # 0=新月〜360(黄経差。generate_report.moon_phase_deg と同じ)
    dark_start: datetime | None
    dark_end: datetime | None
    window_start: datetime | None
    window_end: datetime | None
    moon_free_hours: float
    moonrise: datetime | None = None  # その夜(日没〜日の出)の間の月の出・月の入り
    moonset: datetime | None = None

    @property
    def illum(self) -> float:
        """おおよその輝面比(0〜1)。夜の中央時刻の月相から。"""
        return (1.0 - math.cos(math.radians(self.moon_phase_deg))) / 2.0


# ---- 純粋な関数(暦なしでテストできる) ----

def weekday_ja(d: date) -> str:
    return WEEKDAYS[d.weekday()]


def fmt_date(d: date) -> str:
    return f"{d.month:02d}/{d.day:02d}({weekday_ja(d)})"


def fmt_range(start: datetime | None, end: datetime | None, base: date) -> str:
    """HH:MM〜HH:MM。終了が基準日の翌日以降なら (翌) を付ける。"""
    if start is None or end is None:
        return "なし"
    def one(dt: datetime) -> str:
        return dt.strftime("%H:%M") + ("(翌)" if dt.date() > base else "")
    return f"{one(start)}〜{one(end)}"


def fmt_event(dt: datetime | None, base: date) -> str:
    if dt is None:
        return "-"
    return dt.strftime("%H:%M") + ("(翌)" if dt.date() > base else "")


def top_rows(rows: list[NightRow], n: int = DEFAULT_TOP) -> list[NightRow]:
    """月の影響が小さい時間帯が長い順(同じ長さなら日付順)の上位n夜。時間帯が無い夜は含めない。"""
    withwin = [r for r in rows if r.window_start is not None]
    return sorted(withwin, key=lambda r: r.moon_free_hours, reverse=True)[:n]


def format_table(rows: list[NightRow], ref_label: str, top: int = DEFAULT_TOP) -> str:
    lines = [f"月の条件で見た夜の一覧(基準: {ref_label})", NOTE, ""]
    header = ["日付", "月相", "輝面", "暗い時間帯", "月の影響が小さい時間帯", "長さ", "月の出", "月の入り"]
    table = [header]
    for r in rows:
        table.append([
            fmt_date(r.night_date), r.moon_icon, f"{r.illum * 100:.0f}%",
            fmt_range(r.dark_start, r.dark_end, r.night_date),
            fmt_range(r.window_start, r.window_end, r.night_date),
            f"{r.moon_free_hours:.1f}時間",
            fmt_event(r.moonrise, r.night_date), fmt_event(r.moonset, r.night_date),
        ])
    widths = [max(_w(row[i]) for row in table) for i in range(len(header))]
    for k, row in enumerate(table):
        lines.append("  ".join(_pad(c, widths[i]) for i, c in enumerate(row)).rstrip())
        if k == 0:
            lines.append("  ".join("-" * widths[i] for i in range(len(header))))
    best = top_rows(rows, top)
    lines += ["", f"月の影響が小さい時間帯が長い順(上位{len(best)}夜)"]
    for i, r in enumerate(best, 1):
        lines.append(f"  {i}. {fmt_date(r.night_date)} {r.moon_free_hours:.1f}時間 "
                     f"{fmt_range(r.window_start, r.window_end, r.night_date)}")
    if not best:
        lines.append("  (該当なし)")
    lines += ["", NOTE]
    return "\n".join(lines)


def _w(s: str) -> int:
    """表示幅(全角=2、絵文字=2)。"""
    import unicodedata
    return sum(2 if unicodedata.east_asian_width(c) in "WF" or ord(c) >= 0x1F300 else 1 for c in s)


def _pad(s: str, width: int) -> str:
    return s + " " * (width - _w(s))


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat(timespec="minutes") if dt else None


def to_json(rows: list[NightRow], ref: dict, start_date: date, days: int, top: int = DEFAULT_TOP) -> dict:
    return {
        "schema": SCHEMA,
        "reference": ref,
        "start_date": start_date.isoformat(),
        "days": days,
        "cloud": "not_evaluated",
        "note": NOTE,
        "nights": [{
            "date": r.night_date.isoformat(), "weekday": weekday_ja(r.night_date), "moon_icon": r.moon_icon,
            "moon_phase_deg": round(r.moon_phase_deg, 1), "illum": round(r.illum, 2),
            "dark_start": _iso(r.dark_start), "dark_end": _iso(r.dark_end),
            "window_start": _iso(r.window_start), "window_end": _iso(r.window_end),
            "moon_free_hours": round(r.moon_free_hours, 2),
            "moonrise": _iso(r.moonrise), "moonset": _iso(r.moonset),
        } for r in rows],
        "top": [r.night_date.isoformat() for r in top_rows(rows, top)],
    }


# ---- 暦が要る計算 ----

def compute_rows(ts, eph, lat: float, lon: float, start_date: date, days: int) -> list[NightRow]:
    """start_date から days 夜。explore_hoshibiyori.all_nights_timeline と同じ下位関数を同じ順で呼ぶ(あちらは今日固定のため)。"""
    import generate_report as gr
    from galactic_center import Location, moon_rise_set

    rows: list[NightRow] = []
    loc = Location("基準", lat, lon, 0.0)
    for i in range(days):
        day = datetime(start_date.year, start_date.month, start_date.day, tzinfo=JST) + timedelta(days=i)
        sunset, sunrise = ex.find_sun_events(ts, eph, lat, lon, day)
        if sunset is None or sunrise is None:
            continue
        dark_start, dark_end = ex.find_astro_dark_events(ts, eph, lat, lon, day)
        if dark_start is not None and dark_end is not None:
            w_start, w_end, hours = ex.longest_negligible_window(ts, eph, lat, lon, dark_start, dark_end)
        else:
            w_start, w_end, hours = None, None, 0.0
        mid = sunset + (sunrise - sunset) / 2
        phase = gr.moon_phase_deg(ts, eph, mid)
        rises, sets = [], []
        for d in (day, day + timedelta(days=1)):
            r, s = moon_rise_set(ts, eph, loc, d)
            rises.append(r)
            sets.append(s)
        in_night = lambda t: t is not None and sunset <= t <= sunrise  # noqa: E731
        rows.append(NightRow(
            night_date=day.date(), moon_icon=gr.moon_icon_for(phase), moon_phase_deg=phase,
            dark_start=dark_start, dark_end=dark_end, window_start=w_start, window_end=w_end, moon_free_hours=hours,
            moonrise=next((t for t in rises if in_night(t)), None), moonset=next((t for t in sets if in_night(t)), None),
        ))
    return rows


def resolve_reference(spot_key: str | None) -> dict:
    """基準地点。既定は generate_report.py と同じ(curated由来の地点から石廊崎)。--spot は stargazing_spots.json の name または id。"""
    if spot_key is None:
        sites = [s for s in ex.load_candidate_sites() if ex.is_primary_origin(s["origin"])]
        hits = [s for s in sites if s["name"] == DEFAULT_REF_SPOT]
        if not hits:
            raise MoonNightsError(f"基準地点 {DEFAULT_REF_SPOT} が候補地点にありません")
        return {"name": hits[0]["name"], "lat": hits[0]["lat"], "lon": hits[0]["lon"], "kind": "default"}
    spots = json.loads(ex.STARGAZING_SPOTS_PATH.read_text(encoding="utf-8"))["spots"]
    hits = [s for s in spots if s.get("id") == spot_key or s.get("name") == spot_key]
    if not hits:
        raise MoonNightsError(f"stargazing_spots.json に地点がありません: {spot_key}(推測で置き換えません。表記を確認してください)")
    if len(hits) > 1:
        raise MoonNightsError(f"地点名が複数あります。id で指定してください: {[h['id'] for h in hits]}")
    return {"name": hits[0]["name"], "lat": hits[0]["lat"], "lon": hits[0]["lon"], "kind": "spot"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=ex.NUM_NIGHTS_TO_SCAN, help=f"夜の数(既定 {ex.NUM_NIGHTS_TO_SCAN})")
    ap.add_argument("--start-date", help="最初の夜の開始日 YYYY-MM-DD(既定は今日)")
    ap.add_argument("--spot", help="stargazing_spots.json の地点名またはid(既定は石廊崎=レポートの概況と同じ基準)")
    ap.add_argument("--top", type=int, default=DEFAULT_TOP, help=f"無月時間帯が長い夜の上位N(既定 {DEFAULT_TOP})")
    ap.add_argument("--json-out", help=f"同じ内容を JSON({SCHEMA})で書き出す")
    ap.add_argument("--allow-network", action="store_true", help="暦ファイルが無いときの自動ダウンロード(通信)を許可する。承認を得てから")
    a = ap.parse_args(argv)
    try:
        if a.days < 1:
            raise MoonNightsError("--days は1以上にしてください")
        try:
            start = date.fromisoformat(a.start_date) if a.start_date else datetime.now(JST).date()
        except ValueError:
            raise MoonNightsError(f"--start-date は YYYY-MM-DD で指定してください: {a.start_date}")
        ref = resolve_reference(a.spot)
        if not EPHEMERIS_PATH.exists() and not a.allow_network:
            raise MoonNightsError("天文暦 step1_astronomy/de421.bsp がありません(初回は自動ダウンロード=通信が必要なため、ここでは行いません)。"
                                  "--allow-network を付けるか、先に用意してください(通信の前に承認を得ること)")
        ts = load.timescale()
        eph = load(str(EPHEMERIS_PATH))
        rows = compute_rows(ts, eph, ref["lat"], ref["lon"], start, a.days)
    except MoonNightsError as e:
        print(f"[エラー] {e}", file=sys.stderr)
        return 1
    label = f"{ref['name']}(北緯{ref['lat']:.3f}°・東経{ref['lon']:.3f}°)、{start.isoformat()} から{a.days}夜"
    print(format_table(rows, label, a.top))
    if a.json_out:
        out = Path(a.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(to_json(rows, ref, start, a.days, a.top), ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\nJSON: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
