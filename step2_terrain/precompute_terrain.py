"""星の日和(hoshibiyori) ステップ2拡張: stargazing_spots.jsonのspots配列(curated由来)に対する
地形地平線プロファイルのバッチ計算。

対象は spots配列のうち horizon_profile が未設定(null)のエントリのみ(2026-09-06時点で84件中81件、
精進湖 他手合浜・石廊崎・ヘブンスそのはらの3件は既にcandidate_sites.db統合時にhorizon_profileが
設定済みのため自動的にスキップされる)。viewpoint_reference配列(OSM由来751件)は対象外。

各地点の観測者標高は、curated由来データが標高情報を持たないため、地形計算と同じGSI DEMタイルから
その地点自体の標高を取得して用いる(地形プロファイルと観測者標高の基準を一致させるため)。

処理順序: 緯度経度を0.5度グリッドでまとめ、近接する地点をまとめて処理することで、
同一DEMタイルの再利用(ディスクキャッシュヒット)を最大化し、新規タイルダウンロード量を抑える。

中断・再開: 1地点処理するごとにCSV出力とstargazing_spots.json更新の両方を都度書き込むため、
中断しても再実行すればhorizon_profileが未設定(null)の残り分から自動的に再開できる。

DEMデータ出典: 国土地理院 地理院タイル(標高タイル) https://cyberjapandata.gsi.go.jp/
  既存のgsi_dem.DemTileStoreが実装するポライトネス・ディレイ/ディスクキャッシュの方針(CLAUDE.md参照)を
  そのまま利用する(本スクリプト側で変更・短縮しない)。
"""
from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path

from gsi_dem import ATTRIBUTION, DemTileStore
from horizon_profile import compute_horizon_profile

ROOT = Path(__file__).parent.parent
STARGAZING_SPOTS_PATH = ROOT / "stargazing_spots.json"
TERRAIN_DIR = Path(__file__).parent
CACHE_DIR = TERRAIN_DIR / "dem_cache"

MAX_DISTANCE_KM = 50.0
STEP_M = 100.0
REFRACTION_K = 0.13


def slug_for(spot_id: str) -> str:
    """'curated:028' -> 'curated028' (ファイル名に使える単純なスラッグ)。"""
    return spot_id.replace(":", "").replace(" ", "")


def csv_relpath_for(spot_id: str) -> str:
    return f"step2_terrain/horizon_{slug_for(spot_id)}_50km.csv"


def load_spots_data() -> dict:
    with open(STARGAZING_SPOTS_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_spots_data(data: dict) -> None:
    with open(STARGAZING_SPOTS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def geographic_sort_key(spot: dict) -> tuple:
    # 0.5度グリッド(緯度経度とも約50km四方)でまとめ、同グリッド内は緯度→経度の順。
    # 近接地点を連続処理することでDEMタイルキャッシュのヒット率を上げる狙い。
    return (round(spot["lat"] * 2) / 2, round(spot["lon"] * 2) / 2, spot["lat"], spot["lon"])


def write_horizon_csv(path: Path, name: str, lat: float, lon: float, elevation_m: float,
                       results: list[tuple[int, float, float | None]]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        f.write(f"# {ATTRIBUTION}\n")
        f.write(f"# 地点: {name} (緯度{lat}, 経度{lon}, 観測者標高{elevation_m:.1f}m [DEMタイルから自動取得])\n")
        writer = csv.writer(f)
        writer.writerow(["azimuth_deg", "horizon_altitude_deg", "distance_of_max_m"])
        for az, angle, dist in results:
            writer.writerow([az, f"{angle:.3f}", "" if dist is None else int(dist)])


def process_one(spot: dict, store: DemTileStore) -> tuple[float, list[tuple[int, float, float | None]]]:
    lat, lon = spot["lat"], spot["lon"]
    elevation_m = store.get_elevation(lat, lon)
    if elevation_m is None:
        elevation_m = 0.0  # タイル取得失敗時のフォールバック(海面扱い)
    results = compute_horizon_profile(
        lat=lat, lon=lon, observer_elevation_m=elevation_m,
        max_distance_m=MAX_DISTANCE_KM * 1000.0, step_m=STEP_M, refraction_k=REFRACTION_K,
        store=store, progress=False,
    )
    return elevation_m, results


def new_store() -> DemTileStore:
    """地点ごとに新規のDemTileStoreを作る。

    DemTileStoreはタイルをプロセスメモリ上にも際限なくキャッシュし続ける実装
    (_mem_cache、エビクションなし)のため、全国に散らばる81地点分をまたいで単一の
    インスタンスを使い回すと、地点間で重ならないタイル群が積み上がり続けてメモリを
    圧迫する(実際に長時間バッチ実行中にOOMでプロセスがkillされる事象が発生した)。
    ディスクキャッシュ(dem_cache/)は地点をまたいで共有され続けるため、地点ごとに
    メモリキャッシュだけリセットしても速度上のデメリットはほぼ無い。
    """
    return DemTileStore(cache_dir=str(CACHE_DIR), dataset="dem")


def main() -> None:
    parser = argparse.ArgumentParser(description="stargazing_spots.json spots配列の地形地平線プロファイル一括計算")
    parser.add_argument("--limit", type=int, default=None, help="処理件数の上限(試験実行用)")
    args = parser.parse_args()

    data = load_spots_data()
    spots = data["spots"]
    todo = [s for s in spots if s.get("horizon_profile") is None]
    todo.sort(key=geographic_sort_key)

    total_target = len(todo)
    if args.limit:
        todo = todo[: args.limit]

    print(ATTRIBUTION, flush=True)
    print(f"対象: spots配列{len(spots)}件のうちhorizon_profile未設定の{total_target}件"
          f"{f'(今回は先頭{len(todo)}件のみ試験実行)' if args.limit else ''}", flush=True)
    print("処理順序: 0.5度グリッドで近接地点をまとめ、DEMタイルキャッシュ再利用を優先\n", flush=True)

    times: list[float] = []
    total_dl = total_cache = total_failed = 0
    t_batch_start = time.time()

    for i, spot in enumerate(todo, 1):
        store = new_store()  # 地点ごとに新規インスタンス(メモリキャッシュの無限増大を防ぐ。上記new_store()参照)
        t0 = time.time()
        elevation_m, results = process_one(spot, store)
        elapsed = time.time() - t0
        times.append(elapsed)

        rel_path = csv_relpath_for(spot["id"])
        write_horizon_csv(TERRAIN_DIR / f"horizon_{slug_for(spot['id'])}_50km.csv",
                           spot["name"], spot["lat"], spot["lon"], elevation_m, results)

        for s in spots:
            if s["id"] == spot["id"]:
                s["horizon_profile"] = rel_path
                s["elevation_m"] = round(elevation_m, 2)
                break
        save_spots_data(data)

        total_dl += store.downloaded_count
        total_cache += store.cache_hit_count
        total_failed += store.failed_count
        del store  # このイテレーションのメモリキャッシュ(タイル実体)を明示的に解放

        avg = sum(times) / len(times)
        remaining = len(todo) - i
        eta_min = avg * remaining / 60.0

        print(f"[{i}/{len(todo)}] {spot['name']}（{spot['municipality']}） 完了"
              f"  所要{elapsed:.1f}秒  標高{elevation_m:.0f}m"
              f"  タイル(新規{total_dl}/キャッシュ{total_cache} 累計)"
              f"  平均{avg:.1f}秒/件  残り推定{eta_min:.1f}分", flush=True)

    t_batch_end = time.time()
    print(f"\n完了。{len(todo)}件処理(全体対象{total_target}件中)。"
          f"合計所要時間 {(t_batch_end - t_batch_start)/60:.1f}分")
    print(f"タイル取得統計(累計): 新規{total_dl} / キャッシュ{total_cache} / 失敗{total_failed}")


if __name__ == "__main__":
    main()
