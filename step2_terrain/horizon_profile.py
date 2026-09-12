"""星の日和(hoshibiyori) ステップ2: 地形地平線プロファイルの検証。

指定した地点(緯度・経度・観測者標高)を中心に、方位角0〜359度(1度刻み)
それぞれについて、その方向のDEM標高を一定距離までサンプリングし、
観測者から見た仰角(地球曲率+大気差補正込み)を計算する。
各方位角の最大仰角を「地平線の高さ」として記録し、360点のプロファイルを
CSV出力する。

DEMデータ出典: 国土地理院 地理院タイル(標高タイル) https://cyberjapandata.gsi.go.jp/
  -> 成果物の公開時は「出典:国土地理院」の表示を行うこと。詳細は CLAUDE.md 参照。
"""
from __future__ import annotations

import argparse
import csv
import math
import time

from geodesy import vincenty_direct
from gsi_dem import ATTRIBUTION, DemTileStore

EARTH_RADIUS_M = 6371000.0


def apparent_elevation_angle_deg(
    observer_elevation_m: float,
    target_elevation_m: float,
    distance_m: float,
    refraction_k: float,
) -> float:
    """地球曲率+大気差補正込みの、観測者から見た対象点の仰角(度)を返す。

    標準的な近似式: 見かけの降下量 drop = (1-k) * d^2 / (2R)
    (k: 大気差係数。標準的な値として 0.13 前後が使われる)
    """
    delta_h = target_elevation_m - observer_elevation_m
    drop = (1 - refraction_k) * distance_m * distance_m / (2 * EARTH_RADIUS_M)
    return math.degrees(math.atan2(delta_h - drop, distance_m))


def compute_horizon_profile(
    lat: float,
    lon: float,
    observer_elevation_m: float,
    max_distance_m: float,
    step_m: float,
    refraction_k: float,
    store: DemTileStore,
    progress: bool = True,
) -> list[tuple[int, float, float | None]]:
    distances = [step_m * i for i in range(1, int(max_distance_m // step_m) + 1)]
    results: list[tuple[int, float, float | None]] = []

    start_time = time.time()
    for az in range(360):
        best_angle = -90.0
        best_dist: float | None = None
        for d in distances:
            lat2, lon2 = vincenty_direct(lat, lon, az, d)
            elev = store.get_elevation(lat2, lon2)
            if elev is None:
                continue  # タイル取得失敗(通信エラー)。この点はスキップ
            angle = apparent_elevation_angle_deg(observer_elevation_m, elev, d, refraction_k)
            if angle > best_angle:
                best_angle = angle
                best_dist = d
        results.append((az, best_angle, best_dist))

        if progress and az % 30 == 0:
            elapsed = time.time() - start_time
            print(
                f"  方位角 {az:3d}° 処理中... "
                f"(タイル取得: 新規{store.downloaded_count} / キャッシュ{store.cache_hit_count} / "
                f"失敗{store.failed_count}, 経過{elapsed:.1f}秒)"
            )

    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="方位角ごとの地形地平線プロファイル(仰角)を計算する"
    )
    parser.add_argument("--lat", type=float, required=True, help="観測地点 緯度(度、北緯正)")
    parser.add_argument("--lon", type=float, required=True, help="観測地点 経度(度、東経正)")
    parser.add_argument("--elevation", type=float, required=True, help="観測者標高(m)")
    parser.add_argument("--name", type=str, default="観測地点", help="地点名")
    parser.add_argument("--max-distance-km", type=float, default=50.0, help="サンプリング最大距離(km)")
    parser.add_argument("--step-m", type=float, default=100.0, help="サンプリング間隔(m)")
    parser.add_argument("--refraction-k", type=float, default=0.13, help="大気差係数k(標準的な近似値)")
    parser.add_argument(
        "--dataset",
        type=str,
        default="dem",
        choices=["dem", "dem5a", "dem5b"],
        help="使用するDEMデータセット(既定: dem=10mメッシュ全国。5a/5bは5mメッシュだが提供範囲が限定的)",
    )
    parser.add_argument("--cache-dir", type=str, default="dem_cache", help="DEMタイルのディスクキャッシュ先")
    parser.add_argument("--output", type=str, default="horizon_profile.csv", help="出力CSVファイルパス")
    args = parser.parse_args()

    store = DemTileStore(cache_dir=args.cache_dir, dataset=args.dataset)

    print(f"=== {args.name} (緯度{args.lat:.4f}, 経度{args.lon:.4f}, 観測者標高{args.elevation:.0f}m) ===")
    print(f"最大距離: {args.max_distance_km}km, 間隔: {args.step_m}m, 大気差係数k={args.refraction_k}")
    print(f"DEMデータセット: {args.dataset}")
    print(f"{ATTRIBUTION}\n")

    results = compute_horizon_profile(
        lat=args.lat,
        lon=args.lon,
        observer_elevation_m=args.elevation,
        max_distance_m=args.max_distance_km * 1000.0,
        step_m=args.step_m,
        refraction_k=args.refraction_k,
        store=store,
    )

    with open(args.output, "w", newline="", encoding="utf-8") as f:
        f.write(f"# {ATTRIBUTION}\n")
        f.write(f"# 地点: {args.name} (緯度{args.lat}, 経度{args.lon}, 観測者標高{args.elevation}m)\n")
        writer = csv.writer(f)
        writer.writerow(["azimuth_deg", "horizon_altitude_deg", "distance_of_max_m"])
        for az, angle, dist in results:
            writer.writerow([az, f"{angle:.3f}", "" if dist is None else int(dist)])

    print(f"\n完了。360点のプロファイルを {args.output} に出力しました。")
    print(
        f"タイル取得統計: 新規ダウンロード {store.downloaded_count}件 / "
        f"キャッシュ利用 {store.cache_hit_count}件 / 失敗 {store.failed_count}件"
    )

    print("\n--- 抜粋(30度刻み) ---")
    print(f"{'方位角':>6} | {'地平線仰角(度)':>14} | {'距離(m)':>8}")
    for az, angle, dist in results:
        if az % 30 == 0:
            dist_str = "-" if dist is None else f"{dist:.0f}"
            print(f"{az:6d} | {angle:14.2f} | {dist_str:>8}")


if __name__ == "__main__":
    main()
