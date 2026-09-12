"""測地線(Vincenty法)による直接測位計算。

外部の地理系ライブラリ(pyproj等)を使わず、WGS84楕円体上での
「出発点+方位角+距離 -> 到達点(緯度経度)」を計算する。
"""
from __future__ import annotations

import math

# WGS84 楕円体パラメータ
_A = 6378137.0  # 長半径(m)
_F = 1 / 298.257223563  # 扁平率
_B = (1 - _F) * _A  # 短半径(m)


def vincenty_direct(lat1_deg: float, lon1_deg: float, azimuth_deg: float, distance_m: float) -> tuple[float, float]:
    """出発点(lat1, lon1)から方位角azimuth_degへdistance_m進んだ地点の緯度経度を返す。"""
    lat1 = math.radians(lat1_deg)
    lon1 = math.radians(lon1_deg)
    alpha1 = math.radians(azimuth_deg)

    sin_alpha1 = math.sin(alpha1)
    cos_alpha1 = math.cos(alpha1)

    tan_u1 = (1 - _F) * math.tan(lat1)
    cos_u1 = 1 / math.sqrt(1 + tan_u1 * tan_u1)
    sin_u1 = tan_u1 * cos_u1

    sigma1 = math.atan2(tan_u1, cos_alpha1)
    sin_alpha = cos_u1 * sin_alpha1
    cos_sq_alpha = 1 - sin_alpha * sin_alpha

    u_sq = cos_sq_alpha * (_A * _A - _B * _B) / (_B * _B)
    big_a = 1 + u_sq / 16384 * (4096 + u_sq * (-768 + u_sq * (320 - 175 * u_sq)))
    big_b = u_sq / 1024 * (256 + u_sq * (-128 + u_sq * (74 - 47 * u_sq)))

    sigma = distance_m / (_B * big_a)
    for _ in range(200):
        two_sigma_m = 2 * sigma1 + sigma
        delta_sigma = big_b * math.sin(sigma) * (
            math.cos(two_sigma_m) + big_b / 4 * (
                math.cos(sigma) * (-1 + 2 * math.cos(two_sigma_m) ** 2)
                - big_b / 6 * math.cos(two_sigma_m) * (-3 + 4 * math.sin(sigma) ** 2)
                * (-3 + 4 * math.cos(two_sigma_m) ** 2)
            )
        )
        sigma_prev = sigma
        sigma = distance_m / (_B * big_a) + delta_sigma
        if abs(sigma - sigma_prev) < 1e-12:
            break

    two_sigma_m = 2 * sigma1 + sigma
    tmp = sin_u1 * math.sin(sigma) - cos_u1 * math.cos(sigma) * cos_alpha1
    lat2 = math.atan2(
        sin_u1 * math.cos(sigma) + cos_u1 * math.sin(sigma) * cos_alpha1,
        (1 - _F) * math.sqrt(sin_alpha * sin_alpha + tmp * tmp),
    )
    lambda_ = math.atan2(
        math.sin(sigma) * sin_alpha1,
        cos_u1 * math.cos(sigma) - sin_u1 * math.sin(sigma) * cos_alpha1,
    )
    c = _F / 16 * cos_sq_alpha * (4 + _F * (4 - 3 * cos_sq_alpha))
    big_l = lambda_ - (1 - c) * _F * sin_alpha * (
        sigma + c * math.sin(sigma) * (
            math.cos(two_sigma_m) + c * math.cos(sigma) * (-1 + 2 * math.cos(two_sigma_m) ** 2)
        )
    )
    lon2 = lon1 + big_l

    return math.degrees(lat2), math.degrees(lon2)
