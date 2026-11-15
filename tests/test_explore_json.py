"""探索結果の JSON 出力(explore_hoshibiyori.py --json-out、スキーマ hoshibiyori-explore/1)のテスト。通信しない。

- 組み立て(explore_json.build_explore_json)は手で作ったデータクラスで確かめる。
- main() の経路は、GridCloudCache・天文計算のキャッシュ・_explore を差し替えて確かめる(通信・天文計算をしない)。
- スキーマの検査は依存を足さず、このファイルの中の小さな検査器で行う(必須の項目・型・const・enum・$ref・allOf)。
"""
from __future__ import annotations

import contextlib
import io
import json
import re
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import explore_hoshibiyori as ex  # noqa: E402
import explore_json as ej  # noqa: E402
from grid_cache import FailedCell, FetchSummary  # noqa: E402
from cloud_forecast import OpenMeteoDailyLimitError  # noqa: E402

JST = timezone(timedelta(hours=9))
SCHEMA_PATH = ROOT / "schemas" / "hoshibiyori-explore.schema.json"
GEN = datetime(2026, 11, 16, 4, 38, 0, tzinfo=JST)
OFFSET_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?[+-]\d{2}:\d{2}$")


def t(day, hour, minute=0):
    return datetime(2026, 11, day, hour, minute, tzinfo=JST)


def make_final(name, origin="curated", score=50.0, night=date(2026, 11, 17), stars=False, **kw):
    base = dict(
        night_date=night, site_name=name, municipality="テスト市", origin=origin,
        site_lat=35.5, site_lon=139.0, requires_lift_access=False,
        window_start=t(17, 19), window_end=t(18, 2), best_time=t(17, 20),
        target_az=None if stars else 220.5, target_alt=None if stars else 12.25,
        horizon_alt=None if stars else 3.5, terrain_available=not stars,
        mean_obstruction=12.345678, lp_index=1.23456789, moon_free_hours=6.5, clear_hours=5.0,
        score=0.0 if stars else score, alr=2.5, alr_rank_pct=20.0,
    )
    base.update(kw)
    return ex.FinalCandidate(**base)


def make_outlook(name, origin="curated", score=80.0, night=date(2026, 11, 20), stars=False, **kw):
    base = dict(
        night_date=night, site_name=name, municipality="テスト町", origin=origin,
        site_lat=36.0, site_lon=138.5, requires_lift_access=True,
        visible_start=t(20, 19), visible_end=t(21, 3),
        target_az=None if stars else 200.0, target_alt=None if stars else 10.0,
        horizon_alt=None, terrain_available=False, lp_index=0.5, clear_sky_pct=None,
        moon_free_hours=7.0, score=0.0 if stars else score, alr=1.0, alr_rank_pct=5.0,
    )
    base.update(kw)
    return ex.OutlookCandidate(**base)


def make_night(day, hours=6.0):
    d = date(2026, 11, day)
    return ex.NightCandidate(night_date=d, sunset=t(day, 16, 35), sunrise=t(day + 1, 6, 15),
                             dark_start=t(day, 18, 3), dark_end=t(day + 1, 4, 48),
                             window_start=t(day, 18, 3), window_end=t(day + 1, 0, 3), moon_free_hours=hours)


def summary(failed=0, total=10, rate_limited=False):
    return FetchSummary(total_cells=total, api_calls=total - failed, cache_hits=3, failed=failed, rate_limited=rate_limited)


def build(finals=(), outlooks=(), target="milkyway", nights=None, msm_dates=(date(2026, 11, 17),),
          fetch=None, failures=(), generated_at=GEN):
    return ej.build_explore_json(
        generated_at=generated_at, version="1.1.0", commit="0" * 40, dirty=False,
        target=target, astro_grid="ecmwf", thresholds=ex.explore_thresholds(10.66),
        reference_site={"name": "石廊崎", "lat": 34.6, "lon": 138.85, "elevation_m": 60.0},
        nights=list(nights if nights is not None else [make_night(17), make_night(20)]),
        msm_dates=msm_dates, finals=list(finals), outlooks=list(outlooks),
        final_rank_key=lambda f: ex.final_rank_key(f, target),
        outlook_rank_key=lambda o: ex.outlook_rank_key(o, target),
        is_primary=ex.is_primary_origin, fetch_summary=fetch or summary(), fetch_failures=list(failures),
        sites={"primary": 2, "reference": 1, "total": 3, "with_horizon": 1},
    )


# --- 小さなスキーマ検査器(依存を足さないため) ---
_TYPES = {"object": dict, "array": list, "string": str, "boolean": bool, "null": type(None)}


def _type_ok(value, name):
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return isinstance(value, _TYPES[name])


def validate(value, schema, root, path="$"):
    errors = []
    if "$ref" in schema:
        name = schema["$ref"].split("/")[-1]
        errors += validate(value, root["$defs"][name], root, path)
    for sub in schema.get("allOf", []):
        errors += validate(value, sub, root, path)
    if "type" in schema:
        names = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_type_ok(value, n) for n in names):
            return errors + [f"{path}: 型が {names} でない ({type(value).__name__})"]
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: {value!r} != const {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} が enum にない")
    if schema.get("format") == "date-time" and isinstance(value, str) and not OFFSET_RE.match(value):
        errors.append(f"{path}: オフセットつきの時刻でない {value!r}")
    if schema.get("format") == "date" and isinstance(value, str) and not re.match(r"^\d{4}-\d{2}-\d{2}$", value):
        errors.append(f"{path}: YYYY-MM-DD でない {value!r}")
    if isinstance(value, dict):
        for k in schema.get("required", []):
            if k not in value:
                errors.append(f"{path}: 必須の {k} がない")
        for k, sub in schema.get("properties", {}).items():
            if k in value:
                errors += validate(value[k], sub, root, f"{path}.{k}")
        extra = schema.get("additionalProperties")
        if isinstance(extra, dict):
            for k, v in value.items():
                if k not in schema.get("properties", {}):
                    errors += validate(v, extra, root, f"{path}.{k}")
    if isinstance(value, list) and "items" in schema:
        for i, v in enumerate(value):
            errors += validate(v, schema["items"], root, f"{path}[{i}]")
    return errors


def iter_strings_with_keys(obj, key=None):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from iter_strings_with_keys(v, k)
    elif isinstance(obj, list):
        for v in obj:
            yield from iter_strings_with_keys(v, key)
    else:
        yield key, obj


class BuildTests(unittest.TestCase):
    def test_top_level_items(self):
        doc = build([make_final("A")], [make_outlook("B")])
        for k in ("schema", "generated_at", "version", "commit", "dirty", "target", "astro_grid", "thresholds",
                  "reference_site", "nights", "finals", "outlooks", "fetch", "sites", "notes"):
            self.assertIn(k, doc)
        self.assertEqual(doc["schema"], "hoshibiyori-explore/1")
        self.assertEqual(doc["generated_at"], "2026-11-16T04:38:00+09:00")
        self.assertEqual(doc["reference_site"], {"name": "石廊崎", "lat": 34.6, "lon": 138.85})
        self.assertEqual(doc["notes"], ej.NOTES)
        self.assertEqual(len(doc["notes"]), 3)
        # 閾値はコードの定数から
        th = doc["thresholds"]
        self.assertEqual(th["cloud_obstruction_threshold_pct"], ex.CLOUD_OBSTRUCTION_THRESHOLD)
        self.assertEqual(th["min_clear_window_hours"], ex.MIN_CLEAR_WINDOW_HOURS)
        self.assertEqual(th["lp_index_limit"], ex.LP_INDEX_LIMIT)
        self.assertEqual(th["milkyway_few_results"], ex.MILKYWAY_FEW_RESULTS)
        self.assertEqual(th["failed_cell_rate_abort"], ex.FAILED_CELL_RATE_ABORT)
        self.assertEqual(th["lp_alr_threshold"], 10.66)

    def test_candidate_fields_and_kinds(self):
        f = make_final("A")
        doc = build([f], [make_outlook("B")])
        rec = doc["finals"][0]
        import dataclasses
        for fld in dataclasses.fields(ex.FinalCandidate):
            self.assertIn(fld.name, rec)
        self.assertEqual(rec["mean_obstruction"], 12.345678)   # 丸めない
        self.assertEqual(rec["lp_index"], 1.23456789)
        self.assertEqual(rec["score_kind"], "final")
        self.assertTrue(rec["is_primary"])
        self.assertEqual(rec["rank"], 1)
        orec = doc["outlooks"][0]
        for fld in dataclasses.fields(ex.OutlookCandidate):
            self.assertIn(fld.name, orec)
        self.assertEqual(orec["score_kind"], "outlook")

    def test_nights_regime(self):
        doc = build()
        self.assertEqual([n["regime"] for n in doc["nights"]], ["MSM", "ECMWF"])
        self.assertEqual(doc["nights"][0]["night_date"], "2026-11-17")
        self.assertEqual(doc["nights"][0]["sunset"], "2026-11-17T16:35:00+09:00")

    def test_times_have_offset_none_and_nan_are_null(self):
        nan_final = make_final("N", mean_obstruction=float("nan"), lp_index=float("inf"), alr=None)
        doc = build([nan_final], [make_outlook("O", clear_sky_pct=float("nan"))])
        self.assertIsNone(doc["finals"][0]["mean_obstruction"])
        self.assertIsNone(doc["finals"][0]["lp_index"])
        self.assertIsNone(doc["finals"][0]["alr"])
        self.assertIsNone(doc["outlooks"][0]["clear_sky_pct"])
        text = ej.dumps(doc)       # allow_nan=False で通る
        self.assertNotIn("NaN", text)
        self.assertNotIn("Infinity", text)
        time_keys = {"generated_at", "sunset", "sunrise", "dark_start", "dark_end", "window_start", "window_end",
                     "best_time", "visible_start", "visible_end"}
        for key, v in iter_strings_with_keys(json.loads(text)):
            if key in time_keys and v is not None:
                self.assertRegex(v, OFFSET_RE, key)

    def test_naive_datetime_becomes_null(self):
        self.assertIsNone(ej.json_value(datetime(2026, 11, 17, 20, 0)))
        self.assertEqual(ej.json_value(date(2026, 11, 17)), "2026-11-17")

    def test_all_candidates_kept_and_rank_order_matches_screen(self):
        finals = [make_final(f"P{i}", score=float(i)) for i in range(30)]
        finals += [make_final(f"R{i}", origin="viewpoint", score=float(i)) for i in range(15)]
        outlooks = [make_outlook(f"Q{i}", score=float(i % 7)) for i in range(25)]
        outlooks += [make_outlook(f"S{i}", origin="test_site", score=float(i)) for i in range(12)]
        doc = build(finals, outlooks)
        self.assertEqual(len(doc["finals"]), 45)          # 画面の上位20+10で切らない
        self.assertEqual(len(doc["outlooks"]), 37)
        exp_p = sorted((f for f in finals if ex.is_primary_origin(f.origin)),
                       key=lambda f: ex.final_rank_key(f, "milkyway"), reverse=True)
        exp_r = sorted((f for f in finals if not ex.is_primary_origin(f.origin)),
                       key=lambda f: ex.final_rank_key(f, "milkyway"), reverse=True)
        self.assertEqual([r["site_name"] for r in doc["finals"]], [f.site_name for f in exp_p + exp_r])
        self.assertEqual([r["rank"] for r in doc["finals"]], list(range(1, 31)) + list(range(1, 16)))
        self.assertEqual({r["group"] for r in doc["finals"][:30]}, {"primary"})
        self.assertEqual({r["group"] for r in doc["finals"][30:]}, {"reference"})
        exp_o = sorted((o for o in outlooks if ex.is_primary_origin(o.origin)),
                       key=lambda o: ex.outlook_rank_key(o, "milkyway"), reverse=True)
        self.assertEqual([r["site_name"] for r in doc["outlooks"][:25]], [o.site_name for o in exp_o])  # 同点は安定

    def test_stars_mode_rank_and_nulls(self):
        finals = [make_final("A", stars=True, clear_hours=3.0), make_final("B", stars=True, clear_hours=6.0)]
        outlooks = [make_outlook("C", stars=True, alr=3.0), make_outlook("D", stars=True, alr=0.5)]
        doc = build(finals, outlooks, target="stars")
        self.assertEqual([r["site_name"] for r in doc["finals"]], ["B", "A"])
        self.assertEqual([r["site_name"] for r in doc["outlooks"]], ["D", "C"])
        for r in doc["finals"] + doc["outlooks"]:
            self.assertIsNone(r["target_az"])
            self.assertIsNone(r["target_alt"])
            self.assertIsNone(r["horizon_alt"])
        self.assertEqual(doc["target"], "stars")
        self.assertEqual(validate(doc, json.loads(SCHEMA_PATH.read_text(encoding="utf-8")),
                                  json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))), [])

    def test_same_input_same_bytes(self):
        args = ([make_final("A"), make_final("B", origin="viewpoint")], [make_outlook("C")])
        a = ej.dumps(build(*args)).encode("utf-8")
        b = ej.dumps(build(*args)).encode("utf-8")
        self.assertEqual(a, b)
        c = ej.dumps(build(*args, generated_at=GEN + timedelta(hours=1))).encode("utf-8")
        self.assertNotEqual(a, c)
        da, dc = json.loads(a), json.loads(c)
        da.pop("generated_at"), dc.pop("generated_at")
        self.assertEqual(da, dc)

    def test_fetch_has_counts_and_reason_kinds_without_coordinates(self):
        failures = [FailedCell("jma_msm", 35.123, 139.456, "ConnectionResetError: [WinError 10054] lat=35.123"),
                    FailedCell("jma_msm", 35.2, 139.5, "client_error (HTTP 404)"),
                    FailedCell("ecmwf_ifs025", 36.0, 138.0, "ConnectionResetError: x")]
        doc = build(fetch=summary(failed=3, total=40), failures=failures)
        fe = doc["fetch"]
        self.assertEqual(fe["status"], "partial")
        self.assertEqual(fe["failed_cells"], 3)
        self.assertEqual(fe["total_cells"], 40)
        self.assertAlmostEqual(fe["failed_rate"], 3 / 40)
        self.assertEqual(fe["failure_reasons"], {"ConnectionResetError": 2, "client_error (HTTP 404)": 1})
        text = json.dumps(fe, ensure_ascii=False)
        self.assertNotIn("35.123", text)
        self.assertNotIn("139.456", text)

    def test_schema_required_items_present(self):
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        doc = json.loads(ej.dumps(build([make_final("A"), make_final("B", origin="viewpoint")],
                                        [make_outlook("C"), make_outlook("D", horizon_alt=1.0, terrain_available=True)])))
        self.assertEqual(validate(doc, schema, schema), [])
        # 検査器が欠けを見つけられること
        broken = dict(doc)
        broken.pop("fetch")
        broken["finals"] = [dict(doc["finals"][0], rank="1")]
        errs = validate(broken, schema, schema)
        self.assertTrue(any("fetch" in e for e in errs))
        self.assertTrue(any("rank" in e for e in errs))

    def test_schema_required_matches_dataclass_fields(self):
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        import dataclasses
        common = set(schema["$defs"]["candidate_common"]["required"])
        final_req = common | set(schema["$defs"]["final"]["required"])
        outlook_req = common | set(schema["$defs"]["outlook"]["required"])
        extra = {"score_kind", "is_primary", "group", "rank"}
        self.assertEqual(final_req - extra, {f.name for f in dataclasses.fields(ex.FinalCandidate)})
        self.assertEqual(outlook_req - extra, {f.name for f in dataclasses.fields(ex.OutlookCandidate)})
        night_req = set(schema["$defs"]["night"]["required"]) - {"regime"}
        self.assertEqual(night_req, {f.name for f in dataclasses.fields(ex.NightCandidate)})


class WriteTests(unittest.TestCase):
    def test_atomic_write_creates_parent_and_utf8_without_bom(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "sub" / "dir" / "out.json"
            ej.write_json_atomic(path, build([make_final("戦場ヶ原")]))
            raw = path.read_bytes()
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
            self.assertIn("戦場ヶ原".encode("utf-8"), raw)
            self.assertEqual(json.loads(raw.decode("utf-8"))["schema"], "hoshibiyori-explore/1")
            self.assertEqual([p.name for p in path.parent.iterdir()], ["out.json"])   # 一時ファイルが残らない

    def test_failed_write_keeps_old_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "out.json"
            path.write_text("old", encoding="utf-8")
            with mock.patch.object(ej.os, "replace", side_effect=OSError("boom")):
                with self.assertRaises(OSError):
                    ej.write_json_atomic(path, build())
            self.assertEqual(path.read_text(encoding="utf-8"), "old")
            self.assertEqual([p.name for p in Path(d).iterdir()], ["out.json"])


class FakeCache:
    """main() 用の偽の GridCloudCache(通信しない)。"""

    def __init__(self, fetch_summary=None, failures=()):
        self._summary = fetch_summary or summary()
        self.failures = list(failures)

    def summary(self):
        return self._summary


def fake_result():
    return {"sites": {"primary": 2, "reference": 1, "total": 3, "with_horizon": 1},
            "reference_site": {"name": "石廊崎", "lat": 34.6, "lon": 138.85},
            "nights": [make_night(17)], "msm_dates": [date(2026, 11, 17)],
            "finals": [make_final("A"), make_final("B", origin="viewpoint")],
            "outlooks": [make_outlook("C")], "alr_threshold": 10.66}


class MainPathTests(unittest.TestCase):
    """main() の経路(通信・天文計算はすべて差し替える)。"""

    def run_main(self, argv, cache, explore_effect):
        out = io.StringIO()
        kwargs = {"side_effect": explore_effect} if isinstance(explore_effect, BaseException) else \
            {"return_value": explore_effect}
        with mock.patch.object(ex, "GridCloudCache", lambda: cache), \
                mock.patch.object(ex, "make_astro_cache", lambda mode: None), \
                mock.patch.object(ex, "_explore", **kwargs), \
                mock.patch("requests.get", side_effect=AssertionError("通信しない")), \
                mock.patch("requests.Session.get", side_effect=AssertionError("通信しない")), \
                contextlib.redirect_stdout(out):
            code = ex.main(argv)
        return code, out.getvalue()

    def test_writes_json_on_exit_0(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "new" / "x.json"
            code, out = self.run_main(["--target", "stars", "--json-out", str(path)], FakeCache(), fake_result())
            self.assertEqual(code, 0)
            self.assertTrue(path.exists())
            doc = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(doc["target"], "stars")
            self.assertEqual(doc["astro_grid"], "ecmwf")
            self.assertEqual(len(doc["finals"]), 2)
            self.assertEqual(doc["fetch"]["status"], "ok")
            self.assertRegex(doc["generated_at"], OFFSET_RE)
            self.assertEqual(out.splitlines()[-1], f"探索結果の JSON を書きました: {path}")

    def test_partial_still_writes(self):
        cache = FakeCache(summary(failed=1, total=10), [FailedCell("jma_msm", 35.0, 139.0, "TimeoutError: x")])
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "x.json"
            code, _ = self.run_main(["--json-out", str(path)], cache, fake_result())
            self.assertEqual(code, 0)
            doc = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(doc["fetch"]["status"], "partial")
            self.assertEqual(doc["fetch"]["failure_reasons"], {"TimeoutError": 1})

    def assert_exit2_untouched(self, cache, effect):
        with tempfile.TemporaryDirectory() as d:
            existing = Path(d) / "old.json"
            existing.write_bytes(b'{"old": true}\n')
            missing = Path(d) / "missing.json"
            code, out = self.run_main(["--json-out", str(existing)], cache, effect)
            self.assertEqual(code, 2)
            self.assertEqual(existing.read_bytes(), b'{"old": true}\n')
            self.assertNotIn("探索結果の JSON を書きました", out)
            code, _ = self.run_main(["--json-out", str(missing)], cache, effect)
            self.assertEqual(code, 2)
            self.assertFalse(missing.exists())
            self.assertEqual(sorted(p.name for p in Path(d).iterdir()), ["old.json"])

    def test_exit2_abort_rate(self):
        cache = FakeCache(summary(failed=5, total=10), [FailedCell("jma_msm", 35.0, 139.0, "x")] * 5)
        self.assert_exit2_untouched(cache, fake_result())

    def test_exit2_rate_limited(self):
        self.assert_exit2_untouched(FakeCache(summary(rate_limited=True)), OpenMeteoDailyLimitError("429 テスト"))

    def test_exit2_reference_unavailable(self):
        self.assert_exit2_untouched(FakeCache(), ex.ReferenceForecastUnavailable("基準地点 テスト"))

    def test_without_json_out_no_file_no_extra_line(self):
        with tempfile.TemporaryDirectory() as d:
            before = set(Path(d).iterdir())
            with mock.patch.object(ex, "write_explore_json", side_effect=AssertionError("書かない")):
                code, out = self.run_main(["--target", "stars"], FakeCache(), fake_result())
            self.assertEqual(code, 0)
            self.assertNotIn("JSON", out)
            self.assertEqual(set(Path(d).iterdir()), before)
            self.assertIsNone(ex.parse_args([]).json_out)

    def test_run_still_accepts_args_without_json_out(self):
        # 既存の呼び方(sink なし・json_out の無い args)が動くこと
        from types import SimpleNamespace
        with mock.patch.object(ex, "_explore", return_value=fake_result()), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(ex._run(FakeCache(), SimpleNamespace(target="stars")), 0)


class MetaTests(unittest.TestCase):
    def test_plugin_version(self):
        manifest = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(ej.plugin_version(), manifest["version"])
        self.assertIsNone(ej.plugin_version(ROOT / "no-such-plugin.json"))

    def test_git_state_without_git(self):
        with mock.patch.object(ej.subprocess, "run", side_effect=FileNotFoundError("git")):
            self.assertEqual(ej.git_state(), (None, None))

    def test_git_state_not_a_repo(self):
        from types import SimpleNamespace
        with mock.patch.object(ej.subprocess, "run",
                               return_value=SimpleNamespace(returncode=128, stdout="", stderr="fatal")):
            self.assertEqual(ej.git_state(), (None, None))

    def test_git_state_uses_argument_list(self):
        from types import SimpleNamespace
        calls = []

        def fake(cmd, **kw):
            calls.append((cmd, kw))
            return SimpleNamespace(returncode=0, stdout=("a" * 40 + "\n") if "rev-parse" in cmd else " M x.py\n")
        with mock.patch.object(ej.subprocess, "run", side_effect=fake):
            self.assertEqual(ej.git_state(), ("a" * 40, True))
        for cmd, kw in calls:
            self.assertIsInstance(cmd, list)
            self.assertNotIn("shell", kw)


if __name__ == "__main__":
    unittest.main()
