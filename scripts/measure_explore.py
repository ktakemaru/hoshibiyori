"""探索(explore_hoshibiyori.py)の実行時間を測る計測用スクリプト(2026-11-12、通信以外の処理時間の短縮のため)。

利用者向けの既定の動き(explore_hoshibiyori.py・generate_report.py)は変えない。このスクリプトの中だけで、
雲量のディスクキャッシュの置き場を差し替えて explore の main() を呼ぶ。

    # 実行(画面の出力・秒数のJSON・(--profile なら)プロファイルを --out-dir に保存)
    py -X utf8 scripts/measure_explore.py run --cache-dir <フォルダ> --out-dir <フォルダ> --label <名前>
        [--frozen] [--primary-only] [--profile] [--target stars|milkyway] [--code-root <フォルダ>]

    # 2つの画面の出力が「同じ」か比べる(下の除外規則の行を除いて1文字も違わなければ同じ、終了コード0)
    py -X utf8 scripts/measure_explore.py compare <A.log> <B.log>

- --cache-dir : 雲量のディスクキャッシュの置き場(リポジトリ既定の cloud_cache は使わない)。空のフォルダなら通常どおり取得して書く。
- --frozen    : そのフォルダのキャッシュを有効期限を無視して読む。キャッシュに無いセルは通信せず欠測(取得失敗の扱い)にする。
                通信は0回(requests.Session.get も止める)。
- --primary-only : 主要候補(curated系の origin)だけで実行する(速い確かめ用)。
- --profile   : cProfile をかけ、累積時間の上位40件を <label>.profile.txt に、生データを <label>.prof に出す。
- --code-root : explore_hoshibiyori.py を読むリポジトリ(既定はこのスクリプトの親)。変更前のコードの写しを測るのに使う。
- --max-minutes : この分数を超えたら出力を書き出して強制終了する(既定60分、終了コード9)。
- 画面の出力のほかに、第2段階・第3段階・見込みの戻り値の全件(上位N件で切らない)を <label>.results.txt に書く。
  compare は両方の .results.txt があればそれも比べる。また2つの <label>.json の開始日(JST)が違えば「比べられない」とする。

「同じ」の判定で除く行(COMPARE_EXCLUDE): 秒数・分・実行日時・API呼び出しとキャッシュヒットの回数が入る行。
  - 「実行時間」で始まる行(「実行時間: 全体 N分…」「実行時間の内訳: …」)
  - 「API呼び出し」または「キャッシュヒット」を含む行(第2段階の途中経過・格子セルキャッシュの行・最終統計・予報取得の集計)
explore は実行日時を画面に出さない(夜の日付は「今日」から決まるため、比べる2つは同じ日付[JST]の中で実行する)。
"""
from __future__ import annotations

import argparse
import contextlib
import cProfile
import io
import json
import os
import pstats
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
JST = timezone(timedelta(hours=9))

COMPARE_EXCLUDE = [
    re.compile(r"^\s*実行時間"),
    re.compile(r"API呼び出し"),
    re.compile(r"キャッシュヒット"),
]


def normalized_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if not any(p.search(line) for p in COMPARE_EXCLUDE)]


def _diff(la: list[str], lb: list[str], na: str, nb: str) -> list[str]:
    import difflib
    return list(difflib.unified_diff(la, lb, na, nb, lineterm="", n=1))[:80]


def _start_date(log: Path) -> str | None:
    j = log.with_suffix(".json")
    if not j.exists():
        return None
    return json.loads(j.read_text(encoding="utf-8"))["started_jst"][:10]


def compare_logs(a: Path, b: Path) -> tuple[bool, list[str]]:
    da, db = _start_date(a), _start_date(b)
    if da and db and da != db:
        return False, [f"開始日(JST)が違うため比べられない: {da} / {db}"]
    out: list[str] = []
    la = normalized_lines(a.read_text(encoding="utf-8"))
    lb = normalized_lines(b.read_text(encoding="utf-8"))
    if la != lb:
        out += _diff(la, lb, str(a), str(b))
    ra, rb = a.with_suffix(".results.txt"), b.with_suffix(".results.txt")
    if ra.exists() and rb.exists():
        xa = ra.read_text(encoding="utf-8").splitlines()
        xb = rb.read_text(encoding="utf-8").splitlines()
        if xa != xb:
            out += _diff(xa, xb, str(ra), str(rb))
    elif ra.exists() or rb.exists():
        out.append("片方にだけ .results.txt がある")
    return not out, out


class _Tee(io.TextIOBase):
    def __init__(self, f):
        self._f = f

    def write(self, s):
        self._f.write(s)
        return len(s)

    def flush(self):
        self._f.flush()


def _git_rev(root: Path) -> str | None:
    try:
        out = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10)
        return out.stdout.strip() or None
    except Exception:
        return None


def run(args) -> int:
    code_root = Path(args.code_root).resolve()
    cache_dir = Path(args.cache_dir).resolve()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)

    sys.path.insert(0, str(code_root))
    import explore_hoshibiyori as ex  # noqa: E402  (code_root の版)
    import grid_cache as gc  # noqa: E402
    from cloud_forecast import FetchOutcome  # noqa: E402

    if Path(ex.__file__).resolve().parent != code_root:
        print(f"[measure] explore_hoshibiyori の場所が違います: {ex.__file__}", file=sys.stderr)
        return 3

    created: list = []

    class MeasureCache(gc.GridCloudCache):
        def __init__(self, *a, **kw):
            super().__init__(cache_dir=cache_dir, disk_cache=True)
            created.append(self)

        if args.frozen:
            def _read_disk(self, key, model):  # 有効期限を無視して読む
                path = self._disk_path(key)
                if not path.exists():
                    return None
                try:
                    with open(path, encoding="utf-8") as f:
                        return json.load(f)
                except (OSError, json.JSONDecodeError):
                    return None

            def _write_disk(self, key, hourly):  # 固定キャッシュは書き換えない
                return None

    ex.GridCloudCache = MeasureCache
    if args.frozen:
        def _no_fetch(lat, lon, model, forecast_days, variables=None):
            return FetchOutcome(None, reason="frozen: キャッシュに無いセル(通信しない)")
        gc._fetch_hourly_detailed = _no_fetch
        import requests

        def _blocked(*a, **kw):
            raise RuntimeError("measure_explore --frozen: 通信は禁止")
        requests.Session.get = _blocked
        requests.get = _blocked

    if args.primary_only:
        orig_load = ex.load_candidate_sites

        def _primary_only():
            return [s for s in orig_load() if ex.is_primary_origin(s["origin"])]
        ex.load_candidate_sites = _primary_only

    # 第2段階・第3段階・見込みの戻り値を全件記録する(上位N件の表示に出ない候補の違いも見るため)
    results_log: list[str] = []

    def _record(name, fn):
        def wrapper(*a, **kw):
            res = fn(*a, **kw)
            results_log.append(f"## {name} ({len(res)}件)")
            results_log.extend(repr(x) for x in res)
            return res
        return wrapper
    for name in ("stage1_moon_filter", "stage2_cloud_filter", "stage3_direction_filter", "stage_outlook"):
        setattr(ex, name, _record(name, getattr(ex, name)))

    label = args.label
    log_path = out_dir / f"{label}.log"

    import threading

    def _watchdog():
        print(f"[measure] {args.max_minutes}分を超えたため強制終了します", file=sys.__stderr__, flush=True)
        try:
            sys.stdout.flush()
            (out_dir / f"{label}.json").write_text(json.dumps(
                {"label": label, "aborted": f"over {args.max_minutes} min"}, ensure_ascii=False), encoding="utf-8")
        finally:
            os._exit(9)
    timer = threading.Timer(args.max_minutes * 60, _watchdog)
    timer.daemon = True
    timer.start()
    started = datetime.now(JST)
    prof = cProfile.Profile() if args.profile else None
    with open(log_path, "w", encoding="utf-8", newline="\n") as logf:
        with contextlib.redirect_stdout(_Tee(logf)):
            t0 = time.perf_counter()
            if prof:
                prof.enable()
            try:
                code = ex.main(["--target", args.target])
            finally:
                if prof:
                    prof.disable()
                total = time.perf_counter() - t0
    ended = datetime.now(JST)
    timer.cancel()
    with open(out_dir / f"{label}.results.txt", "w", encoding="utf-8", newline="\n") as rf:
        rf.write("\n".join(results_log) + "\n")

    cache = created[0] if created else None
    s = cache.summary() if cache else None
    result = {
        "label": label, "code_root": str(code_root), "git_rev": _git_rev(code_root),
        "target": args.target, "frozen": args.frozen, "primary_only": args.primary_only, "profile": args.profile,
        "cache_dir": str(cache_dir), "started_jst": started.isoformat(), "ended_jst": ended.isoformat(),
        "exit_code": code, "total_sec": round(total, 3),
        "fetch_sec": round(s.fetch_sec, 3) if s else None,
        "non_fetch_sec": round(total - s.fetch_sec, 3) if s else None,
        "api_calls": s.api_calls if s else None, "cache_hits": s.cache_hits if s else None,
        "failed_cells": s.failed if s else None, "total_cells": s.total_cells if s else None,
        "log": str(log_path),
    }
    (out_dir / f"{label}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if prof:
        prof.dump_stats(str(out_dir / f"{label}.prof"))
        buf = io.StringIO()
        pstats.Stats(prof, stream=buf).sort_stats("cumulative").print_stats(40)
        (out_dir / f"{label}.profile.txt").write_text(buf.getvalue(), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="探索の実行時間の計測(計測用。既定の動きは変えない)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--cache-dir", required=True)
    r.add_argument("--out-dir", required=True)
    r.add_argument("--label", required=True)
    r.add_argument("--frozen", action="store_true")
    r.add_argument("--primary-only", action="store_true")
    r.add_argument("--profile", action="store_true")
    r.add_argument("--target", choices=("stars", "milkyway"), default="stars")
    r.add_argument("--code-root", default=str(REPO_ROOT))
    r.add_argument("--max-minutes", type=float, default=60.0)
    c = sub.add_parser("compare")
    c.add_argument("a")
    c.add_argument("b")
    args = ap.parse_args(argv)
    if args.cmd == "run":
        return run(args)
    same, diff = compare_logs(Path(args.a), Path(args.b))
    print("同じ" if same else "違いあり")
    for line in diff:
        print(line)
    return 0 if same else 1


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUTF8", "1")
    raise SystemExit(main())
