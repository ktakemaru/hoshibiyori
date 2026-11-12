"""Open-Meteo の利用上限への対応(2026-11-13)の単体テスト。ネットワークは使わない。

- 第1部: 429 の本文の reason を読み、種類(minutely/hourly/daily/unknown)で扱いを分ける
- 第2部: 通信の間隔の調整(直近60秒の重さの合計を上限以下に保つ)
- 第3部: 再試行のたびに1行出す
- 第4部: 基準地点(石廊崎)のMSMのセルが取得の失敗で空なら中止する

実行: py -X utf8 -m unittest discover -s tests
"""
import contextlib
import io
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "step5_cloud_forecast"))
sys.path.insert(0, str(ROOT))

import cloud_forecast  # noqa: E402
import grid_cache  # noqa: E402
from cloud_forecast import FetchOutcome, RequestPacer, classify_rate_limit, request_weight  # noqa: E402
from grid_cache import FetchSummary, GridCloudCache  # noqa: E402

JST = timezone(timedelta(hours=9))
OK_HOURLY = {"time": ["2026-10-12T00:00"], "cloudcover": [10]}
MINUTELY_REASON = "Minutely API request limit exceeded. Please try again in one minute."


class FakeClock:
    """時計と sleep の組。sleep で時計が進む。"""

    def __init__(self, t=1000.0):
        self.t = t
        self.sleeps: list[float] = []

    def __call__(self):
        return self.t

    def sleep(self, sec):
        self.sleeps.append(sec)
        self.t += sec


def _resp429(json_body=None, text="", json_error=False):
    r = mock.Mock()
    r.status_code = 429
    if json_error:
        r.json.side_effect = ValueError("not json")
    else:
        r.json.return_value = json_body
    r.text = text
    return r


def _resp200():
    r = mock.Mock()
    r.status_code = 200
    r.json.return_value = {"hourly": OK_HOURLY}
    r.raise_for_status.return_value = None
    return r


class ClassifyTest(unittest.TestCase):
    def test_kinds(self):
        self.assertEqual(classify_rate_limit(MINUTELY_REASON), "minutely")
        self.assertEqual(classify_rate_limit("Hourly API request limit exceeded"), "hourly")
        self.assertEqual(classify_rate_limit("Daily API request limit exceeded"), "daily")
        self.assertEqual(classify_rate_limit("too many requests"), "unknown")
        self.assertEqual(classify_rate_limit(""), "unknown")
        self.assertEqual(classify_rate_limit(None), "unknown")


@mock.patch("cloud_forecast.time.sleep")
class Fetch429ReasonTest(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(cloud_forecast, "_PACER", RequestPacer(clock=FakeClock()))
        p.start()
        self.addCleanup(p.stop)

    def fetch(self, resp):
        out = io.StringIO()
        with mock.patch("requests.Session.get", return_value=resp), contextlib.redirect_stdout(out):
            o = cloud_forecast._fetch_hourly_detailed(35.0, 139.0, "jma_msm", 4)
        return o, out.getvalue()

    def test_json_reason_minutely(self, sleep):
        o, printed = self.fetch(_resp429({"error": True, "reason": MINUTELY_REASON}))
        self.assertTrue(o.rate_limited)
        self.assertEqual(o.rate_limit_kind, "minutely")
        self.assertEqual(o.rate_limit_reason, MINUTELY_REASON)
        self.assertIn("429", o.reason)
        self.assertIn(MINUTELY_REASON, printed)
        self.assertIn("種類=minutely", printed)
        sleep.assert_not_called()  # 待ちと取り直しは grid_cache 側

    def test_non_json_body_first_200_chars(self, _sleep):
        body = "<html>" + "x" * 500
        o, printed = self.fetch(_resp429(text=body, json_error=True))
        self.assertEqual(o.rate_limit_kind, "unknown")
        self.assertEqual(o.rate_limit_reason, body[:200])
        self.assertIn(body[:200], printed)

    def test_json_without_reason_uses_text(self, _sleep):
        o, _ = self.fetch(_resp429({"error": True}, text="Daily limit"))
        self.assertEqual(o.rate_limit_kind, "daily")


class GridCacheRateLimitTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.cache = GridCloudCache(cache_dir=self._tmp.name)
        self.sleeps: list[float] = []
        self.cache._sleep = self.sleeps.append

    def limit(self, kind, reason="r"):
        return FetchOutcome(None, reason=f"HTTP 429 ({kind}): {reason}", rate_limited=True,
                            rate_limit_kind=kind, rate_limit_reason=reason)

    def get(self, lat=35.0, *outcomes):
        out = io.StringIO()
        with mock.patch("grid_cache._fetch_hourly_detailed", side_effect=list(outcomes)) as f, \
                contextlib.redirect_stdout(out):
            res = self.cache.get_hourly(lat, 139.0, "jma_msm", 4, "cloudcover")
        return res, f, out.getvalue()

    def test_minutely_waits_and_refetches_same_cell(self):
        res, f, printed = self.get(35.0, self.limit("minutely", MINUTELY_REASON), FetchOutcome(OK_HOURLY))
        self.assertEqual(res, OK_HOURLY)
        self.assertEqual(f.call_count, 2)
        self.assertEqual(f.call_args_list[0], f.call_args_list[1])  # 同じセル
        self.assertEqual(self.sleeps, [65.0])
        self.assertIn("1分の上限のため65秒待ちます(1/5)", printed)
        self.assertEqual(self.cache.failures, [])
        s = self.cache.summary()
        self.assertEqual((s.minutely_waits, s.minutely_wait_sec, s.status), (1, 65.0, "ok"))
        self.assertEqual(self.cache.rate_limit_events, [("minutely", MINUTELY_REASON)])

    def test_minutely_budget_is_five_per_run(self):
        # 別々のセルで計5回まで待てる。6回目は中止
        for i in range(5):
            self.get(35.0 + i, self.limit("minutely"), FetchOutcome(OK_HOURLY))
        self.assertEqual(len(self.sleeps), 5)
        with self.assertRaises(cloud_forecast.OpenMeteoDailyLimitError) as cm:
            self.get(40.0, self.limit("minutely", MINUTELY_REASON))
        self.assertEqual(len(self.sleeps), 5)
        self.assertIn("minutely", str(cm.exception))
        self.assertIn(MINUTELY_REASON, str(cm.exception))
        self.assertEqual(self.cache.summary().status, "abort")

    def test_hourly_daily_unknown_abort_without_wait(self):
        for kind in ("hourly", "daily", "unknown"):
            cache = GridCloudCache(cache_dir=self._tmp.name)
            cache._sleep = self.sleeps.append
            with mock.patch("grid_cache._fetch_hourly_detailed", side_effect=[self.limit(kind, f"{kind} reason")]):
                with self.assertRaises(cloud_forecast.OpenMeteoDailyLimitError) as cm:
                    cache.get_hourly(35.0, 139.0, "jma_msm", 4, "cloudcover")
            self.assertIn(f"種類={kind}", str(cm.exception))
            self.assertIn(f"{kind} reason", str(cm.exception))
            self.assertTrue(cache.rate_limited)
            self.assertEqual(len(cache.failures), 1)
        self.assertEqual(self.sleeps, [])

    def test_legacy_outcome_without_kind_aborts(self):
        with self.assertRaises(cloud_forecast.OpenMeteoDailyLimitError):
            self.get(35.0, FetchOutcome(None, reason="HTTP 429", rate_limited=True))
        self.assertEqual(self.sleeps, [])


class RequestWeightTest(unittest.TestCase):
    def test_weight(self):
        from elevation_cloud import level_hourly_vars
        v = level_hourly_vars()
        self.assertEqual(len(v.split(",")), 24)
        self.assertAlmostEqual(request_weight(v, 4), 2.4)
        self.assertAlmostEqual(request_weight(v, 15), 2.4 * 15 / 14)
        self.assertAlmostEqual(request_weight("cloudcover", 4), 1.0)
        self.assertAlmostEqual(request_weight(",".join(["a"] * 5), 28), 2.0)


class RequestPacerTest(unittest.TestCase):
    def test_never_exceeds_limit_in_any_window(self):
        clock = FakeClock()
        pacer = RequestPacer(limit=10.0, window_sec=60.0, clock=clock, sleep=clock.sleep)
        sent = []
        for _ in range(30):
            pacer.acquire(2.5)
            sent.append(clock.t)
            clock.t += 0.5  # 通信そのものの時間
        for t in sent:
            in_window = [s for s in sent if t - 60.0 < s <= t]
            self.assertLessEqual(len(in_window) * 2.5, 10.0)
        self.assertGreater(sum(clock.sleeps), 0)

    def test_no_wait_under_limit_and_wait_total(self):
        clock = FakeClock(0.0)
        pacer = RequestPacer(limit=5.0, window_sec=60.0, clock=clock, sleep=clock.sleep)
        self.assertEqual(pacer.acquire(2.0), 0.0)
        clock.t = 10.0
        self.assertEqual(pacer.acquire(2.0), 0.0)
        clock.t = 20.0
        waited = pacer.acquire(2.0)  # 2+2+2 > 5 → 最初の分(時刻0)が抜ける60秒まで待つ
        self.assertAlmostEqual(waited, 40.0)
        self.assertAlmostEqual(clock.t, 60.0)
        self.assertAlmostEqual(pacer.window_total(), 4.0)


@mock.patch("cloud_forecast.time.sleep")
class FetchPacingTest(unittest.TestCase):
    def test_retries_go_through_pacer_and_wait_is_not_fetch_time(self, _sleep):
        pacer = mock.Mock()
        pacer.acquire.return_value = 3.0
        with mock.patch.object(cloud_forecast, "_PACER", pacer), \
                mock.patch("requests.Session.get", side_effect=requests.ConnectionError("x")), \
                contextlib.redirect_stdout(io.StringIO()):
            o = cloud_forecast._fetch_hourly_detailed(35.0, 139.0, "jma_msm", 4)
        self.assertEqual(pacer.acquire.call_count, 3)  # 再試行の通信も数える
        self.assertAlmostEqual(o.paced_sec, 9.0)
        self.assertLess(o.elapsed_sec, 1.0)  # 間隔の調整の待ち(偽)は通信に入れない

    def test_cache_hit_does_not_touch_pacer(self, _sleep):
        pacer = mock.Mock()
        pacer.acquire.return_value = 0.0
        with tempfile.TemporaryDirectory() as d, mock.patch.object(cloud_forecast, "_PACER", pacer), \
                mock.patch("requests.Session.get", return_value=_resp200()):
            cache = GridCloudCache(cache_dir=d)
            cache.get_hourly(35.0, 139.0, "jma_msm", 4, "cloudcover")
            cache.get_hourly(35.0, 139.0, "jma_msm", 4, "cloudcover")  # メモリ
            GridCloudCache(cache_dir=d).get_hourly(35.0, 139.0, "jma_msm", 4, "cloudcover")  # ディスク
        self.assertEqual(pacer.acquire.call_count, 1)
        pacer.acquire.assert_called_with(1.0)


class PacingSummaryTest(unittest.TestCase):
    def test_paced_sec_summed(self):
        with tempfile.TemporaryDirectory() as d:
            cache = GridCloudCache(cache_dir=d)
            outs = [FetchOutcome(OK_HOURLY, attempts=1, elapsed_sec=0.5, paced_sec=12.0),
                    FetchOutcome(OK_HOURLY, attempts=1, elapsed_sec=0.5, paced_sec=0.5)]
            with mock.patch("grid_cache._fetch_hourly_detailed", side_effect=outs):
                cache.get_hourly(35.0, 139.0, "jma_msm", 4, "cloudcover")
                cache.get_hourly(36.0, 139.0, "jma_msm", 4, "cloudcover")
            s = cache.summary()
        self.assertAlmostEqual(s.pacing_sec, 12.5)
        self.assertAlmostEqual(s.fetch_sec, 1.0)
        self.assertTrue(s.console_line().endswith(" / 間隔の調整 12.5 秒"))

    def test_console_line_unchanged_without_wait(self):
        line = FetchSummary(10, 10, 0, 0, False, fetch_sec=3.0).console_line()
        self.assertNotIn("間隔の調整", line)

    def test_console_line_with_minutely(self):
        s = FetchSummary(10, 10, 0, 0, False, pacing_sec=10.0, minutely_waits=2, minutely_wait_sec=130.0)
        self.assertTrue(s.console_line().endswith(" / 間隔の調整 140.0 秒(うち1分の上限の待ち 2 回・130.0 秒)"))

    def test_timing_line_three_way(self):
        s = FetchSummary(10, 10, 0, 0, False, fetch_sec=40.0, pacing_sec=20.0)
        self.assertEqual(grid_cache.timing_line(100.0, s),
                         "実行時間の内訳: 全体 100.0 秒 / Open-Meteoの通信 40.0 秒 / 間隔の調整 20.0 秒 / "
                         "それ以外 40.0 秒(全体 − 通信 − 間隔の調整)")


@mock.patch("cloud_forecast.time.sleep")
class RetryPrintTest(unittest.TestCase):
    def test_each_retry_prints_one_line(self, _sleep):
        out = io.StringIO()
        with mock.patch("requests.Session.get", side_effect=[requests.ConnectionError("x"),
                                                             requests.ConnectionError("y"), _resp200()]), \
                contextlib.redirect_stdout(out):
            o = cloud_forecast._fetch_hourly_detailed(35.0, 139.0, "jma_msm", 4)
        self.assertEqual(o.hourly, OK_HOURLY)
        lines = [l for l in out.getvalue().splitlines() if "[再試行]" in l]
        self.assertEqual(len(lines), 2)
        self.assertIn("ConnectionError", lines[0])
        self.assertIn("2秒待って2回目", lines[0])
        self.assertIn("4秒待って3回目", lines[1])

    def test_no_print_on_first_success(self, _sleep):
        out = io.StringIO()
        with mock.patch("requests.Session.get", return_value=_resp200()), contextlib.redirect_stdout(out):
            cloud_forecast._fetch_hourly_detailed(35.0, 139.0, "jma_msm", 4)
        self.assertEqual(out.getvalue(), "")


class ReferenceSiteTest(unittest.TestCase):
    """第4部: 基準地点のMSMのセルが取得の失敗で空なら中止、範囲の外なら従来どおり ECMWF。"""

    REF = {"name": "石廊崎", "lat": 34.6, "lon": 138.85}

    @classmethod
    def setUpClass(cls):
        import explore_hoshibiyori
        import elevation_cloud
        cls.ex = explore_hoshibiyori
        cls.total_var = elevation_cloud._NATIVE_VARS["total"]

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.cache = GridCloudCache(cache_dir=self._tmp.name, disk_cache=False)
        start = datetime(2026, 11, 13, 20, tzinfo=JST)
        self.night = SimpleNamespace(window_start=start, window_end=start + timedelta(hours=3))

    def hourly(self, first: datetime, hours: int):
        return {"time": [(first + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M") for i in range(hours)],
                self.total_var: [10.0] * hours}

    def fetch_by_model(self, msm, ecmwf):
        def fake(lat, lon, model, days, variables=None):
            return msm if model == "jma_msm" else ecmwf
        return mock.patch("grid_cache._fetch_hourly_detailed", side_effect=fake)

    def test_msm_failure_raises(self):
        ecmwf = FetchOutcome(self.hourly(datetime(2026, 11, 13, 0, tzinfo=JST), 48))
        with self.fetch_by_model(FetchOutcome(None, reason="ConnectionResetError: 10054"), ecmwf):
            with self.assertRaises(self.ex.ReferenceForecastUnavailable) as cm:
                self.ex.forecast_regime_for_night(self.cache, self.REF, self.night)
        self.assertIn("基準地点の予報を取得できなかったため中止します", str(cm.exception))

    def test_msm_ok_but_out_of_range_is_ecmwf(self):
        msm = FetchOutcome(self.hourly(datetime(2026, 11, 10, 0, tzinfo=JST), 24))  # その夜を含まない
        ecmwf = FetchOutcome(self.hourly(datetime(2026, 11, 13, 0, tzinfo=JST), 48))
        with self.fetch_by_model(msm, ecmwf):
            self.assertEqual(self.ex.forecast_regime_for_night(self.cache, self.REF, self.night), "ECMWF")

    def test_msm_in_range_is_msm(self):
        msm = FetchOutcome(self.hourly(datetime(2026, 11, 13, 0, tzinfo=JST), 48))
        with self.fetch_by_model(msm, FetchOutcome(None, reason="x")):
            self.assertEqual(self.ex.forecast_regime_for_night(self.cache, self.REF, self.night), "MSM")

    def test_explore_run_returns_2(self):
        err = self.ex.ReferenceForecastUnavailable("基準地点の予報を取得できなかったため中止します(テスト)")
        out = io.StringIO()
        with mock.patch.object(self.ex, "_explore", side_effect=err), contextlib.redirect_stdout(out):
            code = self.ex._run(self.cache, SimpleNamespace(target="stars"))
        self.assertEqual(code, 2)
        self.assertIn("基準地点の予報を取得できなかったため中止します", out.getvalue())

    def test_generate_report_returns_2_without_writing(self):
        import generate_report
        err = self.ex.ReferenceForecastUnavailable("基準地点の予報を取得できなかったため中止します(テスト)")
        out = io.StringIO()
        with mock.patch.object(generate_report, "_generate", side_effect=err), \
                mock.patch.object(generate_report, "GridCloudCache", lambda: self.cache), \
                contextlib.redirect_stdout(out):
            code = generate_report.main(["--target", "stars"])
        self.assertEqual(code, 2)
        self.assertIn("更新していません", out.getvalue())


if __name__ == "__main__":
    unittest.main()
