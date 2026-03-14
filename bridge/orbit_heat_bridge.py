# -*- coding: utf-8 -*-
"""
OrbitHeat ワークベンチ用ブリッジ。
輻射モデルの面リスト（node_id, surface_id, 法線・面積・光学特性）を返す。
RadiationAnalysis は OrbitHeat に依存しない。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import FreeCAD

from orbitherm_studio.modeling import freecad_utils
from orbitherm_studio.modeling.core import (
    _iter_face_groups_front_and_node,
    _local_normal_to_global,
    _mesh_outward_normal,
)


def get_surfaces_for_orbit_heat(
    doc: FreeCAD.Document, parent_group: Optional[Any] = None
) -> List[Dict]:
    """
    軌道熱入力計算用の面リストを返す。

    各要素: node_id, surface_id, normal_global (tuple), area_m2,
            solar_absorptivity, ir_emissivity, node_obj, front_mesh_obj
    """
    face_groups = freecad_utils.get_face_groups(doc)
    if parent_group is not None and hasattr(parent_group, "Group"):
        # 指定グループ内の FaceGroup に限定
        allowed = set(parent_group.Group)
        face_groups = [g for g in face_groups if g in allowed]
    result = []
    for group in face_groups:
        model_name = str(getattr(group, "ModelName", "Model"))
        for front_mesh_obj, node_obj in _iter_face_groups_front_and_node([group]):
            if not getattr(front_mesh_obj, "Mesh", None):
                continue
            mesh = front_mesh_obj.Mesh
            area_mm2 = getattr(mesh, "Area", 0.0) or 0.0
            area_m2 = area_mm2 / 1e6
            solar_absorptivity = float(
                getattr(front_mesh_obj, "SolarAbsorptivity", 0.3)
            )
            ir_emissivity = float(
                getattr(front_mesh_obj, "InfraredEmissivity", 0.85)
            )
            node_number = int(getattr(node_obj, "NodeNumber", 0))
            surface_number = int(
                getattr(front_mesh_obj, "SurfaceNumber", getattr(group, "SurfaceNumber", 0))
            )
            node_id = "{}.{}".format(model_name, node_number)
            surface_id = "{}.{}".format(model_name, surface_number)
            normal_local = _mesh_outward_normal(mesh)
            normal_global = _local_normal_to_global(front_mesh_obj, normal_local)
            normal_tuple = (
                float(normal_global[0]),
                float(normal_global[1]),
                float(normal_global[2]),
            )
            result.append({
                "node_id": node_id,
                "surface_id": surface_id,
                "normal_global": normal_tuple,
                "area_m2": area_m2,
                "solar_absorptivity": solar_absorptivity,
                "ir_emissivity": ir_emissivity,
                "node_obj": node_obj,
                "front_mesh_obj": front_mesh_obj,
            })
    return result
