# -*- coding: utf-8 -*-
"""
輻射モデル（RadiationAnalysis）の面ごとに軌道熱入力を計算し、
CSV エクスポート・ノード HeatSource 書き戻しを行う。
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

import FreeCAD
import numpy as np

from orbitherm_studio.orbit_heat import orbit_attitude, orbit_core


_EARTH_RADIUS_KM = 6371.0


def _view_factor_earth(r_km: float) -> float:
    """衛星高度 r_km での地球ビューファクター簡易値。"""
    if r_km <= _EARTH_RADIUS_KM:
        return 0.5
    half_angle = math.asin(_EARTH_RADIUS_KM / r_km)
    return (1.0 - math.cos(half_angle)) * 0.5


def _vec_to_np(v) -> np.ndarray:
    if hasattr(v, "x"):
        return np.array([v.x, v.y, v.z], dtype=float)
    return np.asarray(v, dtype=float)


def _normalize(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    if n < 1e-30:
        return v
    return v / n


def compute_face_heat_inputs(
    surfaces: List[Dict],
    orbit_input: Any,
    times: np.ndarray,
    heat_array: np.ndarray,
    attitude_mode: orbit_attitude.AttitudeMode = "nadir",
) -> Tuple[List[Dict], np.ndarray]:
    """
    面リストと軌道・熱環境から、各面の時刻ごとの熱入力 [W] を計算する。

    戻り値: (results, times)
    results は [ {"node_id", "surface_id", "t_sec", "Q_solar", "Q_albedo", "Q_earth_ir", "Q_total"}, ... ]
    """
    times_arr = np.asarray(times, dtype=float)
    n_times = len(times_arr)
    if n_times == 0 or len(heat_array) != n_times:
        return [], times_arr
    positions_km = orbit_core.compute_positions_km(orbit_input, times_arr)
    if len(positions_km) != n_times:
        return [], times_arr
    results = []
    for surf in surfaces:
        node_id = surf["node_id"]
        surface_id = surf["surface_id"]
        normal_global = np.array(surf["normal_global"], dtype=float)
        area_m2 = float(surf["area_m2"])
        alpha = float(surf["solar_absorptivity"])
        epsilon = float(surf["ir_emissivity"])
        for i in range(n_times):
            t_sec = float(times_arr[i])
            q_solar = float(heat_array[i][0])
            q_albedo = float(heat_array[i][1])
            q_earth_ir = float(heat_array[i][2])
            pos_km = positions_km[i]
            r_km = np.linalg.norm(pos_km) + 1e-30
            sun_dir = orbit_core.sun_direction_from_earth(orbit_input, t_sec)
            sun_eci = _normalize(_vec_to_np(sun_dir))
            earth_eci = _normalize(-np.asarray(pos_km, dtype=float))
            rot = orbit_attitude.compute_attitude(
                pos_km, mode=attitude_mode, sun_dir_km=sun_dir
            )
            try:
                inv = rot.inverse()
            except AttributeError:
                inv = rot
            def _to_body(v):
                return _vec_to_np(inv.multVec(FreeCAD.Vector(float(v[0]), float(v[1]), float(v[2]))))
            normal_body = _normalize(_to_body(normal_global))
            sun_body = _normalize(_to_body(sun_eci))
            earth_body = _normalize(_to_body(earth_eci))
            cos_sun = max(0.0, np.dot(normal_body, sun_body))
            cos_earth = max(0.0, np.dot(normal_body, earth_body))
            vf = _view_factor_earth(r_km)
            Q_solar = q_solar * alpha * cos_sun * area_m2
            Q_albedo = alpha * q_albedo * vf * cos_earth * area_m2
            Q_earth_ir = epsilon * q_earth_ir * vf * cos_earth * area_m2
            Q_total = Q_solar + Q_albedo + Q_earth_ir
            results.append({
                "node_id": node_id,
                "surface_id": surface_id,
                "t_sec": t_sec,
                "Q_solar": Q_solar,
                "Q_albedo": Q_albedo,
                "Q_earth_ir": Q_earth_ir,
                "Q_total": Q_total,
            })
    return results, times_arr


def export_face_heat_csv(filepath: str, results: List[Dict]) -> None:
    """面ごと熱入力 results を CSV で出力する。"""
    header = "NodeId,SurfaceId,t_sec,Q_solar_W,Q_albedo_W,Q_earth_ir_W,Q_total_W"
    lines = [header]
    for r in results:
        lines.append(",".join([
            r["node_id"], r["surface_id"],
            "{:.6f}".format(r["t_sec"]),
            "{:.6f}".format(r["Q_solar"]), "{:.6f}".format(r["Q_albedo"]),
            "{:.6f}".format(r["Q_earth_ir"]), "{:.6f}".format(r["Q_total"]),
        ]))
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def apply_orbit_heat_to_radiation_model(
    doc: FreeCAD.Document,
    results: List[Dict],
    surfaces: List[Dict],
    mode: str = "mean",
) -> None:
    """
    面ごと熱入力 results の代表値（mode: "mean" なら時刻平均）を
    RadiationAnalysis のノードの HeatSource に書き込む。
    surfaces は get_surfaces_for_orbit_heat の戻り値（node_obj を含む）。
    """
    if not results or not surfaces:
        return
    by_node: Dict[str, List[float]] = {}
    for r in results:
        nid = r["node_id"]
        if nid not in by_node:
            by_node[nid] = []
        by_node[nid].append(r["Q_total"])
    node_obj_by_id = {s["node_id"]: s["node_obj"] for s in surfaces}
    for node_id, totals in by_node.items():
        if node_id not in node_obj_by_id:
            continue
        node_obj = node_obj_by_id[node_id]
        if mode == "mean":
            value = float(np.mean(totals))
        else:
            value = float(totals[0])
        if not hasattr(node_obj, "HeatSource"):
            node_obj.addProperty("App::PropertyFloat", "HeatSource", "Thermal", "発熱量 [W]")
        node_obj.HeatSource = value
    doc.recompute()
