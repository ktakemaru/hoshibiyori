"""Black Marble の生タイル(HDF5)から 0.01度格子のスカイグロー指数(ALR)を作る(段階LP1)。

HDF5の読み込みに h5py が必要(requirements.txt には入れない。年1回の再生成のときだけ使う)。
Python 3.15 RC には h5py のwheelが無く、3.13 などで実行する(UPDATE.md 参照)。
計算本体は skyglow_bm.py(numpyのみ)。

    py -3.13 step3_light_pollution/build_skyglow_bm.py --product VNP46A4 --year 2025 \
        --out step3_light_pollution/data/skyglow_bm_2025.npz
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import skyglow_bm as sg  # noqa: E402

LAYER = "HDFEOS/GRIDS/VIIRS_Grid_DNB_2d/Data Fields/AllAngle_Composite_Snow_Free"
TILE_DEG = 10.0
TILE_N = 2400
CELL_DEG = TILE_DEG / TILE_N  # 15秒角


def mosaic(product_dir: Path, ext: dict):
    """入力範囲を覆うタイルをつなげ、範囲で切り出す。(array, lat_top, lon_left, 欠損数)を返す。"""
    import h5py  # 遅延import(計算だけの利用・テストでは不要)

    names = sg.tiles_for_extent(ext)
    files = {p.name.split(".")[2]: p for p in product_dir.glob("*.h5")}
    missing = [n for n in names if n not in files]
    if missing:
        raise SystemExit(f"タイルが足りない: {missing}(fetch_black_marble.py で取得する)")
    hs = sorted({int(n[1:3]) for n in names})
    vs = sorted({int(n[4:6]) for n in names})
    big = np.full((len(vs) * TILE_N, len(hs) * TILE_N), np.nan, dtype=np.float32)
    n_fill = 0
    for n in names:
        h, v = int(n[1:3]), int(n[4:6])
        with h5py.File(files[n], "r") as f:
            ds = f[LAYER]
            a = ds[...].astype(np.float32)
            fill = float(ds.attrs["_FillValue"][0])
        bad = a == fill
        n_fill += int(bad.sum())
        a[bad] = np.nan
        r0, c0 = vs.index(v) * TILE_N, hs.index(h) * TILE_N
        big[r0:r0 + TILE_N, c0:c0 + TILE_N] = a
    lon_left = hs[0] * TILE_DEG - 180.0
    lat_top = 90.0 - vs[0] * TILE_DEG
    c0 = max(int((ext["lon_min"] - lon_left) / CELL_DEG), 0)
    c1 = min(int(np.ceil((ext["lon_max"] - lon_left) / CELL_DEG)), big.shape[1])
    r0 = max(int((lat_top - ext["lat_max"]) / CELL_DEG), 0)
    r1 = min(int(np.ceil((lat_top - ext["lat_min"]) / CELL_DEG)), big.shape[0])
    return big[r0:r1, c0:c1], lat_top - r0 * CELL_DEG, lon_left + c0 * CELL_DEG, n_fill


def build(product: str, year: int, cache_root: Path, ext_in: dict, ext_out: dict):
    t0 = time.time()
    arr, lat_top, lon_left, n_fill = mosaic(cache_root / product / str(year), ext_in)
    n_nan = int(np.isnan(arr).sum())
    geom = sg.plane_geometry_for_extent(ext_in)
    src = sg.to_plane(arr, lat_top, lon_left, CELL_DEG, CELL_DEG, geom)
    t1 = time.time()
    alr_plane = sg.alr_from_sum(sg.neighborhood_sum(src, geom.pixel_km))
    t2 = time.time()
    step = sg.OUTPUT_STEP_DEG
    out_lat_top = np.ceil(ext_out["lat_max"] / step) * step
    out_lon_left = np.floor(ext_out["lon_min"] / step) * step
    ny = int(round((out_lat_top - ext_out["lat_min"]) / step)) + 1
    nx = int(round((ext_out["lon_max"] - out_lon_left) / step)) + 1
    lats = out_lat_top - np.arange(ny) * step
    lons = out_lon_left + np.arange(nx) * step
    la, lo = np.meshgrid(lats, lons, indexing="ij")
    grid = sg.sample_plane(alr_plane, geom, la, lo).astype(np.float32)
    meta = {
        "schema": "hoshibiyori-skyglow-bm/1",
        "product": product, "year": year, "layer": "AllAngle_Composite_Snow_Free",
        "built": date.today().isoformat(),
        "method": "Duriscoe et al. 2018 (J. Quant. Spectrosc. Radiat. Transf. 214, 133-145) eq.9/11; see METHOD.md",
        "units": "ALR(全天の人工スカイグロー/自然の背景)。日本では未較正のため相対指数として扱う",
        "constants": {"alpha": "2.3*(d/350)^0.28", "radius_km": sg.RADIUS_KM, "noise_clip_nw": sg.NOISE_CLIP_NW,
                      "C": sg.ALR_CALIBRATION_C, "plane_pixel_km": sg.PLANE_PIXEL_KM,
                      "d_min_km_UNCALIBRATED": sg.D_MIN_KM},
        "input_extent": ext_in, "output_extent": ext_out,
        "input_fill_pixels": n_fill, "input_nan_after_mosaic": n_nan,
        "seconds": {"to_plane": round(t1 - t0, 1), "convolve": round(t2 - t1, 1)},
    }
    return grid, {"lat_top": float(out_lat_top), "lon_left": float(out_lon_left), "step": step, "meta": meta}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--product", default="VNP46A4")
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--cache", type=Path, default=HERE / "blackmarble_cache")
    args = ap.parse_args()
    grid, info = build(args.product, args.year, args.cache, sg.input_extent(), sg.output_extent())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(args.out, alr=np.round(grid, 5), lat_top=info["lat_top"], lon_left=info["lon_left"],
                        step=info["step"], meta=json.dumps(info["meta"], ensure_ascii=False))
    print(f"{args.out} {args.out.stat().st_size/1e6:.2f}MB shape={grid.shape} "
          f"min={np.nanmin(grid):.4f} median={np.nanmedian(grid):.4f} max={np.nanmax(grid):.2f}")
    print(json.dumps(info["meta"]["seconds"]), "fill", info["meta"]["input_fill_pixels"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
