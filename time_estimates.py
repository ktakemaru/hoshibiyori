"""長い作業の時間の目安(実測だけ)と、探索・レポート生成の見積もり(通信しない・計算しない)。2026-11-24 追加。

- 時間の値はこのファイルの `ESTIMATES` だけに置く(出どころの日付つき)。AGENTS.md 第5節の表と食い違わないことを
  tests/test_wait_notice.py が確かめる。**実測の無い作業に数字を作らない**(sec=None、「未実測」)。
- 見積もりは、天文計算の保存と雲量の保存を、実際に読む関数(AstroNightCache・GridCloudCache._read_disk)を
  「計算しない・通信しない・書かない」設定で呼んで確かめる。
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

NOTICE_THRESHOLD_SEC = 30          # これ以上かかる見込みの作業の前に伝える(仮の値、AGENTS.md 第5節)
UNMEASURED = "未実測"
UNMEASURED_PHRASE = "まだ測っていません"


@dataclass(frozen=True)
class Estimate:
    key: str
    work: str            # 表の「作業」
    command: str         # 表の「コマンド」
    sec: float | None    # 実測の秒数(None = 未実測)
    text: str            # 表の「目安」
    source: str          # 表の「出どころ」


_USER_1115 = "2026-11-15、Windows・自宅回線、利用者の実測"
_EXPLORE = "`explore_hoshibiyori.py`"
_REPORT = "`generate_report.py`"
ESTIMATES: tuple[Estimate, ...] = (
    Estimate("explore/stars/cold", "探索・星空・星座モード・全897地点(保存が足りない)", f"{_EXPLORE} `--target stars`", 360.9,
             "約6分", _USER_1115 + "(360.9秒、通信あり・失敗0)"),
    Estimate("explore/stars/warm", "探索・星空・星座モード・全897地点(保存がそろっている)", f"{_EXPLORE} `--target stars`", 10.1,
             "約10秒", _USER_1115 + "(10.1秒、通信0回)"),
    Estimate("explore/stars/json", "探索・星空・星座モード・全897地点・JSON つき", f"{_EXPLORE} `--target stars --json-out …`", 300.0,
             "約5分", "2026-11-16、Windows・自宅回線、利用者の実測(通信617回)"),
    Estimate("explore/milkyway/cold", "探索・天の川モード・全897地点(保存が足りない)", _EXPLORE, None, UNMEASURED, "—"),
    Estimate("explore/milkyway/warm", "探索・天の川モード・全897地点(保存がそろっている)", _EXPLORE, None, UNMEASURED, "—"),
    Estimate("report/milkyway/cold", "レポートの生成・天の川モード・主軸146地点(保存が足りない)", _REPORT, None, UNMEASURED, "—"),
    Estimate("report/milkyway/warm", "レポートの生成・天の川モード・主軸146地点(雲量が保存済み)", _REPORT, 114.0,
             "約2分", _USER_1115 + "(1.9分、通信0回)"),
    Estimate("report/stars/cold", "レポートの生成・星空・星座モード・主軸146地点(保存が足りない)", f"{_REPORT} `--target stars`",
             None, UNMEASURED, "—"),
    Estimate("report/stars/warm", "レポートの生成・星空・星座モード・主軸146地点(雲量が保存済み)", f"{_REPORT} `--target stars`",
             None, UNMEASURED, "—"),
    Estimate("skyguide", "星空ガイド(数値JSON・描画)", "`scripts/make_sky_guide.py`・`scripts/render_sky_guide.py`", None, UNMEASURED, "—"),
    Estimate("courses", "コースの取り出し", "`scripts/report_courses.py`", None, UNMEASURED, "—"),
    Estimate("weekend", "週末ページ", "`scripts/weekend_page.py`", None, UNMEASURED, "—"),
    Estimate("weathermap", "天気図・ひまわりの取得", "`step5_cloud_forecast/jma_weather_map.py` ほか", None, UNMEASURED, "—"),
    Estimate("warm_astro", "薄明・月の時刻の先行計算", "`scripts/warm_astro_cache.py --days 30`", None, UNMEASURED, "—"),
    Estimate("tests", "単体テスト", "`py -X utf8 -m unittest discover -s tests`", 108.6,
             "約2分", "2026-11-24、Windows、Claude Code の中で実測(658件で108.6秒)"),
)
BY_KEY = {e.key: e for e in ESTIMATES}

KIND_LABEL = {"explore": "探索", "report": "レポートの生成"}
TARGET_LABEL = {"milkyway": "天の川モード", "stars": "星空・星座モード"}


def table_rows() -> list[str]:
    """AGENTS.md に置く表の行(見出しを除く)。"""
    return [f"| {e.work} | {e.command} | {e.text} | {e.source} |" for e in ESTIMATES]


def pick_time(kind: str, target: str, ready: bool) -> tuple[str, Estimate | None]:
    """(画面に出す目安, 使った実測)。実測の無い組み合わせは、同じコマンドの「同じ状態か、より長くかかる状態」の実測のうち
    長いほうで代用する。保存がそろっているときの短い実測を、足りないときの目安には使わない。"""
    states = ["warm", "cold"] if ready else ["cold"]
    exact = BY_KEY[f"{kind}/{target}/{states[0]}"]
    if exact.sec is not None:
        return exact.text, exact
    others = [e for e in ESTIMATES if e.key.startswith(kind + "/") and e.key.split("/")[2] in states and e.sec is not None]
    if not others:
        return UNMEASURED_PHRASE, None
    best = max(others, key=lambda e: e.sec)
    return f"{best.text}。この条件は未実測で、「{best.work}」の実測で代用", best


@dataclass
class CacheState:
    nights_total: int
    nights_ready: int
    cells_total: int
    cells_fresh: int

    @property
    def astro_ready(self) -> bool:
        return self.nights_total > 0 and self.nights_ready == self.nights_total

    @property
    def cloud_ready(self) -> bool:
        return self.cells_total > 0 and self.cells_fresh == self.cells_total

    @property
    def ready(self) -> bool:
        return self.astro_ready and self.cloud_ready


class _NotSaved(Exception):
    """保存に無く、計算が要る(見積もりでは計算しない)。"""


def _refuse(*_a, **_k):
    raise _NotSaved


def _read_only_astro(conditions: dict, cache_dir: Path | None):
    from astro_grid_cache import AstroNightCache

    class ReadOnly(AstroNightCache):
        def prune_old(self) -> int:
            return 0        # 見積もりでは古い夜のファイルも消さない

        def flush(self) -> int:
            return 0
    return ReadOnly(dark_fn=_refuse, moon_fn=_refuse, ref_fn=_refuse, conditions=conditions, cache_dir=cache_dir)


def astro_state(ex, kind: str, sites: list[dict], ref_site: dict, cache_dir: Path | None = None) -> tuple[int, int]:
    """(そろっている夜, 調べる夜)。夜がそろっている = 基準地点の夜と、雲量を調べる夜なら光害の足切りに残る地点のセルが
    全部保存されている(足切りで落ちる地点のセルは、見込みの夜では計算しないため数えない)。"""
    astro = _read_only_astro(ex.astro_conditions(), cache_dir)
    today = datetime.now(ex.JST).replace(hour=0, minute=0, second=0, microsecond=0)
    days = [today + timedelta(days=i) for i in range(ex.NUM_NIGHTS_TO_SCAN)]
    refs: dict = {}
    for day in days:
        try:
            refs[day] = astro.reference_night(None, None, ref_site["lat"], ref_site["lon"], day)
        except _NotSaved:
            pass
    with_window = [d for d in days if d in refs and refs[d]["window_start"] is not None]
    if kind == "explore" and len(refs) == len(days):
        # 候補の夜の選び方(stage1_moon_filter)と同じ: 無月時間帯の長い順に上位N夜。保存済みの値を並べるだけ
        with_window = sorted(with_window, key=lambda d: refs[d]["hours"], reverse=True)[:ex.NUM_CANDIDATE_NIGHTS]
    lp = ex.make_lp_store()
    cells = sorted({astro.cell_of(s["lat"], s["lon"]) for s in sites
                    if lp.get(s["lat"], s["lon"]).brightness_ratio <= ex.LP_INDEX_LIMIT})
    ready = 0
    for day in days:
        if day not in refs:
            continue
        if day in with_window:
            try:
                for lat, lon in cells:
                    astro.cell_night(None, None, lat, lon, day.date())
            except _NotSaved:
                continue
        ready += 1
    return ready, len(days)


def cloud_state(sites: list[dict], cache_dir: Path | None = None, stop_at_first_missing: bool = False) -> tuple[int, int]:
    """(期限内のセル, 全セル)。MSM と ECMWF のセルの合計。読む関数は GridCloudCache._read_disk(通信しない・フォルダも作らない)。"""
    from cloud_forecast import ECMWF_MAX_FORECAST_DAYS, ECMWF_MODEL, MSM_MAX_FORECAST_DAYS, MSM_MODEL
    from elevation_cloud import level_hourly_vars
    from grid_cache import grid_cell
    from skyguide.build import CacheOnlyCloudCache
    cache = CacheOnlyCloudCache(cache_dir)
    days = {MSM_MODEL: MSM_MAX_FORECAST_DAYS, ECMWF_MODEL: ECMWF_MAX_FORECAST_DAYS}
    variables = level_hourly_vars()
    cells = sorted({(m, grid_cell(s["lat"], s["lon"], m)) for s in sites for m in days})
    fresh = 0
    for model, (lat, lon) in cells:
        if cache.get_hourly(lat, lon, model, days[model], variables) is not None:
            fresh += 1
        elif stop_at_first_missing:
            break
    return fresh, len(cells)


def cache_state(ex, kind: str, sites: list[dict], ref_site: dict, *, astro_cache_dir: Path | None = None,
                cloud_cache_dir: Path | None = None, stop_at_first_missing: bool = False) -> CacheState:
    fresh, total = cloud_state(sites, cloud_cache_dir, stop_at_first_missing)
    if stop_at_first_missing and fresh < total:
        return CacheState(ex.NUM_NIGHTS_TO_SCAN, 0, total, fresh)   # もう「足りない」と決まったので、天文計算の保存は読まない
    ready, nights = astro_state(ex, kind, sites, ref_site, astro_cache_dir)
    return CacheState(nights, ready, total, fresh)


def _time_text(kind: str, target: str, state: CacheState) -> str:
    text, used = pick_time(kind, target, state.ready)
    if state.cloud_ready:
        return text
    return f"{text}・通信あり" if used is None else f"{text}(通信あり)"


def estimate_lines(kind: str, target: str, sites: list[dict], state: CacheState) -> list[str]:
    return [
        f"{KIND_LABEL[kind]}の見積もり: {TARGET_LABEL[target]} / {len(sites)} 地点",
        f"天文計算の保存: {state.nights_total} 夜のうち {state.nights_ready} 夜",
        f"雲量の保存: 期限内 {state.cells_fresh} セル / 全 {state.cells_total} セル",
        f"時間の目安: {_time_text(kind, target, state)}",
    ]


def start_notice(kind: str, target: str, sites: list[dict], state: CacheState) -> str:
    what = "星空の条件を調べます" if kind == "explore" else "星空の条件を調べてレポートを作ります"
    return f"{len(sites)} 地点の{what}(時間の目安: {_time_text(kind, target, state)})"


def print_start_notice(ex, kind: str, target: str, load_sites, astro_grid: str) -> None:
    """探索・レポート生成の始まりに標準エラーへ1行。見積もりに失敗しても本体は止めない。"""
    try:
        sites = load_sites()
        ref = next(s for s in sites if s["name"] == "石廊崎")
        state = cache_state(ex, kind, sites, ref, stop_at_first_missing=True, astro_cache_dir=ex.ASTRO_CACHE_DIR)
        if astro_grid == "site":        # 従来の地点ごとの計算は保存を読まない
            state.nights_ready = 0
        line = start_notice(kind, target, sites, state)
    except Exception:   # 予告だけの機能なので、どんな失敗でも本体の実行を続ける
        line = f"{KIND_LABEL[kind]}を始めます(時間の目安: {UNMEASURED_PHRASE})"
    print(line, file=sys.stderr, flush=True)
