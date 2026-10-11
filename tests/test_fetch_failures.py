"""取得失敗の扱い(cloud_forecast._fetch_hourly_detailed / grid_cache.GridCloudCache)の単体テスト。
ネットワークは使わない(requests.get と time.sleep をモックする)。

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
        with mock.patch("cloud_forecast.requests.get", return_value=_resp(200)) as g:
            out = self.call()
        self.assertEqual(out.hourly, OK_HOURLY)
        self.assertIsNone(out.reason)
        self.assertFalse(out.rate_limited)
        self.assertEqual(g.call_count, 1)

    def test_429_is_not_retried(self, sleep):
        with mock.patch("cloud_forecast.requests.get", return_value=_resp(429)) as g:
            out = self.call()
        self.assertIsNone(out.hourly)
        self.assertTrue(out.rate_limited)
        self.assertIn("429", out.reason)
        self.assertEqual(g.call_count, 1)
        sleep.assert_not_called()

    def test_500_then_success(self, sleep):
        with mock.patch("cloud_forecast.requests.get", side_effect=[_resp(500), _resp(500), _resp(200)]) as g:
            out = self.call()
        self.assertEqual(out.hourly, OK_HOURLY)
        self.assertEqual(g.call_count, 3)
        self.assertEqual(sleep.call_count, 2)

    def test_connection_error_three_times(self, _sleep):
        with mock.patch("cloud_forecast.requests.get", side_effect=requests.ConnectionError("boom")) as g:
            out = self.call()
        self.assertIsNone(out.hourly)
        self.assertFalse(out.rate_limited)
        self.assertIn("ConnectionError", out.reason)
        self.assertEqual(g.call_count, 3)

    def test_legacy_wrapper_returns_none_on_failure(self, _sleep):
        with mock.patch("cloud_forecast.requests.get", side_effect=requests.ConnectionError("x")):
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


if __name__ == "__main__":
    unittest.main()
