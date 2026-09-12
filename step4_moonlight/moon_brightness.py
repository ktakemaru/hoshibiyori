"""星の日和(hoshibiyori) ステップ4: 月明かりによる空の明るさ増加モデルの検証。

Krisciunas & Schaefer (1991), "A model of the sky brightness with moonlight"
(PASP 103, 1033) の天頂輝度モデルを実装する。

このモデルは本来、空の任意の方向(天頂距離Z)について、月からの角距離ρに応じた
散乱光を計算するものだが、本プロジェクトのステップ3(光害データ)が天頂方向の
輝度(zenith brightness)のみを扱っているため、ここでも評価点を天頂(Z=0)に
固定して計算する。この場合 ρ(月と評価点の角距離)は月の天頂距離に等しくなる
(ρ = 90° - 月の高度)。

単位系: 空の明るさは mag/arcsec^2 (等級/平方秒角) で扱うが、光害由来の背景輝度と
月明かり由来の輝度は「線形の明るさ(nanoLambert)」に変換してから加算し、
その合計を再び mag/arcsec^2 に戻す。等級は対数スケールのため、単純な引き算・
足し算では正しく合成できないことに注意(このため線形変換を経由する)。
"""
from __future__ import annotations

import math
from dataclasses import dataclass

# mag/arcsec^2 <-> nanoLambert(nL) 変換定数(K&S 1991 / Garstang由来の標準定数)
_B_CONST_A = 34.08
_B_CONST_B = 20.7233
_B_CONST_C = 0.92104  # = ln(10)/2.5


def mag_to_nl(mpsas: float) -> float:
    """mag/arcsec^2 を nanoLambert(線形輝度)に変換する。"""
    return _B_CONST_A * math.exp(_B_CONST_B - _B_CONST_C * mpsas)


def nl_to_mag(nl: float) -> float:
    """nanoLambert(線形輝度)を mag/arcsec^2 に変換する。"""
    if nl <= 0:
        return float("inf")  # 輝度ゼロ = 無限に暗い(理論上の値)
    return (_B_CONST_B - math.log(nl / _B_CONST_A)) / _B_CONST_C


def _airmass(zenith_angle_deg: float) -> float:
    """K&S1991のエアマス近似式。天頂距離90度以上(地平線下)はNoneを返す。"""
    z = math.radians(zenith_angle_deg)
    sin_z = math.sin(z)
    value = 1.0 - 0.96 * sin_z * sin_z
    if value <= 0:
        return float("inf")
    return 1.0 / math.sqrt(value)


def _moon_illuminance_term(phase_angle_deg: float) -> float:
    """月の位相角(0=満月, 180=新月)から相対照度 I* を計算する(K&S1991 式)。"""
    alpha = abs(phase_angle_deg)
    exponent = -0.4 * (3.84 + 0.026 * alpha + 4e-9 * alpha ** 4)
    return 10 ** exponent


def _scattering_function(rho_deg: float) -> float:
    """月からの角距離rho(度)における散乱関数 f(rho)(K&S1991 式、レイリー+ミー散乱)。"""
    rho = math.radians(rho_deg)
    rayleigh = 10 ** 5.36 * (1.06 + math.cos(rho) ** 2)
    mie = 10 ** (6.15 - rho_deg / 40.0)
    return rayleigh + mie


@dataclass
class MoonBrightnessResult:
    moon_alt_deg: float
    moon_phase_angle_deg: float
    moon_brightness_nl: float  # 月明かりによる天頂輝度増加分(nanoLambert)
    moon_brightness_mag_equivalent: float | None  # 参考: 月明かり単独をmagに換算した値(背景ゼロ相当時)


def moon_zenith_brightness_nl(
    moon_alt_deg: float,
    moon_phase_angle_deg: float,
    extinction_k: float = 0.172,
) -> float:
    """天頂における月明かりの輝度増加分(nanoLambert)を返す。

    moon_alt_deg: 月の高度(度)。地平線下(負値)なら0.0を返す。
    moon_phase_angle_deg: 月の位相角(度)。0=満月, 180=新月。
    extinction_k: 大気減光係数(mag/airmass)。晴天時の標準的な値として0.172(V帯)を既定とする。
    """
    if moon_alt_deg <= 0:
        return 0.0

    z_moon = 90.0 - moon_alt_deg  # 月の天頂距離
    rho = z_moon  # 評価点を天頂(Z=0)に固定しているため、rho = 月の天頂距離
    z_eval = 0.0  # 評価点(天頂)の天頂距離

    x_moon = _airmass(z_moon)
    x_eval = _airmass(z_eval)  # = 1.0 (天頂なので)

    i_star = _moon_illuminance_term(moon_phase_angle_deg)
    f_rho = _scattering_function(rho)

    brightness = (
        f_rho
        * i_star
        * 10 ** (-0.4 * extinction_k * x_moon)
        * (1.0 - 10 ** (-0.4 * extinction_k * x_eval))
    )
    return brightness


def combine_sky_brightness(
    background_mpsas: float,
    moon_alt_deg: float,
    moon_phase_angle_deg: float,
    extinction_k: float = 0.172,
) -> dict:
    """光害由来の背景輝度(mag/arcsec^2)と月明かりを線形輝度で合算し、
    実効的な空の明るさ(mag/arcsec^2)を返す。

    戻り値には内訳(背景輝度、月輝度、合計)もnanoLambert単位で含める。
    """
    background_nl = mag_to_nl(background_mpsas)
    moon_nl = moon_zenith_brightness_nl(moon_alt_deg, moon_phase_angle_deg, extinction_k)
    total_nl = background_nl + moon_nl
    effective_mpsas = nl_to_mag(total_nl)

    return {
        "background_mpsas": background_mpsas,
        "background_nl": background_nl,
        "moon_alt_deg": moon_alt_deg,
        "moon_phase_angle_deg": moon_phase_angle_deg,
        "moon_nl": moon_nl,
        "total_nl": total_nl,
        "effective_mpsas": effective_mpsas,
        "delta_mag": background_mpsas - effective_mpsas,  # 正の値 = 月明かりで空が明るくなった量
    }
