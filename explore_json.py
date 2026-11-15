"""探索結果の JSON 出力(`explore_hoshibiyori.py --json-out`、スキーマ `hoshibiyori-explore/1`)。2026-11-16 追加。

ビヨリコンシェルなど、ほかのプログラムが探索結果を機械的に読めるようにするための出力。
組み立て(`build_explore_json`)は通信も天文計算もしない純粋な関数で、探索が作った候補・夜・取得の集計を受け取る。
探索の既定の動き(画面の出力・順位・終了コード)はこのモジュールでは変えない。

- 時刻は ISO 8601・オフセットつき。時差の情報を持たない datetime(探索では作られない)は推測で日本時間とせず null にする。
- 欠損・NaN・Infinity は null。数値は丸めない(画面の表示用の丸めは持ち込まない)。
- 候補は全件(画面の上位N件で切らない)。並びと順位は画面と同じ(主要候補→参考候補、それぞれ順位キーの降順)。
- 失敗セルの座標は入れない(件数と理由の種類だけ)。
"""
from __future__ import annotations

import dataclasses
import json
import math
import os
import subprocess
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable

SCHEMA = "hoshibiyori-explore/1"
JST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parent
PLUGIN_JSON = ROOT / ".claude-plugin" / "plugin.json"

NOTES = [
    "スコアは近日中(finals)と見込み(outlooks)で式が違い、絶対値を比べられません。",
    "光害の ALR は日本で未較正の相対指数です。lp_index は内部値で、表示用ではありません。",
    "outlooks の雲量は数値スコアに使っていません(clear_sky_pct は参考値)。",
]
# 星空・星座モード(--target stars)のときだけ NOTES の後ろに足す。このモードは score を順位に使わない(score は null で出す)。
STARS_NOTE = "星空・星座モードでは score を使いません(順位は rank を見てください)。"
# scanned_nights(走査した全部の夜)の注記。いつも NOTES の後ろ(STARS_NOTE の前)に足す。2026-11-16。
SCANNED_NOTE = "scanned_nights は走査した全部の夜です。selected が false の夜は、not_selected_reason の理由で候補から外れています。"


def scanned_night_records(scanned: Iterable, selected_dates: Iterable[date], msm_dates: Iterable[date]) -> list[dict]:
    """走査した全部の夜((NightCandidate, 理由のコード or None) の並び、日付順)を JSON の値にする。

    selected は「候補の夜(nights)に入ったか」で、nights の日付の集合から決める(並べ替えを繰り返さない)。
    regime は選ばれた夜だけ MSM / ECMWF、選ばれていない夜は null。not_selected_reason は選ばれた夜では null。
    理由が None なのに nights に入っていない夜は、上位N夜の切り捨て(not_in_top_n)として扱う。"""
    chosen = set(selected_dates)
    msm = set(msm_dates)
    out = []
    for n, reason in scanned:
        rec = dataclass_record(n)
        selected = n.night_date in chosen
        rec["selected"] = selected
        rec["regime"] = ("MSM" if n.night_date in msm else "ECMWF") if selected else None
        rec["not_selected_reason"] = None if selected else (reason or "not_in_top_n")
        out.append(rec)
    return out


def json_value(v):
    """JSON に入れる値へ変換する。datetime はオフセットつきの ISO 8601(naive は null)、date は YYYY-MM-DD、
    NaN・Infinity は null。それ以外の数値・文字列・真偽値・None はそのまま。"""
    if v is None or isinstance(v, (bool, str)):
        return v
    if isinstance(v, datetime):
        if v.tzinfo is None or v.utcoffset() is None:
            return None
        return v.isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, float):
        return v if math.isfinite(v) else None
    if isinstance(v, int):
        return v
    if isinstance(v, dict):
        return {str(k): json_value(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [json_value(x) for x in v]
    # numpy の数値など(float() にできるもの)
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    return f if math.isfinite(f) else None


def dataclass_record(obj) -> dict:
    """データクラスの全項目を、定義の順で JSON の値にする。"""
    return {f.name: json_value(getattr(obj, f.name)) for f in dataclasses.fields(obj)}


def ranked_records(items: Iterable, rank_key: Callable, is_primary: Callable[[str], bool], score_kind: str,
                   score_unused: bool = False) -> list[dict]:
    """画面(print_final_report / print_outlook_report)と同じ並び: 主要候補を順位キーの降順、続いて参考候補を同じく降順。
    順位(rank)は各グループの中で1から(画面の「[N位]」と同じ)。
    score_unused が真(星空・星座モード)なら score を null にする(並び・順位は変えない)。"""
    items = list(items)
    out: list[dict] = []
    for group, primary in (("primary", True), ("reference", False)):
        members = sorted((x for x in items if bool(is_primary(x.origin)) == primary), key=rank_key, reverse=True)
        for i, x in enumerate(members, 1):
            rec = dataclass_record(x)
            if score_unused:
                rec["score"] = None
            rec["score_kind"] = score_kind
            rec["is_primary"] = primary
            rec["group"] = group
            rec["rank"] = i
            out.append(rec)
    return out


def reason_kind(reason: str | None) -> str:
    """失敗の理由から種類だけを取り出す(本文・URL・座標を入れないため、最初の「:」より前だけを使う)。"""
    if not reason:
        return "unknown"
    return reason.split(":", 1)[0].strip() or "unknown"


def fetch_record(summary, failures: Iterable) -> dict:
    """grid_cache.FetchSummary と失敗セルの一覧から、取得の結果を作る(座標は入れない)。"""
    kinds: dict[str, int] = {}
    for f in failures:
        k = reason_kind(getattr(f, "reason", None))
        kinds[k] = kinds.get(k, 0) + 1
    return {
        "status": summary.status,
        "total_cells": summary.total_cells,
        "failed_cells": summary.failed,
        "failed_rate": json_value(float(summary.failed_rate)),
        "cache_hits": summary.cache_hits,
        "api_calls": summary.api_calls,
        "rate_limited": bool(summary.rate_limited),
        "retries": summary.retries,
        "failure_reasons": {k: kinds[k] for k in sorted(kinds)},
    }


def build_explore_json(*, generated_at: datetime, version: str | None, commit: str | None, dirty: bool | None,
                       target: str, astro_grid: str, thresholds: dict, reference_site: dict | None,
                       nights: list, msm_dates: Iterable[date], finals: list, outlooks: list,
                       final_rank_key: Callable, outlook_rank_key: Callable, is_primary: Callable[[str], bool],
                       fetch_summary, fetch_failures: Iterable, sites: dict,
                       scanned_nights: Iterable) -> dict:
    """探索結果の JSON(dict)を組み立てる。通信・天文計算・ファイルの読み書きはしない。

    final_rank_key / outlook_rank_key は1引数の関数(target を束ねたもの)。msm_dates は精密予報(MSM)側の夜の日付。
    scanned_nights(走査した全部の夜。stage1_moon_filter の scan_out)は必須(スキーマの required、2026-11-16)。
    None なら ValueError(集めていないのに「0夜」と書かないため)。キー scanned_nights は nights の直後に置き、
    注記 SCANNED_NOTE をいつも足す。
    """
    if scanned_nights is None:
        raise ValueError("scanned_nights は必須です(_explore を collect_scan=True で呼んでください)")
    msm_dates = list(msm_dates)
    msm = set(msm_dates)
    stars = target == "stars"
    night_records = []
    for n in nights:
        rec = dataclass_record(n)
        rec["regime"] = "MSM" if n.night_date in msm else "ECMWF"
        night_records.append(rec)
    ref = None
    if reference_site is not None:
        ref = {"name": reference_site.get("name"), "lat": json_value(reference_site.get("lat")),
               "lon": json_value(reference_site.get("lon"))}
    doc = {
        "schema": SCHEMA,
        "generated_at": json_value(generated_at),
        "version": version,
        "commit": commit,
        "dirty": dirty,
        "target": target,
        "astro_grid": astro_grid,
        "thresholds": {k: json_value(v) for k, v in thresholds.items()},
        "reference_site": ref,
        "sites": {k: json_value(v) for k, v in sites.items()},
        "nights": night_records,
        "scanned_nights": scanned_night_records(scanned_nights, [n.night_date for n in nights], msm_dates),
        "finals": ranked_records(finals, final_rank_key, is_primary, "final", score_unused=stars),
        "outlooks": ranked_records(outlooks, outlook_rank_key, is_primary, "outlook", score_unused=stars),
        "fetch": fetch_record(fetch_summary, fetch_failures),
        "notes": list(NOTES) + [SCANNED_NOTE] + ([STARS_NOTE] if stars else []),
    }
    return doc


def dumps(doc: dict) -> str:
    """決まった形の文字列にする(同じ入力なら同じ出力)。NaN・Infinity が残っていれば ValueError。"""
    return json.dumps(doc, ensure_ascii=False, indent=2, allow_nan=False) + "\n"


def write_json_atomic(path: str | Path, doc: dict) -> Path:
    """同じフォルダの一時ファイルに書いてから置き換える(途中で止まっても壊れた JSON を残さない)。
    親フォルダが無ければ作る。UTF-8(BOM なし)。"""
    path = Path(path)
    data = dumps(doc).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return path


def plugin_version(path: Path = PLUGIN_JSON) -> str | None:
    try:
        v = json.loads(Path(path).read_text(encoding="utf-8")).get("version")
    except (OSError, ValueError, AttributeError):
        return None
    return v if isinstance(v, str) else None


def git_state(root: Path = ROOT) -> tuple[str | None, bool | None]:
    """(commit, dirty)。git が無い・リポジトリでないなら (None, None)。シェルを介さず引数の配列で呼ぶ。
    dirty は追跡しているファイルの変更の有無(追跡していないファイルは数えない)。"""
    try:
        r = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return None, None
    commit = r.stdout.strip() if r.returncode == 0 else ""
    if not commit:
        return None, None
    try:
        s = subprocess.run(["git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return commit, None
    dirty = bool(s.stdout.strip()) if s.returncode == 0 else None
    return commit, dirty
