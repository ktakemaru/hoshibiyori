"""取得失敗の扱い(cloud_forecast._fetch_hourly_detailed / grid_cache.GridCloudCache)の単体テスト。
ネットワークは使わない(requests.Session.get と time.sleep をモックする)。

実行: python -m unittest discover -s tests -v
"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "step5_cloud_forecast"))

import cloud_forecast  # noqa: E402
import grid_cache  # noqa: E402
from grid_cache import FetchSummary, GridCloudCache  # noqa: E402

OK_HOURLY = {"time": ["2026-10-12T00:00"], "cloudcover": [10]}


def _resp(status: int, payload=None):
    r = mock.Mock()
    r.status_code = status
    r.json.return_value = {"hourly": payload if payload is not None else OK_HOURLY}
    if status >= 400:
        r.raise_for_status.side_effect = requests.HTTPError(f"{status} error")
    else:
        r.raise_for_status.return_value = None
    return r


@mock.patch("cloud_forecast.time.sleep")
class FetchHourlyDetailedTest(unittest.TestCase):
    def call(self):
        return cloud_forecast._fetch_hourly_detailed(35.0, 139.0, "jma_msm", 4)

    def test_200_success(self, _sleep):
        with mock.patch("requests.Session.get", return_value=_resp(200)) as g:
            out = self.call()
        self.assertEqual(out.hourly, OK_HOURLY)
        self.assertIsNone(out.reason)
        self.assertFalse(out.rate_limited)
        self.assertEqual(g.call_count, 1)

    def test_429_is_not_retried(self, sleep):
        with mock.patch("requests.Session.get", return_value=_resp(429)) as g:
            out = self.call()
        self.assertIsNone(out.hourly)
        self.assertTrue(out.rate_limited)
        self.assertIn("429", out.reason)
        self.assertEqual(g.call_count, 1)
        sleep.assert_not_called()

    def test_400_is_client_error_without_retry(self, sleep):
        with mock.patch("requests.Session.get", return_value=_resp(400)) as g:
            out = self.call()
        self.assertIsNone(out.hourly)
        self.assertFalse(out.rate_limited)
        self.assertTrue(out.reason.startswith("client_error"))
        self.assertEqual(g.call_count, 1)
        sleep.assert_not_called()

    def test_408_is_retried(self, sleep):
        with mock.patch("requests.Session.get", side_effect=[_resp(408), _resp(200)]) as g:
            out = self.call()
        self.assertEqual(out.hourly, OK_HOURLY)
        self.assertEqual(g.call_count, 2)
        self.assertEqual(sleep.call_count, 1)

    def test_500_then_success(self, sleep):
        with mock.patch("requests.Session.get", side_effect=[_resp(500), _resp(500), _resp(200)]) as g:
            out = self.call()
        self.assertEqual(out.hourly, OK_HOURLY)
        self.assertEqual(g.call_count, 3)
        self.assertEqual(sleep.call_count, 2)

    def test_connection_error_three_times(self, _sleep):
        with mock.patch("requests.Session.get", side_effect=requests.ConnectionError("boom")) as g:
            out = self.call()
        self.assertIsNone(out.hourly)
        self.assertFalse(out.rate_limited)
        self.assertIn("ConnectionError", out.reason)
        self.assertEqual(g.call_count, 3)

    def test_legacy_wrapper_returns_none_on_failure(self, _sleep):
        with mock.patch("requests.Session.get", side_effect=requests.ConnectionError("x")):
            self.assertIsNone(cloud_forecast._fetch_hourly(35.0, 139.0, "jma_msm", 4))


class GridCloudCacheFailureTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.cache = GridCloudCache(cache_dir=self._tmp.name)

    def get(self, lat, model="jma_msm"):
        return self.cache.get_hourly(lat, 139.0, model, 4, "cloudcover")

    def patch_fetch(self, *outcomes):
        return mock.patch("grid_cache._fetch_hourly_detailed", side_effect=list(outcomes))

    def test_failure_recorded_and_not_retried(self):
        fail = cloud_forecast.FetchOutcome(None, reason="ConnectionError: x")
        with self.patch_fetch(fail) as f:
            self.assertIsNone(self.get(35.0))
            self.assertIsNone(self.get(35.0))  # 同一セルの再要求は再試行しない
        self.assertEqual(f.call_count, 1)
        self.assertEqual(len(self.cache.failures), 1)
        self.assertEqual(self.cache.failures[0].model, "jma_msm")
        self.assertEqual(self.cache.failures[0].reason, "ConnectionError: x")
        self.assertEqual(list(Path(self._tmp.name).glob("*.json")), [])  # 失敗は永続化しない

    def test_429_raises_and_flags(self):
        limit = cloud_forecast.FetchOutcome(None, reason="HTTP 429 (daily limit)", rate_limited=True)
        with self.patch_fetch(limit):
            with self.assertRaises(cloud_forecast.OpenMeteoDailyLimitError):
                self.get(35.0)
        self.assertTrue(self.cache.rate_limited)
        self.assertEqual(self.cache.summary().status, "abort")

    def test_summary_counts_disk_hits_as_success(self):
        ok = cloud_forecast.FetchOutcome(OK_HOURLY)
        with self.patch_fetch(ok):
            self.get(35.0)
        second = GridCloudCache(cache_dir=self._tmp.name)  # 別プロセス相当(ディスクキャッシュ)
        second.get_hourly(35.0, 139.0, "jma_msm", 4, "cloudcover")
        s = second.summary()
        self.assertEqual((s.total_cells, s.api_calls, s.failed), (1, 0, 0))
        self.assertEqual(s.status, "ok")


class SummaryStatusTest(unittest.TestCase):
    def status(self, total, failed, rate_limited=False):
        return FetchSummary(total, total, 0, failed, rate_limited).status

    def test_boundaries(self):
        self.assertEqual(self.status(100, 0), "ok")
        self.assertEqual(self.status(0, 0), "ok")
        self.assertEqual(self.status(1000, 199), "partial")   # 19.9%
        self.assertEqual(self.status(100, 20), "abort")       # 20%
        self.assertEqual(self.status(10, 10), "abort")        # 全滅
        self.assertEqual(self.status(100, 1, rate_limited=True), "abort")

    def test_threshold_constant(self):
        self.assertEqual(grid_cache.FAILED_CELL_RATE_ABORT, 0.20)



class FetchWarningRenderTest(unittest.TestCase):
    def test_warning_text_and_counts(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        import generate_report  # noqa: E402
        html_out = generate_report.render_fetch_warning(FetchSummary(50, 50, 0, 5, False))
        self.assertIn("一部の予報が取得できていない", html_out)
        self.assertIn("50件中5件", html_out)

    def test_warning_has_no_timing(self):
        # 時間の計測は画面表示だけで、レポート(HTML)には出さない
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        import generate_report  # noqa: E402
        s = FetchSummary(50, 50, 0, 5, False, fetch_sec=12.3, retries=2, failed_attempt_sec=4.5)
        html_out = generate_report.render_fetch_warning(s)
        self.assertNotIn("通信", html_out)
        self.assertNotIn("12.3", html_out)


@mock.patch("cloud_forecast.time.sleep")
class SessionReuseTest(unittest.TestCase):
    """接続の使い回し(2026-11-12): 1つの requests.Session をプロセスの中で使い回す。"""

    def setUp(self):
        patcher = mock.patch.object(cloud_forecast, "_SESSION", None)  # 作り直しから始め、終わったら元に戻す
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_same_session_for_two_fetches(self, _sleep):
        with mock.patch("requests.Session.get", autospec=True, return_value=_resp(200)) as g:
            cloud_forecast._fetch_hourly_detailed(35.0, 139.0, "jma_msm", 4)
            cloud_forecast._fetch_hourly_detailed(36.0, 140.0, "ecmwf_ifs025", 15)
        self.assertEqual(g.call_count, 2)
        first, second = (c.args[0] for c in g.call_args_list)  # autospec なので self(Session)が先頭に入る
        self.assertIsInstance(first, requests.Session)
        self.assertIs(first, second)

    def test_user_agent_is_sent(self, _sleep):
        with mock.patch("requests.Session.get", autospec=True, return_value=_resp(200)) as g:
            cloud_forecast._fetch_hourly_detailed(35.0, 139.0, "jma_msm", 4)
        session = g.call_args.args[0]
        self.assertEqual(session.headers["User-Agent"], cloud_forecast._USER_AGENT)
        self.assertEqual(g.call_args.kwargs["headers"]["User-Agent"], cloud_forecast._USER_AGENT)
        self.assertIn("hoshibiyori", cloud_forecast._USER_AGENT)

    def test_url_params_timeout_unchanged(self, _sleep):
        with mock.patch("requests.Session.get", autospec=True, return_value=_resp(200)) as g:
            cloud_forecast._fetch_hourly_detailed(35.0, 139.0, "jma_msm", 4, variables="cloudcover")
        self.assertEqual(g.call_args.args[1], "https://api.open-meteo.com/v1/forecast")
        self.assertEqual(g.call_args.kwargs["timeout"], 20)
        self.assertEqual(g.call_args.kwargs["params"], {
            "latitude": 35.0, "longitude": 139.0, "hourly": "cloudcover", "models": "jma_msm",
            "forecast_days": 4, "timezone": "Asia/Tokyo"})


@mock.patch("cloud_forecast.time.sleep")
class FetchTimingTest(unittest.TestCase):
    """時間の計測(2026-11-12)。時計(cloud_forecast._clock)を差し替える。"""

    def run_with_clock(self, ticks, get_kwargs):
        with mock.patch("cloud_forecast._clock", side_effect=ticks), \
                mock.patch("requests.Session.get", **get_kwargs):
            return cloud_forecast._fetch_hourly_detailed(35.0, 139.0, "jma_msm", 4)

    def test_success_first_try(self, _sleep):
        # t0=100, 試行開始=100, 成功の返却=100.5
        out = self.run_with_clock([100.0, 100.0, 100.5], {"return_value": _resp(200)})
        self.assertEqual(out.attempts, 1)
        self.assertAlmostEqual(out.elapsed_sec, 0.5)
        self.assertAlmostEqual(out.failed_attempt_sec, 0.0)

    def test_failure_then_success(self, _sleep):
        # 1回目: 0→20(失敗、20秒)、待ち2秒、2回目: 22→23(成功)。全体23秒、失敗の試行20秒
        out = self.run_with_clock([0.0, 0.0, 20.0, 22.0, 23.0],
                                  {"side_effect": [requests.ConnectionError("x"), _resp(200)]})
        self.assertEqual(out.hourly, OK_HOURLY)
        self.assertEqual(out.attempts, 2)
        self.assertAlmostEqual(out.elapsed_sec, 23.0)
        self.assertAlmostEqual(out.failed_attempt_sec, 20.0)

    def test_429_counts_as_failed_attempt(self, _sleep):
        out = self.run_with_clock([0.0, 0.0, 0.4, 0.4], {"return_value": _resp(429)})
        self.assertTrue(out.rate_limited)
        self.assertEqual(out.attempts, 1)
        self.assertAlmostEqual(out.failed_attempt_sec, 0.4)


class GridCacheTimingTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.cache = GridCloudCache(cache_dir=self._tmp.name)

    def test_summary_and_console_line(self):
        outcomes = [
            cloud_forecast.FetchOutcome(OK_HOURLY, attempts=2, elapsed_sec=23.0, failed_attempt_sec=20.0),
            cloud_forecast.FetchOutcome(OK_HOURLY, attempts=1, elapsed_sec=0.6, failed_attempt_sec=0.0),
        ]
        with mock.patch("grid_cache._fetch_hourly_detailed", side_effect=outcomes):
            self.cache.get_hourly(35.0, 139.0, "jma_msm", 4, "cloudcover")
            self.cache.get_hourly(36.0, 139.0, "jma_msm", 4, "cloudcover")
            self.cache.get_hourly(36.0, 139.0, "jma_msm", 4, "cloudcover")  # メモリキャッシュ(時間は数えない)
        s = self.cache.summary()
        self.assertAlmostEqual(s.fetch_sec, 23.6)
        self.assertEqual(s.retries, 1)
        self.assertAlmostEqual(s.failed_attempt_sec, 20.0)
        line = s.console_line()
        self.assertTrue(line.startswith("取得セル2件 / API呼び出し2回 / キャッシュヒット1回 / 失敗0件(0.0%)"))
        self.assertTrue(line.endswith(" / 通信 23.6 秒(うち失敗の待ち 20.0 秒・再試行 1 回)"))

    def test_timing_kept_on_429(self):
        limit = cloud_forecast.FetchOutcome(None, reason="HTTP 429 (daily limit)", rate_limited=True,
                                            attempts=1, elapsed_sec=0.3, failed_attempt_sec=0.3)
        with mock.patch("grid_cache._fetch_hourly_detailed", side_effect=[limit]):
            with self.assertRaises(cloud_forecast.OpenMeteoDailyLimitError):
                self.cache.get_hourly(35.0, 139.0, "jma_msm", 4, "cloudcover")
        s = self.cache.summary()
        self.assertAlmostEqual(s.fetch_sec, 0.3)
        self.assertAlmostEqual(s.failed_attempt_sec, 0.3)

    def test_legacy_positional_summary_defaults(self):
        s = FetchSummary(10, 10, 0, 0, False)
        self.assertEqual((s.fetch_sec, s.retries, s.failed_attempt_sec), (0.0, 0, 0.0))
        self.assertIn("通信 0.0 秒(うち失敗の待ち 0.0 秒・再試行 0 回)", s.console_line())

    def test_timing_line(self):
        s = FetchSummary(10, 10, 0, 0, False, fetch_sec=40.0)
        self.assertEqual(grid_cache.timing_line(100.0, s),
                         "実行時間の内訳: 全体 100.0 秒 / Open-Meteoの通信 40.0 秒 / 通信以外 60.0 秒(全体 − 通信)")


if __name__ == "__main__":
    unittest.main()
