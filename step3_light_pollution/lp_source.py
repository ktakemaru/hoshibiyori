"""光害の入力の切り替え(段階LP2): legacy(Lorenz氏のLight Pollution Atlas由来のLPI)と bm(Black Marble由来のALR)。

探索(explore_hoshibiyori.py)とレポート(generate_report.py)は `lp_store.get(lat, lon)` が返す値の
`brightness_ratio`(足切り `<= LPI_THRESHOLD` とスコアの減点に使う)と `mpsas`(月込みの実効的な空の明るさ)を読む。
bm の store も同じ形の値を返し、呼び出し側のしきい値判定・スコア式を変えずに入力だけを差し替える。

bm の `brightness_ratio` は **ALR を LPI_THRESHOLD/BM_ALR_THRESHOLD で線形に規格化した内部値**である。
こうすると「現行と同じコード `brightness_ratio <= LPI_THRESHOLD`」が `ALR <= BM_ALR_THRESHOLD` と完全に一致し、
スコアの光害減点(`値×10`)も閾値の位置で現行と同じ大きさになる(LPIの値は使わない=Lorenz氏のデータに依存しない)。
この内部値は画面に出さない。画面にはALRと順位(`rank_pct`)を出す。

`mpsas` と `bortle_approx` は None(新指数は日本向けの較正が無く、等級に換算できないため)。
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import skyglow_bm as sg  # noqa: E402

LP_SOURCES = ("legacy", "bm")
# 既定の入力(段階LP3で legacy から bm に切り替えた)。legacy は --lp-source legacy で引き続き使える。
DEFAULT_LP_SOURCE = "bm"

# 仮の閾値(段階LP2)。現行の `LPI <= 5.0` で通る主軸146件中の141件と同じ件数が通るALRの境界。
# 求め方: bm_threshold.py(ALRの141番目 10.3087 と142番目 11.0027 の中点 10.6557 を、区間内の丸めた値にした)。
# 論文Table 3(ALR>10)は日本に較正されていないので使っていない(参考値として併記するだけ)。
BM_ALR_THRESHOLD = 10.66
# 閾値を決めたときの通過件数N(現行LPI<=5.0で通った主軸146件中の件数)。段階LP3で stargazing_spots.json から lpi を外したため、
# 件数は固定値として持つ(根拠の再計算は bm_threshold.py。光害タイルが要る)。
BM_THRESHOLD_N_PASS = 141
# 規格化の基準。explore_hoshibiyori.LPI_THRESHOLD と同じ値でなければならない(単体テストで突き合わせる)。
LPI_THRESHOLD_REF = 5.0

BM_RELATIVE_NOTE = "ALRは日本で較正していない相対指数で、絶対値(空の明るさの等級)ではありません。順位や段階の目安として読んでください。"
# 順位への影響の注記(LP2の並べ比較。見込み/ECMWF、2026-10-31〜11-05の6夜、主軸146件)。
BM_RANK_NOTE = ("従来の入力(LPI)との比較では、見込みの上位10件のうち6件が共通で、上位2件は同じでした。"
                "入れ替わりは、光害の減点が2点前後違うだけで動く範囲(上位のスコアは約4.5点幅に密集)で、順位の差は小さいものです。")
BM_CITATION = ("光害 NASA Black Marble VNP46A4(DOI: 10.5067/VIIRS/VNP46A4.002、NASA主導ミッションのデータはCC0)を、"
               "Duriscoe et al. 2018(CC BY)の手法でスカイグロー指数に変換(相対指数)。"
               "引用: NASA VIIRS Land Science Investigator-led Processing System (2025), VIIRS/NPP Lunar BRDF-Adjusted "
               "Nighttime Lights Yearly L3 Global 15 arc second Linear Lat Lon Grid [Dataset], NASA LAADS DAAC, "
               "https://doi.org/10.5067/VIIRS/VNP46A4.002")

DEFAULT_GRID_PATH = sg.DATA_DIR / "skyglow_bm_2025.npz"


@dataclass(frozen=True)
class BmReading:
    """lp_store.get() の戻り値(LightPollutionResultと同じ名前の属性を持つ)。"""
    lat: float
    lon: float
    alr: float | None                 # 範囲外はNone
    rank_pct: float | None            # 主軸の地点の中で、このALR以下の地点の割合(0=最も暗い、100=最も明るい)
    brightness_ratio: float           # 内部値(足切り・減点用)。範囲外は inf(通過させない)
    mpsas: None = None
    bortle_approx: None = None


def reference_alr(grid: sg.DerivedGrid, spots_path: Path = sg.SPOTS_PATH) -> np.ndarray:
    spots = json.loads(Path(spots_path).read_text(encoding="utf-8"))["spots"]
    a = grid.at([s["lat"] for s in spots], [s["lon"] for s in spots])
    return np.sort(a[np.isfinite(a)])


class BmLightPollutionStore:
    def __init__(self, grid: sg.DerivedGrid | None = None, reference: np.ndarray | None = None,
                 alr_threshold: float = BM_ALR_THRESHOLD, lpi_threshold: float = LPI_THRESHOLD_REF):
        self.grid = grid or sg.DerivedGrid.load(DEFAULT_GRID_PATH)
        self.reference = np.sort(np.asarray(reference if reference is not None else reference_alr(self.grid), float))
        self.alr_threshold = alr_threshold
        self.scale = lpi_threshold / alr_threshold

    def get(self, lat: float, lon: float) -> BmReading:
        alr = float(self.grid.at(lat, lon))
        if not np.isfinite(alr):
            return BmReading(lat, lon, None, None, float("inf"))
        pct = 100.0 * float(np.searchsorted(self.reference, alr, side="right")) / len(self.reference)
        return BmReading(lat, lon, alr, pct, alr * self.scale)

    def site_type(self, lat: float, lon: float) -> str | None:
        """dark_sky / night_view(ALRが閾値を超える)。範囲外はNone。"""
        r = self.get(lat, lon)
        if r.alr is None:
            return None
        return "dark_sky" if r.alr <= self.alr_threshold else "night_view"


def describe_alr(alr: float | None, rank_pct: float | None) -> str:
    """画面用の短い表記。mpsas・ボートルは出さない。"""
    if alr is None:
        return "範囲外(未評価)"
    if rank_pct is None:
        return f"ALR {alr:.2f}"
    return f"ALR {alr:.2f}(主軸の地点のうち暗い方から{rank_pct:.0f}%)"
