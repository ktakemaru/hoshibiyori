"""天の川モードの計算の短縮(2026-11-27)の単体テスト(通信しない)。

- compute_target_window(時刻の列をまとめて計算)が、従来の1時刻ずつの計算(_compute_target_window_scalar)と
  値・型・表示(repr)まで同じ結果を返す。銀河中心が見える季節(春〜秋)の夜と、見えない冬の夜、地形データの有無の両方。
- まとめた計算と1時刻ずつの計算の差が、判定の切り替えの余裕(TARGET_TRACK_GUARD_DEG)より十分小さい。
- 余裕の中にサンプルがあれば、従来の計算に切り替わる(結果は同じ)。
- stage_outlook の戻り値の全件が、従来の計算に差し替えたときと同じ(夏の夜)。
- 時刻の列の使い回し(_sample_times)、聞かれた夜の保存の読み直しの省略(FetchedOnlyCache)、内訳の行。
天文計算は step1_astronomy/de421.bsp が無い環境ではスキップする。
"""
import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import explore_hoshibiyori as ex  # noqa: E402
import requested_nights as rn  # noqa: E402

JST = timezone(timedelta(hours=9))
BSP = ROOT / "step1_astronomy" / "de421.bsp"

# 銀河中心が見える季節の新月前後と、見えない冬の夜
NIGHTS = (date(2026, 4, 17), date(2026, 6, 15), date(2026, 7, 14), date(2026, 8, 12), date(2026, 12, 9))


class _NoCloudCache:
    """雲量の無いキャッシュ(stage_outlook の雲量は参考値なので、None でも候補は決まる)。"""

    def get_hourly(self, *a, **k):
        return None


def _sites():
    sites = ex.load_candidate_sites()
    with_profile = [s for s in sites if s["horizon_csv"]][:4]
    without = [s for s in sites if not s["horizon_csv"]][::150][:4]
    return with_profile + without


@unittest.skipUnless(BSP.exists(), "de421.bsp が無い環境では天文計算のテストをスキップ")
class TargetWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ts = ex.load.timescale()
        cls.eph = ex.load(str(BSP))
        cls.target = ex.get_target(ex.TARGET_ID)
        cls.sites = _sites()
        cls.cases = []
        for d in NIGHTS:
            for s in cls.sites:
                ds, de = ex.find_astro_dark_events(cls.ts, cls.eph, s["lat"], s["lon"],
                                                   datetime(d.year, d.month, d.day, tzinfo=JST))
                prof = ex.load_horizon_profile(s["horizon_csv"]) if s["horizon_csv"] else None
                cls.cases.append((d, s, ds, de, prof))

    def test_same_as_scalar(self):
        visible = 0
        for d, s, ds, de, prof in self.cases:
            got = ex.compute_target_window(self.ts, self.eph, s, self.target, ds, de, prof)
            want = ex._compute_target_window_scalar(self.ts, self.eph, s, self.target, ds, de, prof)
            self.assertEqual(got, want, f"{d} {s['name']}")
            self.assertEqual([type(x) for x in got], [type(x) for x in want], f"{d} {s['name']}")
            self.assertEqual(repr(got), repr(want), f"{d} {s['name']}")
            visible += got[0] is not None
        self.assertGreater(visible, 10)     # 見える場合を確かめている(冬の夜だけでない)

    def test_batch_difference_far_below_guard(self):
        from datetime import timezone as tz
        worst = 0.0
        for d, s, ds, de, prof in self.cases[::3]:
            times, t_sf = ex._sample_times(self.ts, ds, de, 15)
            az, alt = ex.altaz_at_time(t_sf, self.eph, s["lat"], s["lon"], s["elevation_m"], self.target)
            for i in range(0, len(times), 6):
                a1, l1 = ex.altaz_at_time(self.ts.from_datetime(times[i].astimezone(tz.utc)), self.eph,
                                          s["lat"], s["lon"], s["elevation_m"], self.target)
                worst = max(worst, abs(float(alt[i]) - float(l1)))
                daz = abs(float(az[i]) - float(a1))
                worst = max(worst, min(daz, 360.0 - daz))
        self.assertLess(worst, ex.TARGET_TRACK_GUARD_DEG / 1000.0)

    def test_fallback_inside_guard_gives_same_result(self):
        d, s, ds, de, prof = next(c for c in self.cases if c[1]["horizon_csv"] and c[0] == date(2026, 7, 14))
        before = ex.target_window_fallbacks
        with mock.patch.object(ex, "TARGET_TRACK_GUARD_DEG", 100.0):     # どのサンプルも余裕の中 → 必ず切り替え
            got = ex.compute_target_window(self.ts, self.eph, s, self.target, ds, de, prof)
        self.assertEqual(ex.target_window_fallbacks, before + 1)
        self.assertEqual(got, ex._compute_target_window_scalar(self.ts, self.eph, s, self.target, ds, de, prof))

    def test_empty_window(self):
        start = datetime(2026, 7, 14, 23, 0, tzinfo=JST)
        s = self.sites[0]
        self.assertEqual(ex.compute_target_window(self.ts, self.eph, s, self.target, start, start - timedelta(minutes=1), None),
                         (None, None, None, None, None))

    def test_stage_outlook_same_as_scalar(self):
        nights = [ex.NightCandidate(night_date=d, sunset=None, sunrise=None, dark_start=None, dark_end=None,
                                    window_start=None, window_end=None, moon_free_hours=0.0) for d in NIGHTS[1:4]]
        lp_store = ex.make_lp_store()
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):
            got = ex.stage_outlook(self.ts, self.eph, nights, self.sites, lp_store, _NoCloudCache(), "milkyway", None)
            with mock.patch.object(ex, "compute_target_window", ex._compute_target_window_scalar):
                want = ex.stage_outlook(self.ts, self.eph, nights, self.sites, lp_store, _NoCloudCache(), "milkyway", None)
        self.assertGreater(len(got), 0)
        self.assertEqual([repr(x) for x in got], [repr(x) for x in want])


@unittest.skipUnless(BSP.exists(), "de421.bsp が無い環境では天文計算のテストをスキップ")
class SampleTimesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ts = ex.load.timescale()

    def test_same_times_as_loop_and_reused(self):
        start = datetime(2026, 7, 14, 20, 3, tzinfo=JST)
        end = start + timedelta(hours=3, minutes=7)
        times, t_sf = ex._sample_times(self.ts, start, end, 15)
        want, t = [], start
        while t <= end:
            want.append(t)
            t += timedelta(minutes=15)
        self.assertEqual(times, want)
        self.assertEqual(list(t_sf.tt), list(self.ts.from_datetimes([x.astimezone(timezone.utc) for x in want]).tt))
        again = ex._sample_times(self.ts, start, end, 15)
        self.assertIs(again[1], t_sf)

    def test_timezone_is_part_of_key(self):
        start = datetime(2026, 7, 14, 20, 0, tzinfo=JST)
        end = start + timedelta(hours=1)
        jst_times, _ = ex._sample_times(self.ts, start, end, 15)
        utc_times, _ = ex._sample_times(self.ts, start.astimezone(timezone.utc), end.astimezone(timezone.utc), 15)
        self.assertEqual(jst_times, utc_times)                       # 同じ瞬間
        self.assertEqual(repr(jst_times[0].tzinfo), repr(JST))       # 表し方は混ざらない
        self.assertEqual(utc_times[0].tzinfo, timezone.utc)

    def test_memo_is_bounded(self):
        with mock.patch.object(ex, "_SAMPLE_TIMES_MEMO_MAX", 3):
            ex._SAMPLE_TIMES_MEMO.clear()
            start = datetime(2026, 7, 14, 20, 0, tzinfo=JST)
            for i in range(10):
                ex._sample_times(self.ts, start + timedelta(minutes=i), start + timedelta(hours=1), 15)
                self.assertLessEqual(len(ex._SAMPLE_TIMES_MEMO), 3)


class FetchedOnlyCacheDiskMemoTests(unittest.TestCase):
    def test_disk_read_once_per_key(self):
        reads = []

        class Fake:
            disk_cache_enabled = True
            _cache = {}

            def _read_disk(self, key, model):
                reads.append(key)
                return {"time": [], "model": model}     # 読むたびに新しいオブジェクト(実物と同じ)

        reader = rn.FetchedOnlyCache(Fake())
        a = reader.get_hourly(35.0, 139.0, "jma_msm", 4, "v")
        b = reader.get_hourly(35.0, 139.0, "jma_msm", 4, "v")
        c = reader.get_hourly(36.0, 139.0, "jma_msm", 4, "v")
        self.assertIs(a, b)
        self.assertIsNot(a, c)
        self.assertEqual(len(reads), 2)

    def test_missing_stays_missing(self):
        class Fake:
            disk_cache_enabled = True
            _cache = {}

            def _read_disk(self, key, model):
                return None

        reader = rn.FetchedOnlyCache(Fake())
        self.assertIsNone(reader.get_hourly(35.0, 139.0, "jma_msm", 4, "v"))
        self.assertIsNone(reader.get_hourly(35.0, 139.0, "jma_msm", 4, "v"))


class ComputeTimingLineTests(unittest.TestCase):
    def test_lines(self):
        self.assertIsNone(ex.compute_timing_line(None))
        self.assertIsNone(ex.compute_timing_line({}))
        self.assertEqual(ex.compute_timing_line({"outlook": 6.34}), "実行時間の内訳(計算): 見込みの計算 6.3 秒")
        self.assertEqual(ex.compute_timing_line({"outlook": 7.0, "requested_nights": 16.61}),
                         "実行時間の内訳(計算): 見込みの計算 7.0 秒 / 聞かれた夜(--nights)の計算 16.6 秒")


if __name__ == "__main__":
    unittest.main()
