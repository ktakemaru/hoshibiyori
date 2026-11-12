"""薄明・月の時刻を 0.25 度の格子の代表点で計算し、結果をディスクに保存して使い回す(2026-11-13、本人の決定)。

撮影者にとって薄明の時刻の分単位の精度より、実行の待ち時間のほうが重要、という本人の判断(案 C + 案 A)による。
2026-09-07 に入れた「地点ごとに薄明・無月時間帯を計算し直す」作りを改めるもの(`--astro-grid site` で従来の計算に戻せる)。

- 格子: `grid_cache.grid_cell(lat, lon, ECMWF_MODEL)`(0.25 度。ECMWF の予報と同じ切り方)。代表点はその戻り値の座標。
  格子の定義はここで持たない。
- 地点×夜 → セル×夜。同じセルの地点は同じ結果(薄明の開始・終了、無月時間帯の開始・終了・時間)を受け取る。
- 基準地点(第1段階の石廊崎)の夜(日没・日の出・薄明・無月時間帯)は、格子に丸めず、その地点の座標のまま同じ保存の仕組みに入れる
  (候補の夜の選び方を変えないため)。
- 保存: `<DATA_ROOT>/step1_astronomy/astro_cache/<条件の指紋>/night_YYYY-MM-DD.json`(1夜1ファイル、git 管理外)。
  ファイルの中にも計算の条件を持ち、条件が1つでも違えば使わない。有効期限は無く、読み込みのときに7日より前の夜の
  ファイルを消す(このキャッシュのフォルダの `night_*.json` に限る)。書き込みは一時ファイル→置き換え。壊れたファイルは無視して計算し直す。
- 日時はタイムゾーンつきの ISO 形式で保存する(読み直した値は計算した値と等しい)。

このモジュールは explore_hoshibiyori を import しない(循環を避けるため、計算の関数は呼び出し側から渡す)。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

_ROOT = Path(__file__).resolve().parent
for _sub in ("step5_cloud_forecast",):
    if str(_ROOT / _sub) not in sys.path:
        sys.path.insert(0, str(_ROOT / _sub))

from grid_cache import GRID_STEP_DEG, grid_cell  # noqa: E402
from cloud_forecast import ECMWF_MODEL  # noqa: E402
from hb_paths import DATA_ROOT  # noqa: E402

JST = timezone(timedelta(hours=9))

ASTRO_GRID_MODES = ("ecmwf", "site")
DEFAULT_ASTRO_GRID = "ecmwf"
FORMAT_VERSION = 1
KEEP_PAST_DAYS = 7  # 読み込みのときに、今日よりこの日数より前の夜のファイルを消す
SCHEMA = "hoshibiyori-astro-night-cache/1"

DEFAULT_CACHE_DIR = DATA_ROOT / "step1_astronomy" / "astro_cache"

_NIGHT_FILE_RE = re.compile(r"^night_(\d{4})-(\d{2})-(\d{2})\.json$")

# 計算の関数の型(呼び出し側の explore_hoshibiyori が渡す)。
#   dark_fn(ts, eph, lat, lon, day_start_local) -> (dark_start, dark_end)
#   moon_fn(ts, eph, lat, lon, dark_start, dark_end) -> (window_start, window_end, hours)
#   ref_fn(ts, eph, lat, lon, night_date) -> dict(sunset, sunrise, dark_start, dark_end, window_start, window_end, hours)


@dataclass(frozen=True)
class CellNight:
    """セル×夜の結果。dark_* は天文薄明の終了・開始(暗い区間)、window_* は無月時間帯。"""
    dark_start: datetime | None
    dark_end: datetime | None
    window_start: datetime | None
    window_end: datetime | None
    hours: float

    def window(self) -> tuple[datetime | None, datetime | None, float]:
        return self.window_start, self.window_end, self.hours


REF_FIELDS = ("sunset", "sunrise", "dark_start", "dark_end", "window_start", "window_end")


def _dt_to_str(v: datetime | None) -> str | None:
    if v is None:
        return None
    if v.tzinfo is None:
        raise ValueError("タイムゾーンの無い日時は保存しない")
    return v.isoformat()


def _str_to_dt(v: str | None) -> datetime | None:
    if v is None:
        return None
    d = datetime.fromisoformat(v)
    if d.tzinfo is None:
        raise ValueError("タイムゾーンの無い日時")
    return d


def _cell_key(lat: float, lon: float) -> str:
    return f"{lat!r},{lon!r}"


def conditions_fingerprint(conditions: dict) -> str:
    text = json.dumps(conditions, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def make_conditions(*, moon_phase_negligible_deg: float, sample_interval_min: int, ephemeris: str,
                    search_hours: int = 48) -> dict:
    """保存の鍵に入れる計算の条件。1つでも違えば保存済みを使わない。"""
    step = GRID_STEP_DEG[ECMWF_MODEL]
    return {
        "format_version": FORMAT_VERSION,
        "grid": {"model": ECMWF_MODEL, "lat_step": step["lat"], "lon_step": step["lon"]},
        "moon_phase_negligible_deg": float(moon_phase_negligible_deg),
        "sample_interval_min": int(sample_interval_min),
        "ephemeris": str(ephemeris),
        "search_hours": int(search_hours),
        "timezone": "+09:00",
    }


class AstroNightCache:
    """格子セル×夜の薄明・無月時間帯と、基準地点の夜を、計算して覚え、ディスクに保存する。

    `--astro-grid site` のときはこのクラスを作らない(呼び出し側が従来の地点ごとの計算を使う。保存は読まない・書かない)。
    """

    def __init__(self, *, dark_fn: Callable, moon_fn: Callable, ref_fn: Callable, conditions: dict,
                 cache_dir: Path | str | None = None, disk_cache: bool = True, today: date | None = None):
        self._dark_fn = dark_fn
        self._moon_fn = moon_fn
        self._ref_fn = ref_fn
        self.conditions = conditions
        self.cache_dir = Path(cache_dir) if cache_dir is not None else DEFAULT_CACHE_DIR
        self.disk_cache = disk_cache
        self.today = today if today is not None else datetime.now(JST).date()
        self.dir = self.cache_dir / f"v{FORMAT_VERSION}_{conditions_fingerprint(conditions)}"
        # 夜ごとの {"cells": {key: CellNight}, "ref": {key: dict}}
        self._nights: dict[date, dict] = {}
        self._loaded: set[date] = set()
        self._dirty: set[date] = set()
        self.computed = 0       # この実行で計算したセル×夜(基準地点の夜を含む)
        self.from_disk = 0      # 保存済みを使ったセル×夜(基準地点の夜を含む。1件につき1回だけ数える)
        self.lookups = 0        # 地点×夜の問い合わせの回数
        self._counted_disk: set[tuple] = set()
        self._from_disk_keys: set[tuple] = set()  # ディスクから読んだ項目の鍵
        self.pruned = 0
        self.ignored_files = 0
        if self.disk_cache:
            self.prune_old()

    # ---------- 問い合わせ ----------
    @staticmethod
    def cell_of(lat: float, lon: float) -> tuple[float, float]:
        return grid_cell(lat, lon, ECMWF_MODEL)

    def cell_night(self, ts, eph, lat: float, lon: float, night_date: date) -> CellNight:
        """地点(lat, lon)が属するセルの、その夜の結果。"""
        self.lookups += 1
        cell = self.cell_of(lat, lon)
        key = _cell_key(*cell)
        store = self._night(night_date)
        hit = store["cells"].get(key)
        if hit is not None:
            self._count_disk(("cell", night_date, key))
            return hit
        day_start_local = datetime(night_date.year, night_date.month, night_date.day, tzinfo=JST)
        dark_start, dark_end = self._dark_fn(ts, eph, cell[0], cell[1], day_start_local)
        if dark_start is None or dark_end is None:
            res = CellNight(dark_start, dark_end, None, None, 0.0)
        else:
            ws, we, hours = self._moon_fn(ts, eph, cell[0], cell[1], dark_start, dark_end)
            res = CellNight(dark_start, dark_end, ws, we, hours)
        store["cells"][key] = res
        self._dirty.add(night_date)
        self.computed += 1
        return res

    def site_night_window(self, ts, eph, site: dict, night_date: date) -> tuple[datetime | None, datetime | None, float]:
        """compute_site_night_window と同じ形の戻り値(無月時間帯の開始・終了・時間)。"""
        res = self.cell_night(ts, eph, site["lat"], site["lon"], night_date)
        if res.dark_start is None or res.dark_end is None:
            return None, None, 0.0
        return res.window()

    def reference_night(self, ts, eph, lat: float, lon: float, day_start_local: datetime) -> dict:
        """基準地点の夜(格子に丸めない)。戻り値は ref_fn と同じ dict。"""
        night_date = day_start_local.date()
        key = "ref:" + _cell_key(lat, lon)
        store = self._night(night_date)
        hit = store["ref"].get(key)
        if hit is not None:
            self._count_disk(("ref", night_date, key))
            return dict(hit)
        res = self._ref_fn(ts, eph, lat, lon, day_start_local)
        store["ref"][key] = dict(res)
        self._dirty.add(night_date)
        self.computed += 1
        return dict(res)

    def _count_disk(self, k: tuple) -> None:
        if k in self._from_disk_keys and k not in self._counted_disk:
            self._counted_disk.add(k)
            self.from_disk += 1

    # ---------- 読み書き ----------
    def _path(self, night_date: date) -> Path:
        return self.dir / f"night_{night_date.isoformat()}.json"

    def _night(self, night_date: date) -> dict:
        if night_date not in self._nights:
            self._nights[night_date] = {"cells": {}, "ref": {}}
        if self.disk_cache and night_date not in self._loaded:
            self._loaded.add(night_date)
            loaded = self._read(night_date)
            if loaded is not None:
                store = self._nights[night_date]
                for k, v in loaded["cells"].items():
                    if k not in store["cells"]:
                        store["cells"][k] = v
                        self._from_disk_keys.add(("cell", night_date, k))
                for k, v in loaded["ref"].items():
                    if k not in store["ref"]:
                        store["ref"][k] = v
                        self._from_disk_keys.add(("ref", night_date, k))
        return self._nights[night_date]

    def _read(self, night_date: date) -> dict | None:
        path = self._path(night_date)
        if not path.exists():
            return None
        try:
            with open(path, encoding="utf-8") as f:
                raw = json.load(f)
            if raw.get("schema") != SCHEMA or raw.get("conditions") != self.conditions:
                self.ignored_files += 1
                return None
            if raw.get("night_date") != night_date.isoformat():
                self.ignored_files += 1
                return None
            cells = {}
            for k, v in raw.get("cells", {}).items():
                cells[k] = CellNight(_str_to_dt(v["dark_start"]), _str_to_dt(v["dark_end"]),
                                     _str_to_dt(v["window_start"]), _str_to_dt(v["window_end"]), float(v["hours"]))
            refs = {}
            for k, v in raw.get("ref", {}).items():
                d = {f: _str_to_dt(v[f]) for f in REF_FIELDS}
                d["hours"] = float(v["hours"])
                refs[k] = d
            return {"cells": cells, "ref": refs}
        except (OSError, ValueError, KeyError, TypeError, AttributeError, json.JSONDecodeError):
            self.ignored_files += 1
            return None

    def flush(self) -> int:
        """計算して増えた夜のファイルを書き出す(一時ファイル→置き換え)。書いたファイルの数を返す。"""
        if not self.disk_cache:
            self._dirty.clear()
            return 0
        written = 0
        for night_date in sorted(self._dirty):
            store = self._nights[night_date]
            # 他の実行が同じ夜を書いていたら、それと合わせる(自分の値を優先)
            existing = self._read(night_date) or {"cells": {}, "ref": {}}
            cells = {**existing["cells"], **store["cells"]}
            refs = {**existing["ref"], **store["ref"]}
            payload = {
                "schema": SCHEMA,
                "conditions": self.conditions,
                "night_date": night_date.isoformat(),
                "cells": {k: {"dark_start": _dt_to_str(v.dark_start), "dark_end": _dt_to_str(v.dark_end),
                              "window_start": _dt_to_str(v.window_start), "window_end": _dt_to_str(v.window_end),
                              "hours": v.hours} for k, v in sorted(cells.items())},
                "ref": {k: {**{f: _dt_to_str(v[f]) for f in REF_FIELDS}, "hours": v["hours"]}
                        for k, v in sorted(refs.items())},
            }
            self.dir.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".tmp_night_", suffix=".json", dir=str(self.dir))
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                    json.dump(payload, f, ensure_ascii=False)
                os.replace(tmp, self._path(night_date))
            except BaseException:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
            written += 1
        self._dirty.clear()
        return written

    def prune_old(self) -> int:
        """今日より KEEP_PAST_DAYS 日より前の夜のファイルを消す(このキャッシュのフォルダの night_*.json に限る)。"""
        if not self.cache_dir.exists():
            return 0
        limit = self.today - timedelta(days=KEEP_PAST_DAYS)
        removed = 0
        for sub in self.cache_dir.iterdir():
            if not sub.is_dir() or not sub.name.startswith("v"):
                continue
            for p in sub.iterdir():
                m = _NIGHT_FILE_RE.match(p.name)
                if not m or not p.is_file():
                    continue
                try:
                    d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                except ValueError:
                    continue
                if d < limit:
                    try:
                        p.unlink()
                        removed += 1
                    except OSError:
                        pass
        self.pruned += removed
        return removed

    # ---------- 表示 ----------
    @staticmethod
    def count_cells(sites: list[dict]) -> int:
        return len({grid_cell(s["lat"], s["lon"], ECMWF_MODEL) for s in sites})

    def start_line(self, sites: list[dict]) -> str:
        return (f"[天文計算] 薄明・月の時刻は0.25度格子の代表点で計算"
                f"({len(sites)}地点 → {self.count_cells(sites)}セル)")

    def summary_line(self) -> str:
        return (f"天文計算のキャッシュ: 計算 {self.computed} 件 / 保存済みを使用 {self.from_disk} 件"
                f"(セル×夜と基準地点の夜)")
