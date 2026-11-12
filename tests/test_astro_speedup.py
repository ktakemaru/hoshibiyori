"""通信以外の処理時間の短縮(2026-11-12)の単体テスト(通信しない)。

- 配列でまとめた月の判定(_moon_negligible_flags)が、1時刻ずつの compute_moon_position と同じ判定を返す
- 同じ引数なら同じ値、違う地点・違う夜で値が混ざらない
天文計算は step1_astronomy/de421.bsp が無い環境ではスキップする。
"""
import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import explore_hoshibiyori as ex  # noqa: E402

JST = timezone(timedelta(hours=9))
BSP = ROOT / "step1_astronomy" / "de421.bsp"

SITE_A = {"name": "A", "lat": 34.60, "lon": 138.85, "elevation_m": 60.0}    # 石廊崎付近
SITE_B = {"name": "B", "lat": 36.80, "lon": 139.42, "elevation_m": 1400.0}  # 戦場ヶ原付近


@unittest.skipUnless(BSP.exists(), "de421.bsp が無い環境では天文計算のテストをスキップ")
class MoonFlagsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ts = ex.load.timescale()
        cls.eph = ex.load(str(BSP))

    def _times(self, start, hours=12):
        return [start + timedelta(minutes=15 * i) for i in range(hours * 4 + 1)]

    def test_same_as_scalar_compute_moon_position(self):
        # 満月前後・新月前後・半月を含む夜で、1時刻ずつの計算と判定が一致する
        for d in (date(2026, 11, 3), date(2026, 11, 10), date(2026, 11, 17), date(2026, 11, 24)):
            start = datetime(d.year, d.month, d.day, 18, 0, tzinfo=JST)
            times = self._times(start)
            for site in (SITE_A, SITE_B):
                got = ex._moon_negligible_flags(self.ts, self.eph, site["lat"], site["lon"], times)
                want = []
                for t in times:
                    m = ex.compute_moon_position(self.ts, self.eph, site["lat"], site["lon"], 0.0, t)
                    want.append(m.alt_deg <= 0 or m.phase_angle_deg >= ex.MOON_PHASE_NEGLIGIBLE_DEG)
                self.assertEqual(got, want, f"{site['name']} {d}")

    def test_empty(self):
        self.assertEqual(ex._moon_negligible_flags(self.ts, self.eph, 35.0, 139.0, []), [])

    def test_same_args_same_value_and_no_mixing(self):
        a1 = ex.compute_site_night_window(self.ts, self.eph, SITE_A, date(2026, 11, 20))
        a2 = ex.compute_site_night_window(self.ts, self.eph, SITE_A, date(2026, 11, 20))
        self.assertEqual(a1, a2)
        b = ex.compute_site_night_window(self.ts, self.eph, SITE_B, date(2026, 11, 20))
        a_other_night = ex.compute_site_night_window(self.ts, self.eph, SITE_A, date(2026, 11, 21))
        self.assertNotEqual(a1, b)
        self.assertNotEqual(a1, a_other_night)
        # 呼び出しの順番に依存しない(Bや別の夜を挟んでも同じ値)
        self.assertEqual(ex.compute_site_night_window(self.ts, self.eph, SITE_A, date(2026, 11, 20)), a1)


class ParsedCloudMemoTests(unittest.TestCase):
    """_to_dict_by_time_cached: 同じ時系列オブジェクトなら同じ変換結果、違うセル・違うキャッシュで混ざらない。"""

    def setUp(self):
        sys.path.insert(0, str(ROOT / "step5_cloud_forecast"))
        import elevation_cloud as ec
        self.ec = ec

    def _hourly(self, base):
        times = [f"2026-11-20T{h:02d}:00" for h in range(24)]
        h = {"time": times}
        for var in self.ec.level_hourly_vars().split(","):
            h[var] = [float(base + i) for i in range(24)]
        return h

    def test_same_object_same_value(self):
        class C:
            pass
        cache, hourly = C(), self._hourly(1)
        a = self.ec._to_dict_by_time_cached(cache, hourly)
        b = self.ec._to_dict_by_time_cached(cache, hourly)
        self.assertIs(a, b)
        self.assertEqual(a.keys(), self.ec._to_dict_by_time(hourly).keys())
        for k, v in self.ec._to_dict_by_time(hourly).items():
            self.assertEqual(a[k], v)

    def test_no_mixing_between_cells_and_caches(self):
        class C:
            pass
        cache = C()
        h1, h2 = self._hourly(1), self._hourly(50)
        p1 = self.ec._to_dict_by_time_cached(cache, h1)
        p2 = self.ec._to_dict_by_time_cached(cache, h2)
        k = next(iter(p1))
        self.assertNotEqual(p1[k].native, p2[k].native)
        self.assertEqual(p2[k].native, self.ec._to_dict_by_time(h2)[k].native)
        other = C()
        self.assertIsNot(self.ec._to_dict_by_time_cached(other, h1), p1)
        self.assertEqual(self.ec._to_dict_by_time_cached(cache, None), {})

    def test_get_level_cloud_forecast_unchanged(self):
        class FakeCache:
            def __init__(self, hourly):
                self.h = hourly

            def get_hourly(self, lat, lon, model, days, variables):
                return self.h if model == self.ec_msm else None
        FakeCache.ec_msm = self.ec.MSM_MODEL
        h = self._hourly(3)
        start = datetime(2026, 11, 20, 18, tzinfo=JST)
        end = datetime(2026, 11, 20, 23, tzinfo=JST)
        cache = FakeCache(h)
        first = self.ec.get_level_cloud_forecast(35.0, 139.0, start, end, cache=cache)
        second = self.ec.get_level_cloud_forecast(35.0, 139.0, start, end, cache=cache)
        self.assertEqual(first, second)
        self.assertEqual([x.cloud_total for x in first], [21.0, 22.0, 23.0, 24.0, 25.0, 26.0])


if __name__ == "__main__":
    unittest.main()
