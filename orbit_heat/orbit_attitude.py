from __future__ import annotations

from typing import Literal

import FreeCAD


AttitudeMode = Literal["nadir", "sun"]


def _to_vector_km(pos_km) -> FreeCAD.Vector:
    """(x, y, z) in km -> FreeCAD.Vector (km)."""
    return FreeCAD.Vector(float(pos_km[0]), float(pos_km[1]), float(pos_km[2]))


def rotation_nadir(position_km) -> FreeCAD.Rotation:
    """
    Nadir 指向姿勢の回転を返す。

    ワールド +Z 軸が地球中心方向（すなわち -r ベクトル）を向くように回転を与える。
    軌道接線方向までは拘束せず、Z 軸合わせのみ行う簡易モデル。
    """
    r = _to_vector_km(position_km)
    if r.Length == 0:
        return FreeCAD.Rotation()
    nadir_dir = -r
    return FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), nadir_dir)


def rotation_sun_pointing(position_km, sun_dir_km) -> FreeCAD.Rotation:
    """
    太陽指向姿勢の回転を返す。

    ワールド +Z 軸が太陽方向ベクトルを向くように回転を与える。
    position_km は現状未使用だが将来の拡張のために受け取る。
    """
    s = _to_vector_km(sun_dir_km)
    if s.Length == 0:
        return FreeCAD.Rotation()
    return FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), s)


def compute_attitude(
    position_km,
    mode: AttitudeMode = "nadir",
    sun_dir_km=None,
) -> FreeCAD.Rotation:
    """
    姿勢モードに応じて Rotation を返す。

    - "nadir": 地球中心方向を向く姿勢
    - "sun": 太陽方向を向く姿勢（sun_dir_km が必須）
    """
    if mode == "sun":
        if sun_dir_km is None:
            raise ValueError("sun モードには sun_dir_km が必要です。")
        return rotation_sun_pointing(position_km, sun_dir_km)
    return rotation_nadir(position_km)

