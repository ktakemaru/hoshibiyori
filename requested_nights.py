"""聞かれた夜(`explore_hoshibiyori.py --nights`)を、候補の上位N夜に入らなくても調べる。2026-11-24 追加。

- 今ある候補(finals / outlooks)には混ぜない。結果は `--json-out` の `requested_nights[]` と、画面の数行だけ。
- **通信を増やさない**: 雲量は、その回の通常の探索がすでに取ったセル(1セルで全部の日を含む)と、期限内の保存だけを読む
  (`FetchedOnlyCache`)。通常の探索が取らなかったセルの地点は「調べていない」(not_examined)にする。
- 判定は今ある段階と同じ閾値・同じ関数で行い、新しい閾値は作らない。スコアは出さない。
- 「調べていない」と「条件を通らなかった」を分ける。

このモジュールは explore_hoshibiyori を import しない(スクリプトとして実行されたときに2つ目の複製を作らないため、
呼び出し側がモジュールを `ex` として渡す)。
"""
from __future__ import annotations

import dataclasses
import math
from datetime import date, datetime

WINDOW_MOON_FREE = "moon_free"
WINDOW_DARK = "dark"
WINDOW_NONE = "none"

NONE_OUT_OF_SCAN = "out_of_scanned_range"              # 走査した夜(今日から14夜)の外
NONE_OUT_OF_FORECAST = "out_of_forecast_range"         # 基準地点の予報に、その時間帯の値が無い
NONE_NO_REFERENCE = "reference_forecast_not_fetched"   # 基準地点の予報をこの回に取っていない

REASON_CLOUD = "cloud_filter"
REASON_LIGHT = "light_pollution_filter"
REASON_DIRECTION = "direction_filter"
REASONS = (REASON_CLOUD, REASON_LIGHT, REASON_DIRECTION)

NOT_EXAMINED_NO_WINDOW = "no_window_at_site"           # 基準地点にはあるが、この地点には暗い時間帯・無月時間帯が無い
NOT_EXAMINED_NOT_FETCHED = "cell_not_fetched"          # この回の探索が、この地点のセルを取っていない
NOT_EXAMINED_FETCH_FAILED = "fetch_failed"
NOT_EXAMINED_NO_FORECAST = "no_forecast"               # セルはあるが、その時間帯の値が無い
NOT_EXAMINED = (NOT_EXAMINED_NO_WINDOW, NOT_EXAMINED_NOT_FETCHED, NOT_EXAMINED_FETCH_FAILED, NOT_EXAMINED_NO_FORECAST)

TRACK_INTERVAL_MIN = 15     # stage3_direction_filter と同じ刻み


class FetchedOnlyCache:
    """GridCloudCache の、この回に取ったセルと期限内の保存だけを読む(通信しない・集計を変えない・書かない)。"""

    def __init__(self, cache):
        self._cache = cache
        memo = getattr(cache, "_by_time_memo", None)
        if memo is None:
            memo = {}
        self._by_time_memo = memo
        # 保存から読んだセルは、この回のあいだ覚えておく(2026-11-27、処理時間の短縮)。以前は地点×夜ごとに同じファイルを
        # 読み直していたため、同じ時系列が毎回別のオブジェクトになり、時系列の変換の使い回し(_by_time_memo)が効かなかった
        self._disk_memo: dict = {}

    def get_hourly(self, lat, lon, model, forecast_days, variables):
        from grid_cache import grid_cell
        key = (model, grid_cell(lat, lon, model), forecast_days, variables)
        memory = getattr(self._cache, "_cache", {})
        if key in memory:
            return memory[key]
        if getattr(self._cache, "disk_cache_enabled", False):
            if key not in self._disk_memo:
                self._disk_memo[key] = self._cache._read_disk(key, model)
            return self._disk_memo[key]
        return None

    def has_cell(self, lat, lon) -> bool:
        return any(self.get_hourly(lat, lon, m, d, v) is not None for m, d, v in _cells())

    def failed_cell(self, lat, lon) -> bool:
        from grid_cache import grid_cell
        memory = getattr(self._cache, "_cache", {})
        return any(memory.get((m, grid_cell(lat, lon, m), d, v), True) is None for m, d, v in _cells())


def _cells():
    from cloud_forecast import ECMWF_MAX_FORECAST_DAYS, ECMWF_MODEL, MSM_MAX_FORECAST_DAYS, MSM_MODEL
    from elevation_cloud import level_hourly_vars
    v = level_hourly_vars()
    return ((MSM_MODEL, MSM_MAX_FORECAST_DAYS, v), (ECMWF_MODEL, ECMWF_MAX_FORECAST_DAYS, v))


def parse_nights(text: str) -> list[date]:
    """`2026-11-28,2026-11-29` を日付順・重複なしのリストにする。形が違えば ValueError。"""
    parts = [p.strip() for p in text.split(",") if p.strip()]
    if not parts:
        raise ValueError("日付がありません")
    return sorted({date.fromisoformat(p) for p in parts})


def _site_window(ex, ts, eph, site: dict, night_date: date, kind: str, astro):
    """その地点の調べる時間帯(開始, 終了)。無ければ (None, None)。"""
    if kind == WINDOW_MOON_FREE:
        start, end, _hours = ex.compute_site_night_window(ts, eph, site, night_date, astro)
        return start, end
    if astro is not None:
        cell = astro.cell_night(ts, eph, site["lat"], site["lon"], night_date)
        start, end = cell.dark_start, cell.dark_end
    else:
        start, end = ex.find_astro_dark_events(ts, eph, site["lat"], site["lon"],
                                               datetime(night_date.year, night_date.month, night_date.day, tzinfo=ex.JST))
    return (start, end) if start is not None and end is not None else (None, None)


def moon_info(ex, ts, eph, ref_site: dict, dark_start: datetime | None, dark_end: datetime | None) -> dict | None:
    """基準地点の暗い時間帯の月(出ている時間・出ている区間・輝面比)。15分刻み。"""
    if dark_start is None or dark_end is None:
        return None
    import winter_milkyway as wm
    intervals = wm.moon_up_intervals(ts, eph, ref_site["lat"], ref_site["lon"], dark_start, dark_end,
                                     ex.MOON_SAMPLE_INTERVAL_MIN)
    mid = ex.compute_moon_position(ts, eph, ref_site["lat"], ref_site["lon"], 0.0, dark_start + (dark_end - dark_start) / 2)
    return {
        "up_hours": sum((b - a).total_seconds() for a, b in intervals) / 3600.0,
        "up_intervals": [{"start": a, "end": b} for a, b in intervals],
        "illuminated_fraction": (1.0 + math.cos(math.radians(mid.phase_angle_deg))) / 2.0,
        "phase_angle_deg": float(mid.phase_angle_deg),
    }


def _track(ex, ts, eph, site, target, start: datetime, end: datetime):
    """対象天体の (方位, 高度) を15分刻みでまとめて計算する。時刻の列は同じ時間帯の地点で使い回す(2026-11-27、
    ex._sample_times。作り方は以前と同じ)。"""
    times, t_sf = ex._sample_times(ts, start, end, TRACK_INTERVAL_MIN)
    az, alt = ex.altaz_at_time(t_sf, eph, site["lat"], site["lon"], site["elevation_m"], target)
    return list(zip([float(a) for a in az], [float(a) for a in alt]))


def _direction_ok(ex, track, profile, best_only: bool) -> bool:
    """best_only: stage3 と同じ(最も高い点が地平線の上か)。偽なら、どこかの点が地平線の上か。地形データが無ければ 0°。"""
    points = [max(track, key=lambda p: p[1])] if best_only else track
    return any(alt > (ex.horizon_alt_at(profile, az) if profile is not None else 0.0) for az, alt in points)


def evaluate_site(ex, ts, eph, site: dict, night_date: date, kind: str, reader: FetchedOnlyCache, lp_store,
                  target_mode: str, astro, profiles: dict) -> dict:
    """1地点の結果。status は passed / failed / not_examined。"""
    primary = ex.is_primary_origin(site["origin"])
    rec = {"site_id": site.get("id"), "site_name": site["name"], "municipality": site["municipality"],
           "is_primary": primary, "group": "primary" if primary else "reference",
           "status": None, "reasons": [], "not_examined_reason": None,
           "window_start": None, "window_end": None,
           "clear_start": None, "clear_end": None, "clear_hours": None,
           "mean_obstruction": None, "mean_obstruction_window": None,
           "alr": None, "alr_rank_pct": None, "score": None, "night_rank": None}
    reading = lp_store.get(site["lat"], site["lon"])
    rec["alr"], rec["alr_rank_pct"] = reading.alr, reading.rank_pct
    reasons = []
    if reading.brightness_ratio > ex.LP_INDEX_LIMIT:
        reasons.append(REASON_LIGHT)

    start, end = _site_window(ex, ts, eph, site, night_date, kind, astro)
    not_examined = None
    if start is None:
        not_examined = NOT_EXAMINED_NO_WINDOW
    else:
        rec["window_start"], rec["window_end"] = start, end
        levels = ex.get_level_cloud_forecast(site["lat"], site["lon"], start, end, cache=reader)
        rows = ex.hourly_sky_obstruction_and_cloud_sea(levels, site["elevation_m"])
        valid = [r["sky_obstruction"] for r in rows if r["sky_obstruction"] is not None]
        clear_start = clear_end = None
        if valid:
            rec["mean_obstruction_window"] = sum(valid) / len(valid)
            clear_start, clear_end, mean = ex.find_longest_clear_window(rows, ex.CLOUD_OBSTRUCTION_THRESHOLD, start, end)
            if clear_start is None:
                rec["clear_hours"] = 0.0        # 1時間以上の晴れ間が無い
                reasons.append(REASON_CLOUD)
            else:
                rec["clear_start"], rec["clear_end"], rec["mean_obstruction"] = clear_start, clear_end, mean
                rec["clear_hours"] = (clear_end - clear_start).total_seconds() / 3600.0
        elif reader.failed_cell(site["lat"], site["lon"]):
            not_examined = NOT_EXAMINED_FETCH_FAILED
        elif not reader.has_cell(site["lat"], site["lon"]):
            not_examined = NOT_EXAMINED_NOT_FETCHED
        else:
            not_examined = NOT_EXAMINED_NO_FORECAST

        if target_mode != "stars" and REASON_LIGHT not in reasons:
            # 方角: まず時間帯の全体で一度も地平線の上に出なければ通らない。晴れ間があれば、stage3 と同じく晴れ間の中の
            # 最も高い時刻で判定する。光害で落ちた地点は見ない(結果が変わらず、計算が増えるだけのため)。
            profile = None
            if site["horizon_csv"]:
                if site["horizon_csv"] not in profiles:
                    profiles[site["horizon_csv"]] = ex.load_horizon_profile(site["horizon_csv"])
                profile = profiles[site["horizon_csv"]]
            target = ex.get_target(ex.TARGET_ID)
            if clear_start is not None:
                ok = _direction_ok(ex, _track(ex, ts, eph, site, target, clear_start, clear_end), profile, True)
            else:
                ok = _direction_ok(ex, _track(ex, ts, eph, site, target, start, end), profile, False)
            if not ok:
                reasons.append(REASON_DIRECTION)

    rec["reasons"] = [r for r in REASONS if r in reasons]
    if reasons:
        rec["status"] = "failed"
    elif not_examined is not None:
        rec["status"] = "not_examined"
    else:
        rec["status"] = "passed"
    rec["not_examined_reason"] = not_examined   # 光害・方角で落ちた地点でも、雲量を調べていなければ理由を残す
    return rec


def _profile(ex, site: dict, profiles: dict):
    if not site["horizon_csv"]:
        return None
    if site["horizon_csv"] not in profiles:
        profiles[site["horizon_csv"]] = ex.load_horizon_profile(site["horizon_csv"])
    return profiles[site["horizon_csv"]]


def assign_night_ranks(ex, ts, eph, records: list[dict], sites: list[dict], night_date: date, list_kind: str,
                       target_mode: str, astro, lp_store, profiles: dict) -> None:
    """status が passed の地点に night_rank(group ごとに1から)を付ける。ほかは None のまま。2026-11-27。

    決め方は候補の一覧と同じ: list_kind が "final" なら ex.final_rank_key、"outlook" なら ex.outlook_rank_key を、
    探索の候補と同じ項目(光害・月の影響が小さい時間・晴れ間・平均雲量、天の川モードはスコア)を持たせた値に当てて、
    explore_json.ranked_groups で並べる(並べ方・同じ値どうしの並びは finals・outlooks と同じ)。
    天の川モードのスコアは、finals なら晴れ間の中の最も高い時刻(ex.peak_altitude)と ex.final_score、outlooks なら
    調べた時間帯の見頃(ex.compute_target_window)と ex.outlook_score で、探索と同じ式。スコアは出さない(score は None のまま)。
    天の川モードでスコアが求まらない地点(見頃の区間が取れない)は、そのグループの最後に、地点の並びの順で付ける。"""
    from types import SimpleNamespace

    import explore_json as ej
    target = ex.get_target(ex.TARGET_ID) if target_mode != "stars" else None
    items, unranked = [], []
    for rec, site in zip(records, sites):
        if rec["status"] != "passed":
            continue
        reading = lp_store.get(site["lat"], site["lon"])
        _start, _end, moon_free_hours = ex.compute_site_night_window(ts, eph, site, night_date, astro)
        score = None
        if target is not None:
            profile = _profile(ex, site, profiles)
            if list_kind == "final":
                best_alt, best_az, best_time = ex.peak_altitude(ts, eph, site, target, rec["clear_start"], rec["clear_end"])
                if best_time is not None:
                    h_alt = ex.horizon_alt_at(profile, best_az) if profile is not None else None
                    score = ex.final_score(rec["mean_obstruction"], best_alt, h_alt, rec["clear_hours"],
                                           reading.brightness_ratio)
            else:
                _v0, _v1, _pt, peak_az, peak_alt = ex.compute_target_window(ts, eph, site, target, rec["window_start"],
                                                                           rec["window_end"], profile)
                if peak_az is not None:
                    score = ex.outlook_score(reading.brightness_ratio, peak_alt,
                                             ex.horizon_alt_at(profile, peak_az) if profile is not None else 0.0,
                                             moon_free_hours)
            if score is None:
                unranked.append((rec, site))
                continue
        items.append(SimpleNamespace(rec=rec, origin=site["origin"], alr=reading.alr, lp_index=reading.brightness_ratio,
                                     moon_free_hours=moon_free_hours, clear_hours=rec["clear_hours"],
                                     mean_obstruction=rec["mean_obstruction"], score=score))
    key_fn = ex.final_rank_key if list_kind == "final" else ex.outlook_rank_key
    last = {}
    for group, _primary, rank, item in ej.ranked_groups(items, lambda x: key_fn(x, target_mode), ex.is_primary_origin):
        item.rec["night_rank"] = rank
        last[group] = rank
    for rec, site in unranked:
        group = "primary" if ex.is_primary_origin(site["origin"]) else "reference"
        last[group] = last.get(group, 0) + 1
        rec["night_rank"] = last[group]


def _counts(records: list[dict]) -> dict:
    return {
        "total": len(records),
        "passed": sum(r["status"] == "passed" for r in records),
        "failed": sum(r["status"] == "failed" for r in records),
        "not_examined": sum(r["status"] == "not_examined" for r in records),
        "cloud_examined": sum(r["clear_hours"] is not None for r in records),
        "clear": sum((r["clear_hours"] or 0.0) > 0 for r in records),
        "failed_reasons": {k: sum(k in r["reasons"] for r in records) for k in REASONS},
        "not_examined_reasons": {k: sum(r["status"] == "not_examined" and r["not_examined_reason"] == k for r in records)
                                 for k in NOT_EXAMINED},
    }


def evaluate(ex, ts, eph, requested: list[date], scan: list, selected_dates: set, msm_dates: set, sites: list[dict],
             ref_site: dict, cache, lp_store, target_mode: str, astro) -> list[dict]:
    """指定した夜ごとの結果(日付順)。通信しない。"""
    reader = FetchedOnlyCache(cache)
    by_date = {n.night_date: (n, reason) for n, reason in scan}
    profiles: dict = {}
    out = []
    for d in requested:
        night, reason = by_date.get(d, (None, None))
        selected = d in selected_dates
        rec = {"night_date": d, "scanned": night is not None}
        for f in dataclasses.fields(ex.NightCandidate):
            if f.name != "night_date":
                rec[f.name] = getattr(night, f.name) if night is not None else None
        rec["selected"] = selected
        rec["regime"] = ("MSM" if d in msm_dates else "ECMWF") if selected else None
        rec["not_selected_reason"] = None if selected or night is None else (reason or ex.NOT_SELECTED_NOT_IN_TOP_N)
        rec["window_kind"], rec["none_reason"], rec["forecast_regime"] = WINDOW_NONE, None, None
        rec["moon"] = None
        rec["counts"], rec["sites"] = None, []
        out.append(rec)

        if night is None:
            rec["none_reason"] = NONE_OUT_OF_SCAN
            continue
        if night.dark_start is None or night.dark_end is None:
            rec["none_reason"] = reason
            continue
        rec["moon"] = moon_info(ex, ts, eph, ref_site, night.dark_start, night.dark_end)
        # 無月時間帯が最小の晴れ間(MIN_CLEAR_WINDOW_HOURS)より短い夜は、晴れていても必ず「雲で通らない」になって
        # しまうため、無月時間帯が無い夜と同じく暗い時間帯ぜんぶで調べる(月のことは moon と moon_free_hours で示す)
        usable = night.window_start is not None and (night.moon_free_hours or 0.0) >= ex.MIN_CLEAR_WINDOW_HOURS
        kind = WINDOW_MOON_FREE if usable else WINDOW_DARK
        eval_night = night if kind == WINDOW_MOON_FREE else dataclasses.replace(
            night, window_start=night.dark_start, window_end=night.dark_end)
        if not reader.has_cell(ref_site["lat"], ref_site["lon"]):
            rec["none_reason"] = NONE_NO_REFERENCE
            continue
        ref_levels = ex.get_level_cloud_forecast(ref_site["lat"], ref_site["lon"], eval_night.window_start,
                                                 eval_night.window_end, cache=reader)
        ref_rows = ex.hourly_sky_obstruction_and_cloud_sea(ref_levels, ref_site["elevation_m"])
        if all(r["sky_obstruction"] is None for r in ref_rows):
            rec["none_reason"] = NONE_OUT_OF_FORECAST
            continue
        rec["window_kind"] = kind
        rec["forecast_regime"] = ex.forecast_regime_for_night(reader, ref_site, eval_night)
        records = [evaluate_site(ex, ts, eph, s, d, kind, reader, lp_store, target_mode, astro, profiles) for s in sites]
        # その夜の中の順位(2026-11-27)。星空・星座モードは、どの夜も「光害(ALR)が小さい→月の影響が小さい時間が長い順」
        # (利用者の決定。outlooks と同じ決め方。MSM の夜の finals[晴れ時間が先]とは並びが違うことがある)。天の川モードは
        # スコア順で、スコアの式が2つあるため、予報が MSM の夜は finals、ECMWF の夜は outlooks の式(候補の夜は regime、
        # そうでない夜は forecast_regime で分ける。探索が夜を finals と outlooks に分けるのと同じ区分)
        regime = rec["regime"] if selected else rec["forecast_regime"]
        list_kind = "outlook" if target_mode == "stars" or regime != "MSM" else "final"
        assign_night_ranks(ex, ts, eph, records, sites, d, list_kind, target_mode, astro, lp_store, profiles)
        rec["counts"] = {"all": _counts(records),
                         "primary": _counts([r for r in records if r["is_primary"]]),
                         "reference": _counts([r for r in records if not r["is_primary"]])}
        # 地点が多いので、条件を通った地点は全部、通らなかった・調べていない地点は主軸だけを1件ずつ出す(残りは件数)
        rec["sites"] = [r for r in records if r["status"] == "passed" or r["is_primary"]]
    return out


_NONE_TEXT = {
    NONE_OUT_OF_SCAN: "調べていない(今日から14夜の外)",
    NONE_OUT_OF_FORECAST: "調べていない(予報の範囲の外)",
    NONE_NO_REFERENCE: "調べていない(基準地点の予報を取っていない)",
    "no_sunset_or_sunrise": "調べていない(日没・日の出が求まらない)",
    "no_astronomical_darkness": "調べていない(天文薄明の終わり・始まりが無い)",
}


def _moon_text(r: dict) -> str:
    moon = r["moon"]
    dark_hours = (r["dark_end"] - r["dark_start"]).total_seconds() / 3600.0
    up = f"{moon['up_hours']:.1f}"
    state = "月は出ていない" if up == "0.0" else f"月が出ているのは {up}時間"
    return f"その夜の月: 暗い時間帯 {dark_hours:.1f}時間のうち、{state}(輝面比 {moon['illuminated_fraction']:.0%})"


def summary_lines(records: list[dict]) -> list[str]:
    """画面のまとめ(--nights を付けたときだけ出す)。"""
    lines = ["", "[指定した夜](--nights。候補の一覧・順位とは別。雲量はこの回に取った分だけを使う)"]
    for r in records:
        if r["window_kind"] == WINDOW_NONE:
            lines.append(f"    {r['night_date']}  {_NONE_TEXT.get(r['none_reason'], '調べていない')}")
            continue
        a, p = r["counts"]["all"], r["counts"]["primary"]
        kind = "月の無い時間帯" if r["window_kind"] == WINDOW_MOON_FREE else "暗い時間帯ぜんぶ"
        lines.append(f"    {r['night_date']}  {kind}で調べた。予報は {r['forecast_regime']}。"
                     f"候補の上位の夜に{'入っている' if r['selected'] else '入っていない'}")
        # 月の情報は、何で調べたかとは別(どちらの場合も、その夜の暗い時間帯ぜんぶについての値)
        lines.append(f"      {_moon_text(r)}")
        lines.append(f"      条件を通った {a['passed']}/{a['total']}地点(主軸 {p['passed']}/{p['total']})"
                     f" / 1時間以上の晴れ間 {a['clear']}/{a['cloud_examined']}地点 / 調べていない {a['not_examined']}地点")
        f = a["failed_reasons"]
        lines.append(f"      通らなかった理由(重なりあり): 雲 {f[REASON_CLOUD]} / 光害 {f[REASON_LIGHT]} / 方角 {f[REASON_DIRECTION]}")
    return lines
