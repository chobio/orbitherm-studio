# core.py (バージョン 5.2)
"""
COMPATIBILITY INTEGRATION MODULE — DO NOT ADD NEW LOGIC HERE
=============================================================
This file is a temporary integration layer that exists during
an ongoing wrapper-first refactoring of the ThermalAnalysis
workbench.  It currently hosts code that belongs in separate
modules but has not yet been physically moved.

Planned final destinations
--------------------------
- modeling/core.py       → keep only MODEL BUILDING and
                           CONDUCTANCE / RADIATION CALCULATION
- post/                  → all DISPLAY / VISUALIZATION logic
                           (see section marker below)
- bridge/exporter.py     → SOLVER FILE EXPORT helpers

Rules for contributors
----------------------
- Do NOT add new display/visualization logic here; add it
  directly to post/ instead.
- Do NOT add new solver-export logic here; add it to
  bridge/exporter.py instead.
- New model-building or calculation helpers may still go here
  temporarily, but should include a TODO comment pointing to
  their intended final location.

See also: docs/module_structure.md
"""

import FreeCAD
import FreeCADGui
import Mesh
import MeshPart
import Part
import itertools
import json
import math
import os
import random
from collections import defaultdict

import numpy as np

from ThermalAnalysis.modeling import calculation, freecad_utils


# =========================================================
# PRIVATE UTILITIES — LOGGING, NAMING, SELECTION HELPERS
#
# Small internal functions shared across the whole module:
# debug logging, FreeCAD object naming conventions, and
# selection/index parsing utilities.
# =========================================================

# #region agent log
def _dbg_log(location, message, data=None, hypothesisId=None):
    try:
        log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "debug-1b991f.log")
        payload = {"sessionId": "1b991f", "location": location, "message": message, "timestamp": __import__("time").time() * 1000}
        if data is not None:
            payload["data"] = data
        if hypothesisId is not None:
            payload["hypothesisId"] = hypothesisId
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass

# #endregion

# 輻射ビューファクター用: モンテカルロのレイ数（1パッチあたり）
_RAYS_PER_PATCH_DEFAULT = 2000
# 空間ノードID（輻射先の宇宙）
_SPACE_NODE_ID = "SPACE.9999"

# 面プロパティ未設定時に計算で使うデフォルト値（単位: m, kg/m³, J/kgK, W/mK）
_DEFAULT_THICKNESS = 0.001
_DEFAULT_DENSITY = 2000.0
_DEFAULT_SPECIFIC_HEAT = 1000.0
_DEFAULT_THERMAL_CONDUCTIVITY = 1.0


def _get_face_thermal_values(face_obj):
    """
    面オブジェクトから厚み・密度・比熱・熱伝導率を取得する。
    プロパティが無い場合はデフォルト値を返す（熱容量・コンダクタンス計算をスキップしないため）。
    戻り値: (thickness_m, density, specific_heat, thermal_conductivity)
    """
    def _float_attr(name, default):
        v = getattr(face_obj, name, None)
        if v is not None and isinstance(v, (int, float)):
            return float(v)
        return default
    return (
        _float_attr("Thickness", _DEFAULT_THICKNESS),
        _float_attr("Density", _DEFAULT_DENSITY),
        _float_attr("SpecificHeat", _DEFAULT_SPECIFIC_HEAT),
        _float_attr("ThermalConductivity", _DEFAULT_THERMAL_CONDUCTIVITY),
    )

def _sanitize_model_name(label):
    """FreeCAD の Label をサブモデル名として使える文字列に変換する。"""
    if not label:
        return "Model"
    s = str(label).strip()
    for c in " \\/:*?\"<>|":
        s = s.replace(c, "_")
    return s[:64] if s else "Model"


def _name_sanitize(s):
    """FreeCAD の Name 用。ドット等をアンダースコアに。"""
    if not s:
        return "Model"
    return str(s).replace(".", "_").strip()[:64] or "Model"


def _face_group_name(model_name, i):
    return f"FaceGroup_{_name_sanitize(model_name)}_{i}"


def _face_mesh_name(model_name, i, suffix):
    return f"Face_{_name_sanitize(model_name)}_{i}_{suffix}"


def _node_name_for_face(model_name, i):
    return f"Node_{_name_sanitize(model_name)}_{i}"


def _face_sub_mesh_name(model_name, i, k, suffix):
    return f"Face_{_name_sanitize(model_name)}_{i}_sub_{k}_{suffix}"


def _node_sub_name(model_name, i, k):
    return f"Node_{_name_sanitize(model_name)}_{i}_sub_{k}"


def _get_face_group_by_shape_index(doc, face_groups, base_obj, face_index):
    for g in (face_groups or []):
        if getattr(g, "BaseObject", None) != base_obj:
            continue
        if getattr(g, "SurfaceNumber", -1) == face_index:
            return g
    return None


def _get_selection_ex():
    """getSelectionEx の結果を返す。先頭要素の Object と SubElementNames を利用する。"""
    try:
        sel_ex = FreeCADGui.Selection.getSelectionEx()
    except Exception:
        return None
    return sel_ex


_STEFAN_BOLTZMANN_CONST = 5.670374419e-8  # W/(m^2*K^4) の基準値。HEADER CONTROL DATA の STEFAN_BOLTZMANN で上書き可能。


def _parse_face_indices_from_sub_names(sub_element_names):
    """
    SubElementNames から Face インデックス（0-based）のリストを重複除去・ソートして返す。
    例: ["Face3", "Face1"] -> [0, 2]
    """
    if not sub_element_names:
        return []
    indices = []
    for name in sub_element_names:
        if not name or not isinstance(name, str):
            continue
        if name.startswith("Face"):
            try:
                idx = int(name.replace("Face", "").strip()) - 1
                if idx >= 0 and idx not in indices:
                    indices.append(idx)
            except ValueError:
                continue
    return sorted(indices)


# =========================================================
# MODEL BUILDING  (geometry extraction, node generation)
#
# Converts FreeCAD Part shapes into the radiation/thermal
# mesh representation used by this workbench:
#   - tessellates solid faces into Mesh::Feature objects
#   - creates FaceGroup / Node objects in the document
#   - supports surface subdivision (UV grid split)
# =========================================================

def run_prepare_model(linear_deflection=0.1, angular_deflection=28.5, one_node_per_solid=False):
    """
    linear_deflection: メッシュ細分化の許容偏差 [mm]。小さいほど細かくなる。
    angular_deflection: メッシュ細分化の角度許容 [度]。未使用時は MeshPart の既定を使用。
    オブジェクトのみ選択時は全 Face を変換。オブジェクト＋面のサブ選択時は選択した面のみ変換。
    サーフェースのみのオブジェクト（Shell、Compound 等）も選択可能。
    """
    sel_ex = _get_selection_ex()
    if not sel_ex:
        FreeCAD.Console.PrintError("オブジェクトが選択されていません。\n")
        return
    obj = sel_ex[0].Object
    try:
        doc = FreeCAD.ActiveDocument
        shape = obj.Shape
        if not shape or not getattr(shape, "Faces", None) or len(shape.Faces) == 0:
            FreeCAD.Console.PrintError("選択オブジェクトに面がありません。サーフェースまたはソリッドを選択してください。\n")
            return
        model_name = _sanitize_model_name(getattr(obj, "Label", "Model"))
        # 既存の FaceGroup から現在の最大サーフェース番号を取得（部分変換時の連番用）
        existing_groups_all = [
            o for o in doc.Objects
            if hasattr(o, "BaseObject") and o.BaseObject == obj
        ]
        max_surface_index = -1
        for g in existing_groups_all:
            idx = getattr(g, "SurfaceNumber", None)
            if isinstance(idx, int):
                if idx > max_surface_index:
                    max_surface_index = idx

        # 対象面リスト: (thermal_index, source_face_index, Part.Face)
        sub_names = getattr(sel_ex[0], "SubElementNames", []) or []
        selected_face_indices = _parse_face_indices_from_sub_names(sub_names)
        if selected_face_indices:
            # 選択面のみ変換（部分変換）
            base_index = max_surface_index + 1
            target_faces = []
            for i, src_idx in enumerate(selected_face_indices):
                if src_idx < len(shape.Faces):
                    thermal_index = base_index + i
                    target_faces.append((thermal_index, src_idx, shape.Faces[src_idx]))
            if not target_faces:
                FreeCAD.Console.PrintError("選択された面が無効です。\n")
                return
        else:
            # 全面変換（従来どおり）: 0 からの連番で全面を変換
            target_faces = [(i, i, f) for i, f in enumerate(shape.Faces)]

        # 部分変換か全面変換かを判定
        is_partial = len(target_faces) < len(shape.Faces)

        # 全面変換のときだけ既存のグループやリンクを削除して、モデルを作り直す。
        # 部分変換では既存の FaceGroup / ノード / リンクを温存し、新しい面だけを追加・更新する。
        if not is_partial:
            existing_groups = existing_groups_all
            for group in existing_groups:
                doc.removeObject(group.Name)
            old_links = doc.getObject(f"{obj.Label}_ConductanceLinks")
            if not old_links:
                old_links = doc.getObject(f"{model_name}_ConductanceLinks")
            if old_links:
                doc.removeObject(old_links.Name)
            old_rad = doc.getObject(f"{obj.Label}_RadiationLinks")
            if not old_rad:
                old_rad = doc.getObject(f"{model_name}_RadiationLinks")
            if old_rad:
                doc.removeObject(old_rad.Name)
            doc.recompute()

        parent_name = "RadiationModel_" + obj.Name
        if not is_partial:
            # 全面変換の場合は既存の親グループを削除して作り直す
            existing_parent = doc.getObject(parent_name)
            if existing_parent:
                doc.removeObject(existing_parent.Name)
                doc.recompute()
            parent_group = doc.addObject("App::DocumentObjectGroup", parent_name)
        else:
            # 部分変換の場合は既存の親グループを再利用し、無いときだけ新規作成する
            parent_group = doc.getObject(parent_name)
            if parent_group is None:
                parent_group = doc.addObject("App::DocumentObjectGroup", parent_name)

        parent_group.Label = model_name + " 輻射モデル"
        if not hasattr(parent_group, "ModelName"):
            parent_group.addProperty("App::PropertyString", "ModelName", "Internal")
        parent_group.ModelName = model_name
        FreeCAD.Console.PrintMessage(f"'{obj.Label}'の階層モデルの作成を開始します...\n")
        # one_node_per_solid=True のときは、全FaceGroupで共有するノードを1つだけ持つ
        shared_node = None
        if one_node_per_solid:
            center_point = shape.CenterOfMass
            vertex_shape = Part.Vertex(center_point)
            shared_node = doc.addObject("Part::Feature", "Node_Solid_0")
            shared_node.Shape = vertex_shape
            if not hasattr(shared_node, "NodeNumber"):
                shared_node.addProperty("App::PropertyInteger", "NodeNumber", "Thermal", "ノード番号")
            shared_node.NodeNumber = 0
            if not hasattr(shared_node, "HeatSource"):
                shared_node.addProperty("App::PropertyFloat", "HeatSource", "Thermal", "発熱量 [W]")
            shared_node.HeatSource = getattr(shared_node, "HeatSource", 0.0)
            if not hasattr(shared_node, "ModelName"):
                shared_node.addProperty("App::PropertyString", "ModelName", "Internal")
            shared_node.ModelName = model_name
            shared_node.Label = f"ノード {model_name}.0"
            if FreeCAD.GuiUp:
                vp_node = shared_node.ViewObject
                vp_node.PointSize = get_pref_node_point_size_default()
                vp_node.PointColor = (1.0, 1.0, 0.0)
        is_partial = len(target_faces) < len(shape.Faces)
        for thermal_i, source_i, face in target_faces:
            try:
                fg_name = _face_group_name(model_name, thermal_i)
                face_group = doc.getObject(fg_name) or doc.addObject("App::DocumentObjectGroup", fg_name)
                if not hasattr(face_group, "BaseObject"):
                    face_group.addProperty("App::PropertyLink", "BaseObject", "Internal")
                face_group.BaseObject = obj
                if not hasattr(face_group, "ModelName"):
                    face_group.addProperty("App::PropertyString", "ModelName", "Internal")
                face_group.ModelName = model_name
                if not hasattr(face_group, "SurfaceNumber"):
                    face_group.addProperty("App::PropertyInteger", "SurfaceNumber", "Thermal", "サーフェース番号")
                face_group.SurfaceNumber = thermal_i
                if is_partial and not hasattr(face_group, "SourceFaceIndex"):
                    face_group.addProperty("App::PropertyInteger", "SourceFaceIndex", "Internal", "元Shapeの面インデックス")
                if is_partial:
                    face_group.SourceFaceIndex = source_i
                face_group.Label = f"{model_name}.{thermal_i}"
                front_mesh_data = MeshPart.meshFromShape(
                    Shape=face,
                    LinearDeflection=float(linear_deflection),
                    AngularDeflection=float(angular_deflection),
                )
                front_name = _face_mesh_name(model_name, thermal_i, "front")
                back_name = _face_mesh_name(model_name, thermal_i, "back")
                front_mesh_obj = doc.addObject("Mesh::Feature", front_name)
                front_mesh_obj.Mesh = front_mesh_data
                front_mesh_obj.Label = f"{model_name}.{thermal_i} 表面"
                back_mesh_data = front_mesh_data.copy()
                back_mesh_data.flipNormals()
                back_mesh_obj = doc.addObject("Mesh::Feature", back_name)
                back_mesh_obj.Mesh = back_mesh_data
                back_mesh_obj.Label = f"{model_name}.{thermal_i} 裏面"
                for mesh_obj in (front_mesh_obj, back_mesh_obj):
                    if not hasattr(mesh_obj, "SolarAbsorptivity"):
                        mesh_obj.addProperty("App::PropertyFloat", "SolarAbsorptivity", "Thermal", "太陽光吸収率")
                        mesh_obj.SolarAbsorptivity = 0.5
                    if not hasattr(mesh_obj, "InfraredEmissivity"):
                        mesh_obj.addProperty("App::PropertyFloat", "InfraredEmissivity", "Thermal", "赤外放射率")
                        mesh_obj.InfraredEmissivity = 0.85
                    if not hasattr(mesh_obj, "Transmittance"):
                        mesh_obj.addProperty("App::PropertyFloat", "Transmittance", "Thermal", "透過率")
                        mesh_obj.Transmittance = 0.0
                    if not hasattr(mesh_obj, "ActiveSide"):
                        mesh_obj.addProperty("App::PropertyEnumeration", "ActiveSide", "Thermal", "輻射計算の対象面")
                        mesh_obj.ActiveSide = ["両面", "表面", "裏面"]
                        mesh_obj.ActiveSide = "両面"
                face_group.addObject(front_mesh_obj)
                face_group.addObject(back_mesh_obj)
                if one_node_per_solid and shared_node is not None:
                    # 全ての FaceGroup に共有ノードをぶら下げる
                    face_group.addObject(shared_node)
                else:
                    center_point = face.CenterOfMass
                    vertex_shape = Part.Vertex(center_point)
                    node_name = _node_name_for_face(model_name, thermal_i)
                    node_obj = doc.addObject("Part::Feature", node_name)
                    node_obj.Shape = vertex_shape
                    if not hasattr(node_obj, "NodeNumber"):
                        node_obj.addProperty("App::PropertyInteger", "NodeNumber", "Thermal", "ノード番号")
                    node_obj.NodeNumber = thermal_i
                    if not hasattr(node_obj, "HeatSource"):
                        node_obj.addProperty("App::PropertyFloat", "HeatSource", "Thermal", "発熱量 [W]")
                    node_obj.HeatSource = 0.0
                    if not hasattr(node_obj, "ModelName"):
                        node_obj.addProperty("App::PropertyString", "ModelName", "Internal")
                    node_obj.ModelName = model_name
                    node_obj.Label = f"ノード {model_name}.{thermal_i}"
                    face_group.addObject(node_obj)
                    if FreeCAD.GuiUp:
                        vp_node = node_obj.ViewObject
                        vp_node.PointSize = get_pref_node_point_size_default()
                        vp_node.PointColor = (1.0, 1.0, 0.0)  # 黄色
                parent_group.addObject(face_group)
            except Exception as e:
                FreeCAD.Console.PrintError(f"Face_{thermal_i} の処理中にエラーが発生しました: {e}\n")
                continue
        # obj は各 FaceGroup の BaseObject として参照されているため、parent_group に追加すると
        # "Object can only be in a single Group" が発生する。元形状はドキュメントルートに残し 3D のみ非表示にする。
        if FreeCAD.GuiUp and hasattr(obj, "ViewObject"):
            obj.ViewObject.Visibility = False
        doc.recompute()
        FreeCAD.Console.PrintMessage("処理が完了しました。\n")
    except Exception as e:
        FreeCAD.Console.PrintError(f"処理中に予期せぬエラーが発生しました: {e}\n")


def _mesh_point_to_xyz(p):
    """MeshPoint や Vector を (x,y,z) の float タプルに変換する。PyCXX が MeshPoint を扱えないため。"""
    if hasattr(p, "x") and hasattr(p, "y") and hasattr(p, "z"):
        return (float(p.x), float(p.y), float(p.z))
    return (float(p[0]), float(p[1]), float(p[2]))


def _refine_mesh_by_subdividing_facets(points, facets_tuples):
    """
    各三角形を重心と3辺中点で6三角形に分割してメッシュを細かくする。
    ファセット数が少ないとグリッド分割で空セルが出るため、事前に細分化する。
    facets_tuples: list of (i, j, k) の点インデックス。
    """
    new_points = list(points)
    new_facets = []
    point_index = len(points)

    def add_point(px, py, pz):
        nonlocal point_index
        new_points.append((float(px), float(py), float(pz)))
        idx = point_index
        point_index += 1
        return idx

    for (i, j, k) in facets_tuples:
        a, b, c = points[i], points[j], points[k]
        m_ab = (0.5 * (a[0] + b[0]), 0.5 * (a[1] + b[1]), 0.5 * (a[2] + b[2]))
        m_bc = (0.5 * (b[0] + c[0]), 0.5 * (b[1] + c[1]), 0.5 * (b[2] + c[2]))
        m_ca = (0.5 * (c[0] + a[0]), 0.5 * (c[1] + a[1]), 0.5 * (c[2] + a[2]))
        ctr = ((a[0] + b[0] + c[0]) / 3.0, (a[1] + b[1] + c[1]) / 3.0, (a[2] + b[2] + c[2]) / 3.0)
        i_ab = add_point(*m_ab)
        i_bc = add_point(*m_bc)
        i_ca = add_point(*m_ca)
        i_ctr = add_point(*ctr)
        new_facets.append((i, i_ab, i_ctr))
        new_facets.append((i_ab, j, i_ctr))
        new_facets.append((j, i_bc, i_ctr))
        new_facets.append((i_bc, k, i_ctr))
        new_facets.append((k, i_ca, i_ctr))
        new_facets.append((i_ca, i, i_ctr))
    return new_points, new_facets


def _mesh_grid_subdivide(mesh, nu, nv):
    """
    メッシュをバウンディングボックスのグリッドで nu x nv に分割する。
    ファセット数が少ない場合は先に1回細分化してから分割し、全セルにメッシュが入るようにする。
    戻り値: list of Mesh.Mesh, 各要素はセル k に対応する部分メッシュ。
    """
    # MeshPoint のまま渡すと PyCXX で SeqBase 変換エラーになるため、先に (x,y,z) に変換する
    points = [_mesh_point_to_xyz(p) for p in mesh.Points]
    facets = list(mesh.Facets)
    if not points or not facets:
        return []

    def facet_triple(fa):
        if hasattr(fa, "PointIndices"):
            return tuple(fa.PointIndices)
        return (fa[0], fa[1], fa[2])

    # 元の facets は (i,j,k) のリスト。points は (x,y,z) タプルのリスト。
    facets_tuples = [facet_triple(fa) for fa in facets]
    # ファセット数が nu*nv より少ない場合は1回細分化してから分割する（空セルを防ぐ）
    if len(facets_tuples) < nu * nv:
        points, facets_tuples = _refine_mesh_by_subdividing_facets(points, facets_tuples)
    # 各ファセットの重心を計算（以降は points と facets_tuples のみ使用）
    centroids = []
    for (i, j, k) in facets_tuples:
        a, b, c_pt = points[i], points[j], points[k]
        c = FreeCAD.Vector(
            (a[0] + b[0] + c_pt[0]) / 3.0,
            (a[1] + b[1] + c_pt[1]) / 3.0,
            (a[2] + b[2] + c_pt[2]) / 3.0,
        )
        centroids.append(c)
    # バウンディングボックス（2軸で分割するため、範囲の大きい2方向を使う）
    xs = [c.x for c in centroids]
    ys = [c.y for c in centroids]
    zs = [c.z for c in centroids]
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    zmin, zmax = min(zs), max(zs)
    dx = xmax - xmin or 1e-9
    dy = ymax - ymin or 1e-9
    dz = zmax - zmin or 1e-9
    # 最も範囲が小さい軸を「法線方向」として除外し、2軸でグリッド分割
    if dx <= dy and dx <= dz:
        ax1, ax2 = (1, 2)  # y, z
        a1min, a1max, a2min, a2max = ymin, ymax, zmin, zmax
        d1, d2 = dy, dz
    elif dy <= dx and dy <= dz:
        ax1, ax2 = (0, 2)  # x, z
        a1min, a1max, a2min, a2max = xmin, xmax, zmin, zmax
        d1, d2 = dx, dz
    else:
        ax1, ax2 = (0, 1)  # x, y
        a1min, a1max, a2min, a2max = xmin, xmax, ymin, ymax
        d1, d2 = dx, dy
    d1 = d1 or 1e-9
    d2 = d2 or 1e-9
    def get_cell(v):
        a1 = v.x if ax1 == 0 else (v.y if ax1 == 1 else v.z)
        a2 = v.x if ax2 == 0 else (v.y if ax2 == 1 else v.z)
        u = (a1 - a1min) / d1
        vv = (a2 - a2min) / d2
        ci = min(int(u * nu), nu - 1) if nu else 0
        cj = min(int(vv * nv), nv - 1) if nv else 0
        return ci * nv + cj
    # セルごとにファセットインデックスを集める
    cells = [[] for _ in range(nu * nv)]
    for fi, c in enumerate(centroids):
        k = get_cell(c)
        cells[k].append(fi)
    # 各セルで部分メッシュを構築（使う点だけ取り出し、ファセットを付け替え）
    result = []
    for cell_facets in cells:
        if not cell_facets:
            result.append(Mesh.Mesh())
            continue
        used_points = set()
        for fi in cell_facets:
            for idx in facets_tuples[fi]:
                used_points.add(idx)
        old_to_new = {idx: i for i, idx in enumerate(sorted(used_points))}
        new_points = [FreeCAD.Vector(*points[idx]) for idx in sorted(used_points)]
        part = Mesh.Mesh()
        for fi in cell_facets:
            i, j, k = facets_tuples[fi]
            ni, nj, nk = old_to_new[i], old_to_new[j], old_to_new[k]
            part.addFacet(new_points[ni], new_points[nj], new_points[nk])
        result.append(part)
    return result


def run_subdivide_surface(nu, nv, merge_subs_into_one_node=False, surface_number_start=None):
    """
    選択された FaceGroup のメッシュを U方向 nu x V方向 nv のグリッドで分割し、
    Face_i_sub_k_front/back と Node_i_sub_k（または1ノード）を作成する。
    merge_subs_into_one_node: True のときサブを1ノードにまとめる（Node_i のみ使用）。
    surface_number_start: 各サブの SurfaceNumber の開始番号。None のとき FaceGroup.SurfaceNumber * 1000 + k を使う。
    """
    doc = FreeCAD.ActiveDocument
    if not doc:
        FreeCAD.Console.PrintError("アクティブなドキュメントがありません。\n")
        return
    selection = FreeCADGui.Selection.getSelection()
    if not selection:
        FreeCAD.Console.PrintError("FaceGroup またはそのメッシュを選択してください。\n")
        return
    face_groups_to_process = []
    for sel in selection:
        if sel.isDerivedFrom("App::DocumentObjectGroup") and sel.Name.startswith("FaceGroup_"):
            face_groups_to_process.append(sel)
        elif sel.isDerivedFrom("Mesh::Feature") and "Face_" in sel.Name:
            for o in doc.Objects:
                if not hasattr(o, "Group") or sel not in o.Group:
                    continue
                if o.Name.startswith("FaceGroup_"):
                    if o not in face_groups_to_process:
                        face_groups_to_process.append(o)
                    break
                for o2 in doc.Objects:
                    if hasattr(o2, "Group") and o in o2.Group and o2.Name.startswith("FaceGroup_"):
                        if o2 not in face_groups_to_process:
                            face_groups_to_process.append(o2)
                        break
                else:
                    continue
                break  # FaceGroup を見つけたので外側ループを抜ける
    if not face_groups_to_process:
        FreeCAD.Console.PrintError("FaceGroup が見つかりません。\n")
        return
    nu = max(1, int(nu))
    nv = max(1, int(nv))
    for face_group in face_groups_to_process:
        try:
            _subdivide_one_face_group(
                doc, face_group, nu, nv, merge_subs_into_one_node, surface_number_start
            )
        except Exception as e:
            FreeCAD.Console.PrintError(f"{face_group.Name} の分割中にエラー: {e}\n")
    doc.recompute()
    FreeCAD.Console.PrintMessage("サーフェース分割が完了しました。\n")


def _subdivide_face_by_uv(part_face, nu, nv, linear_deflection=0.1, angular_deflection=28.5):
    """
    Part の面を UV パラメータで nu x nv に均等分割し、各サブ面をメッシュ化して返す。
    四角面が均等な四角のサブに分割される。
    戻り値: list of Mesh.Mesh（長さ nu*nv）、失敗時は None。
    """
    try:
        (u_min, u_max, v_min, v_max) = (None, None, None, None)
        if hasattr(part_face, "ParameterRange"):
            try:
                (u_min, u_max, v_min, v_max) = part_face.ParameterRange
            except Exception:
                pass
        if u_min is None and hasattr(part_face, "Surface"):
            try:
                s = part_face.Surface
                if s is not None:
                    u_min, u_max = s.uBounds()
                    v_min, v_max = s.vBounds()
            except Exception:
                pass
        if u_min is None:
            try:
                fg = getattr(part_face, "Face", None)
                if fg is not None and hasattr(fg, "Surface"):
                    s = fg.Surface
                    u_min, u_max = s.uBounds()
                    v_min, v_max = s.vBounds()
            except Exception:
                return None
        if u_min is None:
            return None
        u_del = (u_max - u_min) / nu
        v_del = (v_max - v_min) / nv
        result = []
        for ci in range(nu):
            for cj in range(nv):
                u0 = u_min + ci * u_del
                u1 = u_min + (ci + 1) * u_del
                v0 = v_min + cj * v_del
                v1 = v_min + (cj + 1) * v_del
                try:
                    p00 = part_face.valueAt(u0, v0)
                    p10 = part_face.valueAt(u1, v0)
                    p11 = part_face.valueAt(u1, v1)
                    p01 = part_face.valueAt(u0, v1)
                except Exception:
                    return None
                e1 = Part.LineSegment(p00, p10).toShape()
                e2 = Part.LineSegment(p10, p11).toShape()
                e3 = Part.LineSegment(p11, p01).toShape()
                e4 = Part.LineSegment(p01, p00).toShape()
                wire = Part.Wire([e1, e2, e3, e4])
                try:
                    sub_face = Part.Face(wire)
                except Exception:
                    return None
                sub_mesh = MeshPart.meshFromShape(
                    Shape=sub_face,
                    LinearDeflection=float(linear_deflection),
                    AngularDeflection=float(angular_deflection),
                )
                result.append(sub_mesh)
        return result
    except Exception:
        return None


def _subdivide_one_face_group(doc, face_group, nu, nv, merge_subs_into_one_node, surface_number_start):
    """1つの FaceGroup をサブ分割する。Part 面の UV 分割を優先し、失敗時は既存メッシュのグリッド分割にフォールバック。"""
    group_name = face_group.Name
    if not group_name.startswith("FaceGroup_"):
        return
    face_index = getattr(face_group, "SurfaceNumber", None)
    if face_index is None:
        try:
            i_str = group_name.replace("FaceGroup_", "").strip()
            face_index = int(i_str.split("_")[-1]) if "_" in i_str else int(i_str)
        except ValueError:
            return
    base_obj = getattr(face_group, "BaseObject", None)
    model_name = getattr(face_group, "ModelName", None) or _sanitize_model_name(getattr(base_obj, "Label", "Model"))
    front_name_new = _face_mesh_name(model_name, face_index, "front")
    front_name_old = f"Face_{face_index}_front"
    source_face_index = getattr(face_group, "SourceFaceIndex", face_index)
    part_face = None
    if base_obj and hasattr(base_obj, "Shape"):
        try:
            part_face = base_obj.Shape.Faces[source_face_index]
        except (IndexError, AttributeError):
            pass
    linear_deflection = 0.1
    angular_deflection = 28.5
    if part_face is not None:
        sub_meshes = _subdivide_face_by_uv(part_face, nu, nv, linear_deflection, angular_deflection)
    else:
        sub_meshes = None
    front_obj = doc.getObject(front_name_new) or doc.getObject(front_name_old)
    if sub_meshes is None or len(sub_meshes) != nu * nv:
        FreeCAD.Console.PrintMessage(
            f"Face {model_name}.{face_index}: UV均等分割をスキップし、メッシュのグリッド分割を使用します。\n"
        )
        if not front_obj or not hasattr(front_obj, "Mesh") or front_obj not in _face_group_members(face_group):
            FreeCAD.Console.PrintError(f"Face {front_name_new} / {front_name_old} が見つかりません。\n")
            return
        sub_meshes = _mesh_grid_subdivide(front_obj.Mesh, nu, nv)
        front_obj = doc.getObject(front_name_new) or doc.getObject(front_name_old)
    else:
        if not front_obj or front_obj not in _face_group_members(face_group):
            FreeCAD.Console.PrintError(f"Face {front_name_new} / {front_name_old} が見つかりません。\n")
            return
    base_surf = getattr(face_group, "SurfaceNumber", face_index)
    start_surf = surface_number_start if surface_number_start is not None else base_surf * 1000
    # 既存のサブがあれば削除（再分割時）
    to_remove = []
    for o in face_group.Group:
        if "_sub_" in o.Name:
            to_remove.append(o)
    for o in to_remove:
        face_group.removeObject(o)
        doc.removeObject(o.Name)
    # プロパティコピー用
    def copy_face_props(src, dst):
        for prop in ("SolarAbsorptivity", "InfraredEmissivity", "Transmittance", "ActiveSide", "Thickness", "Density", "SpecificHeat", "ThermalConductivity"):
            if hasattr(src, prop):
                if not hasattr(dst, prop):
                    if prop == "ActiveSide":
                        dst.addProperty("App::PropertyEnumeration", prop, "Thermal", "輻射計算の対象面")
                        dst.ActiveSide = ["両面", "表面", "裏面"]
                    elif prop in ("SolarAbsorptivity", "InfraredEmissivity", "Transmittance", "Thickness", "Density", "SpecificHeat", "ThermalConductivity"):
                        dst.addProperty("App::PropertyFloat", prop, "Thermal", prop)
                    else:
                        continue
                setattr(dst, prop, getattr(src, prop))
    node_list = []
    for k, sub_mesh in enumerate(sub_meshes):
        num_facets = len(sub_mesh.Facets) if hasattr(sub_mesh.Facets, "__len__") else getattr(sub_mesh, "FacetCount", 0)
        if num_facets == 0:
            continue
        name_front = _face_sub_mesh_name(model_name, face_index, k, "front")
        name_back = _face_sub_mesh_name(model_name, face_index, k, "back")
        front_sub = doc.addObject("Mesh::Feature", name_front)
        front_sub.Mesh = sub_mesh
        front_sub.Label = f"{model_name}.{start_surf + k} 表面"
        copy_face_props(front_obj, front_sub)
        back_mesh = sub_mesh.copy()
        back_mesh.flipNormals()
        back_sub = doc.addObject("Mesh::Feature", name_back)
        back_sub.Mesh = back_mesh
        back_sub.Label = f"{model_name}.{start_surf + k} 裏面"
        copy_face_props(front_obj, back_sub)
        face_group.addObject(front_sub)
        face_group.addObject(back_sub)
        if not hasattr(front_sub, "SurfaceNumber"):
            front_sub.addProperty("App::PropertyInteger", "SurfaceNumber", "Thermal", "サーフェース番号")
        front_sub.SurfaceNumber = start_surf + k
        if not hasattr(back_sub, "SurfaceNumber"):
            back_sub.addProperty("App::PropertyInteger", "SurfaceNumber", "Thermal", "サーフェース番号")
        back_sub.SurfaceNumber = start_surf + k
        if merge_subs_into_one_node:
            continue
        center = sub_mesh.BoundBox.Center
        vertex_shape = Part.Vertex(center)
        node_name = _node_sub_name(model_name, face_index, k)
        node_obj = doc.addObject("Part::Feature", node_name)
        node_obj.Shape = vertex_shape
        if not hasattr(node_obj, "NodeNumber"):
            node_obj.addProperty("App::PropertyInteger", "NodeNumber", "Thermal", "ノード番号")
        node_obj.NodeNumber = start_surf + k
        if not hasattr(node_obj, "HeatSource"):
            node_obj.addProperty("App::PropertyFloat", "HeatSource", "Thermal", "発熱量 [W]")
            node_obj.HeatSource = 0.0
        if not hasattr(node_obj, "ModelName"):
            node_obj.addProperty("App::PropertyString", "ModelName", "Internal")
        node_obj.ModelName = model_name
        node_obj.Label = f"ノード {model_name}.{start_surf + k}"
        face_group.addObject(node_obj)
        node_list.append(node_obj)
        if FreeCAD.GuiUp:
            vp = node_obj.ViewObject
            vp.PointSize = get_pref_node_point_size_sub()
            vp.PointColor = (1.0, 1.0, 0.0)  # 黄色
    if merge_subs_into_one_node:
        node_main = doc.getObject(_node_name_for_face(model_name, face_index)) or doc.getObject(f"Node_{face_index}")
        if node_main and node_main in _face_group_members(face_group):
            if not hasattr(node_main, "NodeNumber"):
                node_main.addProperty("App::PropertyInteger", "NodeNumber", "Thermal", "ノード番号")
            node_main.NodeNumber = getattr(face_group, "SurfaceNumber", face_index)

    # サブを1つ以上作成した場合のみ、元のサーフェースとノードをツリーから削除する（FaceSurfaces は廃止）
    has_subs = any(
        "_sub_" in getattr(o, "Name", "") and "Face_" in o.Name and "_front" in o.Name for o in face_group.Group
    )
    if has_subs:
        if not merge_subs_into_one_node:
            node_obj = doc.getObject(_node_name_for_face(model_name, face_index)) or doc.getObject(f"Node_{face_index}")
            if node_obj and node_obj in face_group.Group:
                face_group.removeObject(node_obj)
        back_name_new = _face_mesh_name(model_name, face_index, "back")
        back_name_old = f"Face_{face_index}_back"
        names_to_remove = {front_name_new, front_name_old, back_name_new, back_name_old}
        if not merge_subs_into_one_node:
            names_to_remove.add(_node_name_for_face(model_name, face_index))
            names_to_remove.add(f"Node_{face_index}")
        for name in names_to_remove:
            obj = doc.getObject(name)
            if obj is not None:
                try:
                    if obj in getattr(face_group, "Group", []):
                        face_group.removeObject(obj)
                    doc.removeObject(obj.Name)
                except Exception:
                    pass


# (以降の get_... visualize_... calculate_... 関数は変更なし)
# ...
def get_face_mesh_objects_from_selection():
    """
    後方互換のために残している薄いラッパー。
    実装本体は `freecad_utils.get_face_mesh_objects_from_selection` に移動。
    """
    return freecad_utils.get_face_mesh_objects_from_selection()

# =========================================================
# DISPLAY / VISUALIZATION HELPERS
#
# !! TEMPORARY LOCATION — PLANNED TO MOVE TO post/ !!
# =====================================================
# All functions in this section belong in the post/
# package.  They live here only because the physical
# migration has not been completed yet.
#
# Migration status
# ----------------
# - Wrapper stubs already exist in post/__init__.py.
# - When a function is moved to post/, the stub in
#   post/__init__.py should be updated to call the new
#   location, and the implementation here removed.
# - Do NOT add new display/visualization functions here;
#   add them directly to post/ instead.
#
# Contents
# --------
#   - active-side / optical-property color contours
#   - temperature contour display after solver run
#         (parse_thermal_out is also temporary here;
#          it belongs in post/ as result I/O)
#   - color bar overlay widget
#   - conduction / radiation link visibility controls
#   - display preference getters (node size, line width …)
#   - surface and node number labels in the 3D view
#   - hover label on mouse-over
# =========================================================

def visualize_active_side():
    if not FreeCAD.GuiUp:
        return
    doc = FreeCAD.ActiveDocument
    if not doc:
        return
    # 処理中に選択がクリアされないよう保存し、終了後に復元する（プロパティ編集が押せるように）
    saved_selection = list(FreeCADGui.Selection.getSelection())
    face_meshes = get_all_face_meshes_for_bulk_properties(doc)
    if not face_meshes:
        FreeCAD.Console.PrintWarning(
            "ドキュメントに輻射モデル（FaceGroup）がありません。\n"
        )
        return
    FreeCAD.Console.PrintMessage("アクティブ面に応じて表示を更新します...\n")
    # 先に表裏の ActiveSide を同期してから色を決める（初回表示で「両面」が正しく黄になる）
    face_pairs = freecad_utils.build_face_pairs(face_meshes)
    for _base_name, sides in face_pairs.items():
        f_obj = sides.get("front")
        b_obj = sides.get("back")
        if f_obj and b_obj:
            freecad_utils.sync_active_side(f_obj, b_obj)
    green = (0.0, 1.0, 0.0)
    red = (1.0, 0.0, 0.0)
    yellow = (1.0, 1.0, 0.0)
    gray = (0.5, 0.5, 0.5)
    # 各メッシュを名前で表/裏判定し、1オブジェクトずつ色を設定（ペア取り違えを防ぐ）
    for face_obj in face_meshes:
        vp = face_obj.ViewObject
        active_side = getattr(face_obj, "ActiveSide", "両面")
        if face_obj.Name.endswith("_front"):
            if active_side == "表面":
                color = green
            elif active_side == "裏面":
                color = red
            elif active_side == "両面":
                color = yellow
            else:
                color = gray
        elif face_obj.Name.endswith("_back"):
            if active_side == "表面":
                color = red
            elif active_side == "裏面":
                color = green
            elif active_side == "両面":
                color = yellow
            else:
                color = gray
        else:
            color = gray
        vp.ShapeColor = color
        # メッシュの表示で使われる DiffuseColor も同期（3Dビュー反映のため）
        if hasattr(vp, "DiffuseColor") and hasattr(face_obj, "Mesh") and face_obj.Mesh and face_obj.Mesh.Facets:
            n_facets = len(face_obj.Mesh.Facets)
            vp.DiffuseColor = [tuple(color)] * n_facets
        vp.Lighting = "Two side"
    # 親グループが子の色を上書きしないようにする（プロパティがある場合のみ）
    for group in freecad_utils.get_face_groups(doc):
        if hasattr(group, "ViewObject") and hasattr(group.ViewObject, "OverrideMaterial"):
            try:
                group.ViewObject.OverrideMaterial = False
            except Exception:
                pass
        for child in getattr(group, "Group", []) or []:
            if hasattr(child, "ViewObject") and hasattr(child.ViewObject, "OverrideMaterial"):
                try:
                    child.ViewObject.OverrideMaterial = False
                except Exception:
                    pass
    freecad_utils.apply_active_side_visibility(face_meshes)
    doc.recompute()
    if FreeCAD.GuiUp:
        FreeCADGui.updateGui()
        # 選択を復元（recompute/updateGui で選択が外れる場合にプロパティ編集が有効のままになるように）
        if saved_selection:
            try:
                FreeCADGui.Selection.clearSelection()
                for obj in saved_selection:
                    if obj is not None and getattr(obj, "isValid", lambda: True)():
                        FreeCADGui.Selection.addSelection(obj)
                FreeCADGui.updateGui()
            except Exception:
                pass
    FreeCAD.Console.PrintMessage("表示の更新が完了しました。\n")

# 吸収率・放射率コンター: 0～1 を何段階で表示するか
_CONTOUR_NUM_LEVELS = 10


def visualize_property_contour(prop_name, prop_label):
    """ドキュメント全体の面メッシュを対象に、指定プロパティのコンター表示を行う（アクティブ面表示と同様）。"""
    if not FreeCAD.GuiUp:
        return
    doc = FreeCAD.ActiveDocument
    if not doc:
        return
    saved_selection = list(FreeCADGui.Selection.getSelection())
    face_meshes = get_all_face_meshes_for_bulk_properties(doc)
    if not face_meshes:
        FreeCAD.Console.PrintWarning(
            "ドキュメントに輻射モデル（FaceGroup）がありません。\n"
        )
        return
    values = []
    for face_obj in face_meshes:
        if hasattr(face_obj, prop_name):
            values.append(getattr(face_obj, prop_name))
    if not values:
        FreeCAD.Console.PrintError(
            f"対象オブジェクトにプロパティ '{prop_label}' が見つかりません。\n"
        )
        return
    FreeCAD.Console.PrintMessage(f"'{prop_label}' の値に応じてコンター表示を更新します（ドキュメント全体）...\n")
    n_levels = _CONTOUR_NUM_LEVELS
    # 0～1 の範囲で n_levels 段階のコンター（青=0 ～ 赤=1）
    for face_obj in face_meshes:
        vp = face_obj.ViewObject
        vp.Lighting = "Two side"
        if hasattr(face_obj, prop_name):
            value = getattr(face_obj, prop_name)
            v_clamp = max(0.0, min(1.0, float(value)))
            step = min(n_levels - 1, int(v_clamp * n_levels))
            t = step / (n_levels - 1) if n_levels > 1 else 1.0
            red = t
            blue = 1.0 - t
            color = (red, 0.0, blue)
            vp.ShapeColor = color
            if hasattr(vp, "DiffuseColor") and hasattr(face_obj, "Mesh") and face_obj.Mesh and face_obj.Mesh.Facets:
                n_facets = len(face_obj.Mesh.Facets)
                vp.DiffuseColor = [tuple(color)] * n_facets
        else:
            vp.ShapeColor = (0.5, 0.5, 0.5)
    for group in freecad_utils.get_face_groups(doc):
        if hasattr(group, "ViewObject") and hasattr(group.ViewObject, "OverrideMaterial"):
            try:
                group.ViewObject.OverrideMaterial = False
            except Exception:
                pass
        for child in getattr(group, "Group", []) or []:
            if hasattr(child, "ViewObject") and hasattr(child.ViewObject, "OverrideMaterial"):
                try:
                    child.ViewObject.OverrideMaterial = False
                except Exception:
                    pass
    freecad_utils.apply_active_side_visibility(face_meshes)
    doc.recompute()
    if FreeCAD.GuiUp:
        FreeCADGui.updateGui()
        if saved_selection:
            try:
                FreeCADGui.Selection.clearSelection()
                for obj in saved_selection:
                    if obj is not None and getattr(obj, "isValid", lambda: True)():
                        FreeCADGui.Selection.addSelection(obj)
                FreeCADGui.updateGui()
            except Exception:
                pass
    min_val, max_val = min(values), max(values)
    bounds = [i / (n_levels - 1) for i in range(n_levels)]
    FreeCAD.Console.PrintMessage(
        f"コンター凡例 (0～1 を{n_levels}段階): 青={bounds[0]:.1f}"
    )
    for v in bounds[1:-1]:
        FreeCAD.Console.PrintMessage(f", {v:.1f}")
    FreeCAD.Console.PrintMessage(f" 赤={bounds[-1]:.1f}\n")
    FreeCAD.Console.PrintMessage(
        f"  (データ範囲: 最小 {min_val:.4g} ～ 最大 {max_val:.4g})\n"
    )
    FreeCAD.Console.PrintMessage("コンター表示の更新が完了しました。\n")
    show_contour_color_bar(0.0, 1.0, unit="", title=prop_label)


def parse_thermal_out(filepath):
    """
    熱解析 .out ファイルをパースし、各時刻のノード温度 dict のリストを返す。
    戻り値: list of (time_value: float, node_temperatures: dict[str, float])
    例: [(0.0, {"BASE.0": 20.0, "BASE.1001": 20.0, ...}), (600.0, {...}), ...]
    """
    import re
    result = []
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except Exception as e:
        raise RuntimeError(f".out ファイルを開けません: {e}") from e
    blocks = re.split(r"\n\s*Time\s*=\s*", content, flags=re.IGNORECASE)
    for i, block in enumerate(blocks):
        block = block.strip()
        if not block:
            continue
        if i == 0:
            if block.startswith("Time") or "Time =" in block[:20]:
                first_line, _, rest = block.partition("\n")
                time_match = re.search(r"Time\s*=\s*([\d.eE+-]+)", first_line, re.IGNORECASE)
                time_val = float(time_match.group(1)) if time_match else 0.0
                block = rest
            else:
                time_val = 0.0
        else:
            first_line, _, rest = block.partition("\n")
            time_match = re.search(r"^([\d.eE+-]+)", first_line.strip())
            time_val = float(time_match.group(1)) if time_match else 0.0
            block = rest
        if "[NODES]" not in block:
            continue
        _, nodes_section = block.split("[NODES]", 1)
        if "[CONDUCTORS]" in nodes_section:
            nodes_section = nodes_section.split("[CONDUCTORS]")[0]
        node_temps = {}
        for line in nodes_section.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            node_id = parts[0]
            if node_id == "SPACE.9999":
                continue
            try:
                temp = float(parts[1])
            except ValueError:
                continue
            node_temps[node_id] = temp
        result.append((time_val, node_temps))
    return result


def visualize_temperature_contour(temperatures_by_node_id, t_min, t_max):
    """
    .out から得たノード温度 dict で、輻射モデル面をコンター表示する。
    t_min, t_max: 表示範囲 [℃]。この範囲を青(低)～赤(高)にマッピングする。
    """
    if not FreeCAD.GuiUp:
        return
    doc = FreeCAD.ActiveDocument
    if not doc:
        FreeCAD.Console.PrintWarning("アクティブなドキュメントがありません。\n")
        return
    face_groups = freecad_utils.get_face_groups(doc)
    if not face_groups:
        FreeCAD.Console.PrintWarning("ドキュメントに輻射モデル（FaceGroup）がありません。\n")
        return
    model_name = getattr(face_groups[0], "ModelName", None) or "Model"
    default_color = (0.5, 0.5, 0.5)
    t_range = t_max - t_min
    if t_range <= 0:
        t_range = 1.0
    for group in face_groups:
        for (front_face, node) in _iter_face_groups_front_and_node([group]):
            node_id = f"{model_name}.{getattr(node, 'NodeNumber', 0)}"
            temp = temperatures_by_node_id.get(node_id)
            if temp is None:
                color = default_color
            else:
                t_norm = (temp - t_min) / t_range
                t_norm = max(0.0, min(1.0, t_norm))
                red = t_norm
                blue = 1.0 - t_norm
                color = (red, 0.0, blue)
            vp = front_face.ViewObject
            vp.Lighting = "Two side"
            vp.ShapeColor = color
            if hasattr(vp, "DiffuseColor") and hasattr(front_face, "Mesh") and front_face.Mesh and front_face.Mesh.Facets:
                n_facets = len(front_face.Mesh.Facets)
                vp.DiffuseColor = [tuple(color)] * n_facets
            back_name = front_face.Name.replace("_front", "_back")
            back_obj = doc.getObject(back_name)
            if back_obj:
                vp_back = back_obj.ViewObject
                vp_back.Lighting = "Two side"
                vp_back.ShapeColor = color
                if hasattr(vp_back, "DiffuseColor") and hasattr(back_obj, "Mesh") and back_obj.Mesh and back_obj.Mesh.Facets:
                    n_f = len(back_obj.Mesh.Facets)
                    vp_back.DiffuseColor = [tuple(color)] * n_f
    for group in freecad_utils.get_face_groups(doc):
        if hasattr(group, "ViewObject") and hasattr(group.ViewObject, "OverrideMaterial"):
            try:
                group.ViewObject.OverrideMaterial = False
            except Exception:
                pass
        for child in getattr(group, "Group", []) or []:
            if hasattr(child, "ViewObject") and hasattr(child.ViewObject, "OverrideMaterial"):
                try:
                    child.ViewObject.OverrideMaterial = False
                except Exception:
                    pass
    doc.recompute()
    if FreeCAD.GuiUp:
        FreeCADGui.updateGui()
    show_contour_color_bar(t_min, t_max, unit="℃", title="温度")


# デフォルト表示用の単色（アクティブ面・吸収率・放射率の色分けをやめるときに使用）
_DEFAULT_DISPLAY_COLOR = (0.8, 0.8, 0.8)

# コンター用カラーバー（ThermalAnalysis 用、モジュール内で 1 つだけ保持）
_contour_color_bar_widget = None


def _get_qt():
    try:
        from PySide2 import QtWidgets, QtCore, QtGui
        return QtWidgets, QtCore, QtGui
    except ImportError:
        from PySide import QtGui
        QtWidgets = QtGui
        QtCore = QtGui
        return QtWidgets, QtCore, QtGui


class _ContourColorBarWidget(object):
    def __init__(self):
        self._widget = None
        self._bar = None
        self._label_min = None
        self._label_max = None
        self._label_title = None
        self._v_min = 0.0
        self._v_max = 1.0
        self._unit = ""
        self._title = ""

    def _build(self):
        QtWidgets, QtCore, QtGui = _get_qt()
        main = QtWidgets.QWidget(None)
        main.setObjectName("TA_ContourColorBar")
        main.setWindowFlags(QtCore.Qt.Tool | QtCore.Qt.FramelessWindowHint | QtCore.Qt.WindowStaysOnTopHint)
        main.setAttribute(QtCore.Qt.WA_TranslucentBackground, False)
        main.setStyleSheet("background-color: rgba(40, 40, 40, 220); border: 1px solid #666; border-radius: 4px;")
        layout = QtWidgets.QVBoxLayout(main)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(2)
        if self._label_title is None:
            self._label_title = QtWidgets.QLabel("")
            self._label_title.setStyleSheet("color: #eee; font-weight: bold;")
            layout.addWidget(self._label_title)
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(6)
        if self._bar is None:
            BarClass = _make_color_bar_strip_class()
            self._bar = BarClass(main)
        row.addWidget(self._bar, 0)
        labels = QtWidgets.QVBoxLayout()
        labels.setSpacing(0)
        if self._label_max is None:
            self._label_max = QtWidgets.QLabel("")
            self._label_max.setStyleSheet("color: #fff; font-size: 11px;")
        if self._label_min is None:
            self._label_min = QtWidgets.QLabel("")
            self._label_min.setStyleSheet("color: #fff; font-size: 11px;")
        labels.addWidget(self._label_max)
        labels.addStretch(1)
        labels.addWidget(self._label_min)
        row.addLayout(labels, 1)
        layout.addLayout(row)
        main.setFixedSize(100, 180)
        self._widget = main

    def update_range(self, v_min, v_max, unit="", title=None):
        self._v_min = v_min
        self._v_max = v_max
        self._unit = unit or ""
        self._title = title or ""
        if self._widget is None:
            self._build()
        self._label_max.setText(_format_contour_label(v_max, self._unit))
        self._label_min.setText(_format_contour_label(v_min, self._unit))
        self._label_title.setText(self._title)
        self._bar.setRange(v_min, v_max)

    def show_bar(self):
        if self._widget is None:
            return
        self._widget.show()
        mw = FreeCADGui.getMainWindow()
        if mw and mw.isVisible():
            mw_rect = mw.geometry()
            x = mw_rect.right() - self._widget.width() - 24
            y = mw_rect.bottom() - self._widget.height() - 24
            self._widget.move(x, y)

    def hide_bar(self):
        if self._widget is not None:
            self._widget.hide()


def _make_color_bar_strip_class():
    try:
        from PySide2 import QtWidgets, QtGui
        base = QtWidgets.QWidget
    except ImportError:
        from PySide import QtGui
        base = QtGui.QWidget
    class _ColorBarStrip(base):
        def __init__(self, parent=None):
            base.__init__(self, parent)
            self._v_min = 0.0
            self._v_max = 1.0
            self.setFixedSize(24, 140)
        def setRange(self, v_min, v_max):
            self._v_min = v_min
            self._v_max = v_max
            self.update()
        def paintEvent(self, event):
            try:
                from PySide2 import QtGui as QG
            except ImportError:
                from PySide import QtGui as QG
            qp = QG.QPainter(self)
            try:
                qp.setRenderHint(QG.QPainter.Antialiasing)
                rect = self.rect()
                grad = QG.QLinearGradient(0, rect.height(), 0, 0)
                grad.setColorAt(0.0, QG.QColor(0, 0, 255))
                grad.setColorAt(1.0, QG.QColor(255, 0, 0))
                qp.fillRect(rect, grad)
                qp.setPen(QG.QColor(200, 200, 200))
                qp.drawRect(rect.adjusted(0, 0, -1, -1))
            finally:
                qp.end()
    return _ColorBarStrip


def _format_contour_label(value, unit):
    if abs(value) >= 1e4 or (abs(value) < 0.01 and value != 0):
        s = "{:.2g}".format(value)
    else:
        s = "{:.3g}".format(value)
    return s + (" " + unit if unit else "")


def show_contour_color_bar(v_min, v_max, unit="", title=None):
    if not FreeCAD.GuiUp:
        return
    global _contour_color_bar_widget
    if _contour_color_bar_widget is None:
        _contour_color_bar_widget = _ContourColorBarWidget()
    _contour_color_bar_widget.update_range(v_min, v_max, unit=unit, title=title)
    _contour_color_bar_widget.show_bar()


def hide_contour_color_bar():
    global _contour_color_bar_widget
    if _contour_color_bar_widget is not None:
        _contour_color_bar_widget.hide_bar()


def restore_default_display():
    """
    アクティブ面表示・吸収率・放射率のコンター表示をやめ、
    全面メッシュをデフォルト色に戻す。オフセットも解除する。
    """
    if not FreeCAD.GuiUp:
        return
    doc = FreeCAD.ActiveDocument
    if not doc:
        return
    face_meshes = get_all_face_meshes_for_bulk_properties(doc)
    if not face_meshes:
        FreeCAD.Console.PrintMessage("輻射モデル（FaceGroup）がありません。\n")
        return
    color = _DEFAULT_DISPLAY_COLOR
    for face_obj in face_meshes:
        vp = getattr(face_obj, "ViewObject", None)
        if not vp:
            continue
        vp.ShapeColor = color
        if hasattr(face_obj, "Mesh") and face_obj.Mesh and face_obj.Mesh.Facets:
            n_facets = len(face_obj.Mesh.Facets)
            if hasattr(vp, "DiffuseColor"):
                vp.DiffuseColor = [tuple(color)] * n_facets
    freecad_utils.clear_face_pair_offset(face_meshes)
    hide_contour_color_bar()
    doc.recompute()
    if FreeCAD.GuiUp:
        FreeCADGui.updateGui()
    FreeCAD.Console.PrintMessage("表示をデフォルトに戻しました。\n")


def _get_conduction_conductance_groups(doc):
    """ドキュメント内の伝熱コンダクタンスグループ（*_ConductanceLinks）のリストを返す。"""
    if not doc:
        return []
    return [o for o in doc.Objects if hasattr(o, "Group") and o.Name.endswith("_ConductanceLinks")]


def _get_radiation_conductance_groups(doc):
    """ドキュメント内の輻射コンダクタンスグループ（*_RadiationLinks）のリストを返す。"""
    if not doc:
        return []
    return [o for o in doc.Objects if hasattr(o, "Group") and o.Name.endswith("_RadiationLinks")]


def set_conduction_conductance_visibility(visible):
    """伝熱コンダクタンス（線）の表示・非表示を一括設定する。"""
    doc = FreeCAD.ActiveDocument
    if not doc or not FreeCAD.GuiUp:
        return
    for group in _get_conduction_conductance_groups(doc):
        if hasattr(group, "ViewObject") and group.ViewObject is not None:
            group.ViewObject.Visibility = bool(visible)
    if FreeCAD.GuiUp:
        FreeCADGui.updateGui()


def set_radiation_conductance_visibility(visible):
    """輻射コンダクタンス（線）の表示・非表示を一括設定する。"""
    doc = FreeCAD.ActiveDocument
    if not doc or not FreeCAD.GuiUp:
        return
    for group in _get_radiation_conductance_groups(doc):
        if hasattr(group, "ViewObject") and group.ViewObject is not None:
            group.ViewObject.Visibility = bool(visible)
    if FreeCAD.GuiUp:
        FreeCADGui.updateGui()


def get_conduction_conductance_visibility():
    """伝熱コンダクタンスの現在の表示状態を返す。(visible, has_any) のタプル。"""
    doc = FreeCAD.ActiveDocument
    groups = _get_conduction_conductance_groups(doc) if doc else []
    if not groups:
        return (True, False)
    vp = getattr(groups[0], "ViewObject", None)
    return (bool(vp.Visibility) if vp is not None else True, True)


def get_radiation_conductance_visibility():
    """輻射コンダクタンスの現在の表示状態を返す。(visible, has_any) のタプル。"""
    doc = FreeCAD.ActiveDocument
    groups = _get_radiation_conductance_groups(doc) if doc else []
    if not groups:
        return (True, False)
    vp = getattr(groups[0], "ViewObject", None)
    return (bool(vp.Visibility) if vp is not None else True, True)


def set_node_visibility(visible):
    """輻射モデル内の全ノード（Node_*）の表示・非表示を一括設定する。"""
    doc = FreeCAD.ActiveDocument
    if not doc or not FreeCAD.GuiUp:
        return
    face_groups = freecad_utils.get_face_groups(doc)
    for fg in face_groups or []:
        for obj in _face_group_members(fg):
            if getattr(obj, "Name", "").startswith("Node_"):
                if hasattr(obj, "ViewObject") and obj.ViewObject is not None:
                    obj.ViewObject.Visibility = bool(visible)
    if FreeCAD.GuiUp:
        FreeCADGui.updateGui()


def get_node_visibility():
    """ノードの現在の表示状態を返す。(visible, has_any) のタプル。"""
    doc = FreeCAD.ActiveDocument
    face_groups = freecad_utils.get_face_groups(doc) if doc else []
    first_node = None
    for fg in face_groups or []:
        for obj in _face_group_members(fg):
            if getattr(obj, "Name", "").startswith("Node_"):
                first_node = obj
                break
        if first_node is not None:
            break
    if first_node is None:
        return (True, False)
    vp = getattr(first_node, "ViewObject", None)
    return (bool(vp.Visibility) if vp is not None else True, True)


# コンダクタンス線の表示: 線の太さ [px]、伝導は青系・輻射はオレンジ系（デフォルト値）
_RA_CONDUCTANCE_LINE_WIDTH_DEFAULT = 2.5
_RA_CONDUCTION_LINE_COLOR_DEFAULT = (0.2, 0.5, 1.0)
_RA_RADIATION_LINE_COLOR_DEFAULT = (1.0, 0.35, 0.0)

_DISPLAY_PREFS = "User parameter:Base/App/Preferences/Mod/ThermalAnalysis"


def _get_display_prefs():
    """表示・伝導パラメータ用 ParamGet を返す。"""
    return FreeCAD.ParamGet(_DISPLAY_PREFS)


def get_pref_node_point_size_default():
    return _get_display_prefs().GetInt("NodePointSizeDefault", 14)


def get_pref_node_point_size_sub():
    return _get_display_prefs().GetInt("NodePointSizeSub", 10)


def get_pref_node_sphere_fraction_face():
    return _get_display_prefs().GetFloat("NodeSphereFractionFace", 0.12)


def get_pref_node_sphere_fraction_global():
    return _get_display_prefs().GetFloat("NodeSphereFractionGlobal", 0.03)


def get_pref_node_sphere_radius_min_mm():
    return _get_display_prefs().GetFloat("NodeSphereRadiusMinMm", 0.5)


def get_pref_node_sphere_radius_max_mm():
    return _get_display_prefs().GetFloat("NodeSphereRadiusMaxMm", 500.0)


def get_pref_node_point_size_divisor():
    return _get_display_prefs().GetFloat("NodePointSizeDivisor", 1.2)


def get_pref_conductance_line_width():
    return _get_display_prefs().GetFloat("ConductanceLineWidth", _RA_CONDUCTANCE_LINE_WIDTH_DEFAULT)


def get_pref_conduction_line_color():
    p = _get_display_prefs()
    r = p.GetFloat("ConductionLineColorR", _RA_CONDUCTION_LINE_COLOR_DEFAULT[0])
    g = p.GetFloat("ConductionLineColorG", _RA_CONDUCTION_LINE_COLOR_DEFAULT[1])
    b = p.GetFloat("ConductionLineColorB", _RA_CONDUCTION_LINE_COLOR_DEFAULT[2])
    return (r, g, b)


def get_pref_radiation_line_color():
    p = _get_display_prefs()
    r = p.GetFloat("RadiationLineColorR", _RA_RADIATION_LINE_COLOR_DEFAULT[0])
    g = p.GetFloat("RadiationLineColorG", _RA_RADIATION_LINE_COLOR_DEFAULT[1])
    b = p.GetFloat("RadiationLineColorB", _RA_RADIATION_LINE_COLOR_DEFAULT[2])
    return (r, g, b)


def get_pref_edge_node_tolerance_mm():
    return _get_display_prefs().GetFloat("EdgeNodeToleranceMm", 5.0)


def get_pref_label_scale_percent():
    """番号ラベルのサイズ倍率（%）。100 で面対角線の 20% を基準サイズとする。"""
    return _get_display_prefs().GetInt("LabelScalePercent", 100)


def get_pref_label_offset_mm():
    """番号ラベルを面/ノードの法線方向に押し出す追加オフセット距離 [mm]。
    0.0 ではノード球の縁にラベルを配置（従来の動作）。"""
    return _get_display_prefs().GetFloat("LabelOffsetMm", 0.0)


def _apply_conduction_link_view(link_obj):
    """伝熱コンダクタンスリンクの ViewObject に線の太さ・色を設定する。"""
    if not FreeCAD.GuiUp or not link_obj or not hasattr(link_obj, "ViewObject"):
        return
    vp = link_obj.ViewObject
    if hasattr(vp, "LineWidth"):
        vp.LineWidth = get_pref_conductance_line_width()
    if hasattr(vp, "LineColor"):
        vp.LineColor = get_pref_conduction_line_color()


def _apply_radiation_link_view(link_obj):
    """輻射コンダクタンスリンクの ViewObject に線の太さ・色を設定する。"""
    if not FreeCAD.GuiUp or not link_obj or not hasattr(link_obj, "ViewObject"):
        return
    vp = link_obj.ViewObject
    if hasattr(vp, "LineWidth"):
        vp.LineWidth = get_pref_conductance_line_width()
    if hasattr(vp, "LineColor"):
        vp.LineColor = get_pref_radiation_line_color()


# --- サーフェース番号・ノード番号表示とノードサイズ ---
_RA_LABELS_GROUP_SURF = "RA_SurfaceNumberLabels"
_RA_LABELS_GROUP_NODE = "RA_NodeNumberLabels"
_RA_HOVER_LABEL_GROUP = "RA_HoverLabel"
# 番号ラベルをノードで隠れないよう、アクティブ方向（面法線）先にオフセットする距離 [mm]。ノード直径が取れないときのフォールバック
_RA_LABEL_OFFSET_MM_FALLBACK = 5.0
# ラベル文字の基準を「面の何%」にするか。100%でこの割合が基準になる。
_RA_LABEL_BASE_FRACTION_FACE = 0.20  # 面の20%を基準（ノードデフォルトと同じ）
# ノード球サイズのデフォルト（設定で上書き可能）
_RA_NODE_SPHERE_FRACTION_FACE_DEFAULT = 0.12
_RA_NODE_SPHERE_FRACTION_GLOBAL_DEFAULT = 0.03
_RA_NODE_SPHERE_RADIUS_MIN_MM_DEFAULT = 0.5
_RA_NODE_SPHERE_RADIUS_MAX_MM_DEFAULT = 500.0


def _node_sphere_diameter_mm(node):
    """ノードが球の場合、その直径 [mm] を返す。それ以外はフォールバック値。"""
    if not hasattr(node, "Shape") or not node.Shape:
        return _RA_LABEL_OFFSET_MM_FALLBACK
    try:
        b = node.Shape.BoundBox
        return max(b.XMax - b.XMin, b.YMax - b.YMin, b.ZMax - b.ZMin, 1e-6)
    except Exception:
        return _RA_LABEL_OFFSET_MM_FALLBACK


def _placement_inverse(pl):
    """Placement の逆を返す。inverse() が無い環境では手動計算。"""
    inv = getattr(pl, "inverse", None) or getattr(pl, "inverted", None)
    if callable(inv):
        return inv()
    rot_inv = getattr(pl.Rotation, "inverse", None) or getattr(pl.Rotation, "inverted", None)
    if callable(rot_inv):
        r_inv = rot_inv()
    else:
        r_inv = pl.Rotation
    base_inv = r_inv.multVec(FreeCAD.Vector(-pl.Base.x, -pl.Base.y, -pl.Base.z))
    return FreeCAD.Placement(base_inv, r_inv)


def _get_global_placement(obj):
    """オブジェクトのグローバル Placement を返す。getGlobalPlacement が無い場合は親をたどって積算。"""
    try:
        pl = getattr(obj, "getGlobalPlacement", None)
        if callable(pl):
            return pl()
    except Exception:
        pass
    pl = getattr(obj, "Placement", None)
    if not pl:
        return None
    current = FreeCAD.Placement(pl)
    o = obj
    while getattr(o, "InList", None):
        parent = None
        for cand in o.InList:
            if getattr(cand, "Group", None) and o in cand.Group:
                parent = cand
                break
        if not parent:
            break
        try:
            current = parent.Placement.multiply(current)
        except Exception:
            break
        o = parent
    return current


def _node_position(node):
    """ノードの中心位置を世界（ドキュメント）座標で返す。Vertex または Sphere どちらでも可。親グループの Placement を含むグローバル座標。"""
    if not hasattr(node, "Shape") or not node.Shape:
        return None
    if node.Shape.Vertexes:
        local_pt = node.Shape.Vertexes[0].Point
    else:
        local_pt = node.Shape.CenterOfMass
    pl = _get_global_placement(node)
    if pl:
        out = pl.multVec(local_pt)
        # #region agent log
        if not getattr(_node_position, "_logged", False):
            _node_position._logged = True
            _dbg_log("core.py:_node_position", "position", {"nodeName": node.Name, "pos": [round(out.x, 2), round(out.y, 2), round(out.z, 2)], "hasGetGlobal": hasattr(node, "getGlobalPlacement")}, "H1")
        # #endregion
        return out
    return FreeCAD.Vector(local_pt.x, local_pt.y, local_pt.z)


def _mesh_outward_normal(mesh):
    """メッシュの外向き法線（単位ベクトル）を返す。失敗時は (0,0,1)。"""
    if not mesh or not hasattr(mesh, "Facets"):
        return (0, 0, 1)
    try:
        facets = mesh.Facets
        points = mesh.Points
        if not facets or not points:
            return (0, 0, 1)
        sum_nx, sum_ny, sum_nz = 0.0, 0.0, 0.0
        for fa in facets:
            if hasattr(fa, "PointIndices"):
                i, j, k = fa.PointIndices[0], fa.PointIndices[1], fa.PointIndices[2]
            else:
                i, j, k = fa[0], fa[1], fa[2]
            p0, p1, p2 = points[i], points[j], points[k]
            e1 = (p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2])
            e2 = (p2[0] - p0[0], p2[1] - p0[1], p2[2] - p0[2])
            nx = e1[1] * e2[2] - e1[2] * e2[1]
            ny = e1[2] * e2[0] - e1[0] * e2[2]
            nz = e1[0] * e2[1] - e1[1] * e2[0]
            nlen = math.sqrt(nx * nx + ny * ny + nz * nz)
            if nlen > 1e-18:
                sum_nx += nx / nlen
                sum_ny += ny / nlen
                sum_nz += nz / nlen
        nlen = math.sqrt(sum_nx * sum_nx + sum_ny * sum_ny + sum_nz * sum_nz)
        if nlen < 1e-18:
            return (0, 0, 1)
        return (sum_nx / nlen, sum_ny / nlen, sum_nz / nlen)
    except Exception:
        return (0, 0, 1)


def _local_normal_to_global(face_obj, local_normal):
    """面オブジェクトのローカル法線をグローバル座標の単位ベクトルで返す。"""
    if not face_obj or not local_normal:
        return (0, 0, 1)
    try:
        pl = getattr(face_obj, "getGlobalPlacement", None)
        if callable(pl):
            placement = pl()
        else:
            placement = getattr(face_obj, "Placement", None)
        if not placement or not hasattr(placement, "Rotation"):
            return (local_normal[0], local_normal[1], local_normal[2])
        v = placement.Rotation.multVec(FreeCAD.Vector(local_normal[0], local_normal[1], local_normal[2]))
        nlen = math.sqrt(v.x * v.x + v.y * v.y + v.z * v.z)
        if nlen < 1e-18:
            return (0, 0, 1)
        return (v.x / nlen, v.y / nlen, v.z / nlen)
    except Exception:
        return (local_normal[0], local_normal[1], local_normal[2])


def _get_default_font_path():
    """ShapeString 用のデフォルトフォントパスを返す。"""
    import os
    if os.name == "nt":
        p = os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts", "arial.ttf")
        # #region agent log
        _dbg_log("core.py:_get_default_font_path", "font path result", {"path": p, "exists": os.path.isfile(p) if p else False}, "H1")
        # #endregion
        return p
    for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/TTF/DejaVuSans.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"):
        if os.path.isfile(path):
            # #region agent log
            _dbg_log("core.py:_get_default_font_path", "font path result", {"path": path, "exists": True}, "H1")
            # #endregion
            return path
    # #region agent log
    _dbg_log("core.py:_get_default_font_path", "font path empty", {"path": ""}, "H1")
    # #endregion
    return ""


def _create_number_label(doc, base_name, text, position_mm, size_mm=10.0, unique_index=0):
    """3D 空間に番号ラベル用の形状を作成する。Part.ShapeString を押し出して3Dで見えるようにする。"""
    font = _get_default_font_path()
    # #region agent log
    _dbg_log("core.py:_create_number_label", "entry", {"has_font": bool(font), "has_ShapeString": hasattr(Part, "ShapeString"), "text": str(text), "size_mm": size_mm}, "H2")
    # #endregion
    if font and hasattr(Part, "ShapeString"):
        try:
            ss = Part.ShapeString(str(text), font, size_mm)
            # #region agent log
            _inv = getattr(ss, "isNull", None)
            _dbg_log("core.py:_create_number_label", "after ShapeString", {"isNull": _inv() if callable(_inv) else _inv, "hasFaces": bool(getattr(ss, "Faces", None)), "hasEdges": bool(getattr(ss, "Edges", None)), "hasWires": bool(getattr(ss, "Wires", None))}, "H2")
            # #endregion
            if ss.isNull() or (not ss.Faces and not ss.Edges):
                raise ValueError("ShapeString empty")
            name = f"{base_name}_{unique_index}"
            while doc.getObject(name):
                unique_index += 1
                name = f"{base_name}_{unique_index}"
            obj = doc.addObject("Part::Feature", name)
            # 2D文字をZ方向に薄く押し出して3Dで確実に表示
            try:
                depth = max(0.5, size_mm * 0.1)
                vec = FreeCAD.Vector(0, 0, depth)
                if getattr(ss, "Wires", None) and len(ss.Wires) > 0:
                    ext = Part.makeExtrude(ss.Wires, vec)
                elif getattr(ss, "Faces", None) and len(ss.Faces) > 0:
                    ext = Part.makeExtrude(ss.Faces, vec)
                else:
                    ext = Part.makeExtrude(ss, vec)
                if ext and not ext.isNull():
                    obj.Shape = ext
                else:
                    obj.Shape = ss
            except Exception as ex:
                obj.Shape = ss
                # #region agent log
                _dbg_log("core.py:_create_number_label", "extrude fallback to ss", {"error": str(type(ex).__name__)}, "H2")
                # #endregion
            obj.Placement.Base = FreeCAD.Vector(position_mm[0], position_mm[1], position_mm[2])
            obj.Label = str(text)
            # #region agent log
            _dbg_log("core.py:_create_number_label", "return Part obj", {"name": obj.Name}, "H2")
            # #endregion
            return obj
        except Exception as ex:
            # #region agent log
            _dbg_log("core.py:_create_number_label", "ShapeString branch exception", {"error": str(type(ex).__name__), "msg": str(ex)}, "H2")
            # #endregion
            pass
    # Part.ShapeString が無い環境用: Draft.make_shape_string で Shape を取得し押し出して Part::Feature で表示
    if font:
        try:
            import Draft
            make_ss = getattr(Draft, "make_shape_string", None) or getattr(Draft, "makeShapeString", None)
            if make_ss:
                try:
                    dss = make_ss(String=str(text), FontFile=font, Size=size_mm)
                except (TypeError, Exception):
                    try:
                        dss = make_ss(str(text), font, size_mm)
                    except (TypeError, Exception):
                        dss = None
                if dss and getattr(dss, "Shape", None):
                    _sn = getattr(dss.Shape, "isNull", None)
                    if _sn and callable(_sn) and _sn():
                        doc.removeObject(dss.Name)
                        dss = None
                if dss and getattr(dss, "Shape", None):
                    ss = dss.Shape
                    doc.removeObject(dss.Name)
                    name = f"{base_name}_{unique_index}"
                    while doc.getObject(name):
                        unique_index += 1
                        name = f"{base_name}_{unique_index}"
                    obj = doc.addObject("Part::Feature", name)
                    try:
                        depth = max(0.5, size_mm * 0.1)
                        vec = FreeCAD.Vector(0, 0, depth)
                        if getattr(ss, "Wires", None) and len(ss.Wires) > 0:
                            ext = Part.makeExtrude(ss.Wires, vec)
                        elif getattr(ss, "Faces", None) and len(ss.Faces) > 0:
                            ext = Part.makeExtrude(ss.Faces, vec)
                        else:
                            ext = Part.makeExtrude(ss, vec)
                        if ext and not ext.isNull():
                            obj.Shape = ext
                        else:
                            obj.Shape = ss
                    except Exception:
                        obj.Shape = ss
                    obj.Placement.Base = FreeCAD.Vector(position_mm[0], position_mm[1], position_mm[2])
                    obj.Label = str(text)
                    return obj
        except Exception:
            pass
    try:
        import Draft
        if hasattr(Draft, "make_text"):
            txt = Draft.make_text(str(text), FreeCAD.Vector(position_mm[0], position_mm[1], position_mm[2]), screen=False)
            if txt and hasattr(txt, "ViewObject"):
                for prop in ("FontSize", "TextSize", "FontSizeMultiplier"):
                    if hasattr(txt.ViewObject, prop):
                        setattr(txt.ViewObject, prop, size_mm)
                        break
            # #region agent log
            _dbg_log("core.py:_create_number_label", "return Draft", {"ok": txt is not None}, "H5")
            # #endregion
            return txt
    except Exception as ex:
        # #region agent log
        _dbg_log("core.py:_create_number_label", "Draft exception", {"error": str(type(ex).__name__)}, "H5")
        # #endregion
        pass
    # #region agent log
    _dbg_log("core.py:_create_number_label", "return None", {}, "H2")
    # #endregion
    return None


def _update_surface_number_labels(doc, face_groups, label_scale_percent=100):
    """FaceGroup のサーフェース番号ラベルを再作成する。ラベルは面法線方向にノード直径分オフセットして配置。文字サイズは面の20%を基準。"""
    # #region agent log
    _dbg_log("core.py:_update_surface_number_labels", "entry", {"face_groups_count": len(face_groups) if face_groups else 0, "label_scale_percent": label_scale_percent}, "H4")
    # #endregion
    if not _get_default_font_path():
        FreeCAD.Console.PrintWarning("番号ラベル用フォントが見つかりません。Windows: Fonts/arial.ttf 等を確認してください。\n")
    group = doc.getObject(_RA_LABELS_GROUP_SURF)
    if not group:
        group = doc.addObject("App::DocumentObjectGroup", _RA_LABELS_GROUP_SURF)
        group.Label = "サーフェース番号"
        if FreeCAD.GuiUp and hasattr(group, "ViewObject"):
            group.ViewObject.Visibility = True
    for o in list(group.Group):
        group.removeObject(o)
        try:
            doc.removeObject(o.Name)
        except Exception:
            pass
    for g in face_groups:
        surf_num = getattr(g, "SurfaceNumber", None)
        if surf_num is None:
            continue
        pos = None
        front_face = None
        node_obj = None
        for obj in _face_group_members(g):
            if obj.Name.endswith("_front") and hasattr(obj, "Mesh"):
                front_face = obj
            if obj.Name.startswith("Node_"):
                pos = _node_position(obj)
                if pos is not None:
                    node_obj = obj
                    break
        if pos is None and front_face and getattr(front_face, "Mesh", None):
            pos = front_face.Mesh.BoundBox.Center
        if pos is None:
            continue
        if front_face is None:
            for obj in _face_group_members(g):
                if obj.Name.endswith("_front") and hasattr(obj, "Mesh"):
                    front_face = obj
                    break
        # ラベル文字サイズ: 面の20%を基準に、label_scale_percent でスケール（100%で面の20%）
        face_diag = 10.0
        if front_face and getattr(front_face, "Mesh", None):
            b = front_face.Mesh.BoundBox
            face_diag = math.sqrt((b.XMax - b.XMin) ** 2 + (b.YMax - b.YMin) ** 2 + (b.ZMax - b.ZMin) ** 2)
        if face_diag < 1e-6:
            face_diag = 10.0
        base_size_mm = face_diag * _RA_LABEL_BASE_FRACTION_FACE
        size_mm = max(1.0, min(200.0, base_size_mm * float(label_scale_percent) / 100.0))
        px = pos.x if hasattr(pos, "x") else float(pos[0])
        py = pos.y if hasattr(pos, "y") else float(pos[1])
        pz = pos.z if hasattr(pos, "z") else float(pos[2])
        # オフセット = ノード球半径 + ユーザー設定の追加オフセット
        off = ((_node_sphere_diameter_mm(node_obj) * 0.5) if node_obj else _RA_LABEL_OFFSET_MM_FALLBACK) + get_pref_label_offset_mm()
        if front_face and getattr(front_face, "Mesh", None):
            normal_local = _mesh_outward_normal(front_face.Mesh)
            normal = _local_normal_to_global(front_face, normal_local)
            pos_vec = (px + normal[0] * off, py + normal[1] * off, pz + normal[2] * off)
        else:
            pos_vec = (px, py, pz)
        # #region agent log
        if not getattr(_update_surface_number_labels, "_first_logged", False):
            _update_surface_number_labels._first_logged = True
            parent = group.InList[0] if getattr(group, "InList", None) and len(group.InList) else None
            parent_base = list(parent.Placement.Base) if parent and getattr(parent, "Placement", None) else None
            _dbg_log("core.py:_update_surface_number_labels", "first label pos", {"node_pos": [round(px, 2), round(py, 2), round(pz, 2)], "pos_vec": [round(pos_vec[0], 2), round(pos_vec[1], 2), round(pos_vec[2], 2)], "group_parent": parent.Name if parent else None, "parent_placement_base": parent_base}, "H3")
        # #endregion
        lbl = _create_number_label(doc, "RA_SurfLabel", surf_num, pos_vec, size_mm=size_mm, unique_index=surf_num)
        if lbl:
            group.addObject(lbl)
            if FreeCAD.GuiUp and hasattr(lbl, "ViewObject"):
                lbl.ViewObject.Visibility = True
    # #region agent log
    _dbg_log("core.py:_update_surface_number_labels", "after loop", {"group_count": len(group.Group) if group and group.Group else 0, "group_visibility": getattr(group.ViewObject, "Visibility", None) if group and FreeCAD.GuiUp and hasattr(group, "ViewObject") else None}, "H3")
    # #endregion
    if not group.Group and face_groups:
        FreeCAD.Console.PrintWarning("サーフェース番号ラベルを1つも作成できませんでした。フォントパスを確認してください。\n")
    doc.recompute()


def _update_node_number_labels(doc, face_groups, label_scale_percent=100):
    """全ノードのノード番号ラベルを再作成する。ラベルは面法線方向にノード直径分オフセット。文字サイズは面の20%を基準。"""
    # #region agent log
    _dbg_log("core.py:_update_node_number_labels", "entry", {"face_groups_count": len(face_groups) if face_groups else 0}, "H4")
    # #endregion
    group = doc.getObject(_RA_LABELS_GROUP_NODE)
    if not group:
        group = doc.addObject("App::DocumentObjectGroup", _RA_LABELS_GROUP_NODE)
        group.Label = "ノード番号"
        if FreeCAD.GuiUp and hasattr(group, "ViewObject"):
            group.ViewObject.Visibility = True
    for o in list(group.Group):
        group.removeObject(o)
        try:
            doc.removeObject(o.Name)
        except Exception:
            pass
    for idx, (_front_face, node) in enumerate(_iter_face_groups_front_and_node(face_groups)):
        pos = _node_position(node)
        if pos is None:
            continue
        num = getattr(node, "NodeNumber", 0)
        # ラベル文字サイズ: 面の20%を基準
        face_diag = 10.0
        if _front_face and getattr(_front_face, "Mesh", None):
            b = _front_face.Mesh.BoundBox
            face_diag = math.sqrt((b.XMax - b.XMin) ** 2 + (b.YMax - b.YMin) ** 2 + (b.ZMax - b.ZMin) ** 2)
        if face_diag < 1e-6:
            face_diag = 10.0
        base_size_mm = face_diag * _RA_LABEL_BASE_FRACTION_FACE
        size_mm = max(1.0, min(200.0, base_size_mm * float(label_scale_percent) / 100.0))
        px = pos.x if hasattr(pos, "x") else float(pos[0])
        py = pos.y if hasattr(pos, "y") else float(pos[1])
        pz = pos.z if hasattr(pos, "z") else float(pos[2])
        off = _node_sphere_diameter_mm(node) * 0.5 + get_pref_label_offset_mm()  # 半径 + ユーザー設定オフセット
        if _front_face and getattr(_front_face, "Mesh", None):
            normal_local = _mesh_outward_normal(_front_face.Mesh)
            normal = _local_normal_to_global(_front_face, normal_local)
            pos_vec = (px + normal[0] * off, py + normal[1] * off, pz + normal[2] * off)
        else:
            pos_vec = (px, py, pz)
        lbl = _create_number_label(doc, "RA_NodeLabel", num, pos_vec, size_mm=size_mm, unique_index=idx)
        if lbl:
            group.addObject(lbl)
            if FreeCAD.GuiUp and hasattr(lbl, "ViewObject"):
                lbl.ViewObject.Visibility = True
    # #region agent log
    _dbg_log("core.py:_update_node_number_labels", "after loop", {"group_count": len(group.Group) if group and group.Group else 0}, "H3")
    # #endregion
    if not group.Group and face_groups:
        FreeCAD.Console.PrintWarning("ノード番号ラベルを1つも作成できませんでした。フォントパスを確認してください。\n")
    doc.recompute()


def run_show_surface_numbers(show, label_scale_percent=None):
    """サーフェース番号の表示を ON/OFF する。
    label_scale_percent: ラベル大きさの%。None のとき表示パラメータ設定から読み取る。"""
    if label_scale_percent is None:
        label_scale_percent = get_pref_label_scale_percent()
    doc = FreeCAD.ActiveDocument
    if not doc or not FreeCAD.GuiUp:
        return
    face_groups = freecad_utils.get_face_groups(doc)
    if not face_groups:
        FreeCAD.Console.PrintWarning("FaceGroup がありません。先にモデルを準備してください。\n")
        return
    group = doc.getObject(_RA_LABELS_GROUP_SURF)
    if not group:
        _update_surface_number_labels(doc, face_groups, label_scale_percent)
        group = doc.getObject(_RA_LABELS_GROUP_SURF)
    else:
        _update_surface_number_labels(doc, face_groups, label_scale_percent)
    if group:
        group.ViewObject.Visibility = bool(show)
    # #region agent log
    _dbg_log("core.py:run_show_surface_numbers", "before updateGui", {"show": show, "group_exists": group is not None, "group_visibility": getattr(group.ViewObject, "Visibility", None) if group and hasattr(group, "ViewObject") else None, "group_count": len(group.Group) if group and group.Group else 0}, "H3")
    # #endregion
    doc.recompute()
    if FreeCAD.GuiUp and group and show:
        try:
            FreeCADGui.updateGui()
        except Exception:
            pass


def run_show_node_numbers(show, label_scale_percent=None):
    """ノード番号の表示を ON/OFF する。
    label_scale_percent: ラベル大きさの%。None のとき表示パラメータ設定から読み取る。"""
    if label_scale_percent is None:
        label_scale_percent = get_pref_label_scale_percent()
    doc = FreeCAD.ActiveDocument
    if not doc or not FreeCAD.GuiUp:
        return
    face_groups = freecad_utils.get_face_groups(doc)
    if not face_groups:
        FreeCAD.Console.PrintWarning("FaceGroup がありません。先にモデルを準備してください。\n")
        return
    group = doc.getObject(_RA_LABELS_GROUP_NODE)
    if not group:
        _update_node_number_labels(doc, face_groups, label_scale_percent)
        group = doc.getObject(_RA_LABELS_GROUP_NODE)
    else:
        _update_node_number_labels(doc, face_groups, label_scale_percent)
    if group:
        group.ViewObject.Visibility = bool(show)
    doc.recompute()
    if FreeCAD.GuiUp and group and show:
        try:
            FreeCADGui.updateGui()
        except Exception:
            pass


def _get_face_group_containing(doc, obj):
    """obj が属する FaceGroup を返す。InList をたどって親が FaceGroup ならそれを返す。見つからなければ None。"""
    if not doc or not obj:
        return None
    seen = set()
    stack = list(getattr(obj, "InList", []) or [])
    while stack:
        parent = stack.pop()
        if id(parent) in seen:
            continue
        seen.add(id(parent))
        name = getattr(parent, "Name", "") or ""
        if name.startswith("FaceGroup_"):
            return parent
        stack.extend(getattr(parent, "InList", []) or [])
    for o in doc.Objects:
        if not getattr(o, "Name", "").startswith("FaceGroup_"):
            continue
        if not getattr(o, "Group", None):
            continue
        for child in _face_group_members(o):
            if child is obj:
                return o
    return None


def get_surface_and_node_for_object(doc, obj):
    """
    オブジェクトが面（FaceGroup/メッシュ）またはノードの場合、
    (サーフェース番号 or None, ノード番号 or None) を返す。該当しなければ (None, None)。
    親が FaceGroup の場合はその子としても判定する。
    """
    if not doc or not obj:
        return (None, None)
    name = getattr(obj, "Name", "") or ""
    # FaceGroup
    if name.startswith("FaceGroup_"):
        surf = getattr(obj, "SurfaceNumber", None)
        return (surf, None)
    # Node_
    if name.startswith("Node_"):
        node_num = getattr(obj, "NodeNumber", None)
        parent = _get_face_group_containing(doc, obj)
        surf = getattr(parent, "SurfaceNumber", None) if parent else None
        return (surf, node_num)
    # メッシュ Face_*_front / Face_*_back（分割面は自身の SurfaceNumber を持つ）
    if ("_front" in name or "_back" in name) and name.startswith("Face_"):
        obj_surf = getattr(obj, "SurfaceNumber", None)
        parent = _get_face_group_containing(doc, obj)
        # オブジェクト自身の面番号を優先（分割後の新しい番号）。無い場合のみ親の番号を使う
        if obj_surf is not None:
            return (obj_surf, None)
        if parent:
            surf = getattr(parent, "SurfaceNumber", None)
            return (surf, None)
        return (None, None)
    # 上記に該当しないが、親が FaceGroup の子（例: コンパウンドの子など）
    fg = _get_face_group_containing(doc, obj)
    if fg:
        # オブジェクト自身に SurfaceNumber があれば優先（分割面）
        surf = getattr(obj, "SurfaceNumber", None)
        if surf is None:
            surf = getattr(fg, "SurfaceNumber", None)
        node_num = getattr(obj, "NodeNumber", None) if name.startswith("Node_") else None
        return (surf, node_num)
    return (None, None)


def get_hover_label_position_for_object(obj):
    """ホバーラベルを表示する位置 [mm] を (x,y,z) で返す。取れなければ None。"""
    if not obj:
        return None
    name = getattr(obj, "Name", "") or ""
    if name.startswith("Node_") and hasattr(obj, "Shape") and obj.Shape:
        pos = _node_position(obj)
        if pos is not None:
            return (pos.x, pos.y, pos.z)
    if hasattr(obj, "Mesh") and obj.Mesh:
        c = obj.Mesh.BoundBox.Center
        pl = _get_global_placement(obj)
        if pl:
            v = pl.multVec(FreeCAD.Vector(c[0], c[1], c[2]))
            return (v.x, v.y, v.z)
        return (c[0], c[1], c[2])
    if name.startswith("FaceGroup_"):
        for child in _face_group_members(obj):
            if getattr(child, "Name", "").startswith("Node_"):
                pos = _node_position(child)
                if pos is not None:
                    return (pos.x, pos.y, pos.z)
            if hasattr(child, "Mesh") and child.Mesh:
                c = child.Mesh.BoundBox.Center
                pl = _get_global_placement(child)
                if pl:
                    v = pl.multVec(FreeCAD.Vector(c[0], c[1], c[2]))
                    return (v.x, v.y, v.z)
                return (c[0], c[1], c[2])
    return None


def resolve_hover_object(doc, obj):
    """
    getObjectInfo で得た obj から、ホバー表示用の (位置オブジェクト, 面番号, ノード番号) を返す。
    位置オブジェクトは get_hover_label_position_for_object に渡す用。取れなければ (None, None, None)。
    """
    if not doc or not obj:
        return (None, None, None)
    surf, node = get_surface_and_node_for_object(doc, obj)
    if surf is None and node is None:
        return (None, None, None)
    pos_mm = get_hover_label_position_for_object(obj)
    if pos_mm is not None:
        return (obj, surf, node)
    fg = _get_face_group_containing(doc, obj)
    if fg:
        for child in _face_group_members(fg):
            if get_hover_label_position_for_object(child) is not None:
                return (child, surf, node)
    return (None, None, None)


# ホバーラベル: 画面上表示（Draft make_text screen=True）のときのフォントサイズ [mm]。大きめで読みやすく。
_RA_HOVER_SCREEN_FONT_SIZE_MM = 24.0


def _create_hover_screen_label(doc, text, position_3d_mm, font_size_mm=24.0):
    """Draft.make_text(..., screen=True) で画面上に常に正面を向くラベルを作成。白抜き表示。"""
    try:
        import Draft
        make_text = getattr(Draft, "make_text", None)
        if not make_text:
            return None
        pos = FreeCAD.Vector(position_3d_mm[0], position_3d_mm[1], position_3d_mm[2])
        txt = make_text(str(text), pos, screen=True)
        if not txt or not hasattr(txt, "ViewObject"):
            return None
        vp = txt.ViewObject
        for prop in ("FontSize", "TextSize", "FontSizeMultiplier"):
            if hasattr(vp, prop):
                setattr(vp, prop, font_size_mm)
                break
        # 白抜き: 文字色を白に。LineColor で縁取りがある場合は黒にすると読みやすい
        if hasattr(vp, "TextColor"):
            vp.TextColor = (1.0, 1.0, 1.0)
        if hasattr(vp, "LineColor"):
            vp.LineColor = (0.0, 0.0, 0.0)
        return txt
    except Exception:
        return None


def update_hover_label(doc, text, position_mm, size_mm=10.0):
    """ホバー用の単一ラベルを表示・更新する。画面上表示（Draft screen=True）で大きめの文字。"""
    if not doc or not FreeCAD.GuiUp:
        return
    group = doc.getObject(_RA_HOVER_LABEL_GROUP)
    if not group:
        group = doc.addObject("App::DocumentObjectGroup", _RA_HOVER_LABEL_GROUP)
        group.Label = "ホバー番号"
    for o in list(group.Group):
        group.removeObject(o)
        try:
            doc.removeObject(o.Name)
        except Exception:
            pass
    if not text or position_mm is None:
        if hasattr(group, "ViewObject"):
            group.ViewObject.Visibility = False
        return
    font_size = max(_RA_HOVER_SCREEN_FONT_SIZE_MM, float(size_mm))
    lbl = _create_hover_screen_label(doc, str(text), position_mm, font_size_mm=font_size)
    if not lbl:
        lbl = _create_number_label(doc, "RA_HoverLabel", str(text), position_mm, size_mm=max(20.0, size_mm), unique_index=0)
    if lbl:
        group.addObject(lbl)
        if hasattr(group, "ViewObject"):
            group.ViewObject.Visibility = True
        if hasattr(lbl, "ViewObject"):
            lbl.ViewObject.Visibility = True
    try:
        doc.recompute()
    except Exception:
        pass
    if lbl and FreeCAD.GuiUp:
        try:
            FreeCADGui.updateGui()
        except Exception:
            pass


def clear_hover_label(doc):
    """ホバーラベルを非表示にする。"""
    if not doc:
        return
    group = doc.getObject(_RA_HOVER_LABEL_GROUP)
    if group and hasattr(group, "ViewObject"):
        group.ViewObject.Visibility = False


def run_set_node_point_sizes(mode, percent):
    """
    ノードの表示サイズを一括設定する。
    mode: "face_percent" = 面の大きさに対する%, "global_percent" = 全体の大きさに対する%
    percent: 1～500 のスケール。100%で「面の対角線の8%」または「全体の対角線の2%」を球半径にする。
    """
    doc = FreeCAD.ActiveDocument
    if not doc or not FreeCAD.GuiUp:
        return
    face_groups = freecad_utils.get_face_groups(doc)
    if not face_groups:
        FreeCAD.Console.PrintWarning("FaceGroup がありません。\n")
        return
    scale = max(0.01, min(5.0, float(percent) / 100.0))
    run_set_node_point_sizes._logged = False  # #region agent log (reset per Apply) # #endregion
    ref_diag = None
    if mode == "global_percent":
        bbox = None
        for g in face_groups:
            for obj in _face_group_members(g):
                if hasattr(obj, "Mesh") and obj.Mesh:
                    b = obj.Mesh.BoundBox
                    if bbox is None:
                        bbox = FreeCAD.BoundBox(b.XMin, b.YMin, b.ZMin, b.XMax, b.YMax, b.ZMax)
                    else:
                        bbox.add(b)
                if hasattr(obj, "Shape") and obj.Shape:
                    v = _node_position(obj)
                    if v is not None:
                        if bbox is None:
                            bbox = FreeCAD.BoundBox(v.x, v.y, v.z, v.x, v.y, v.z)
                        else:
                            bbox.add(v)
        if bbox:
            ref_diag = math.sqrt((bbox.XMax - bbox.XMin) ** 2 + (bbox.YMax - bbox.YMin) ** 2 + (bbox.ZMax - bbox.ZMin) ** 2)
        if ref_diag is None or ref_diag < 1e-6:
            ref_diag = 1.0
    # (front_face, node, diag) でループし、位置は常に面メッシュ中心から算出してずれを防ぐ
    node_triples = []
    for front_face, node in _iter_face_groups_front_and_node(face_groups):
        diag = 1.0
        if mode == "face_percent" and hasattr(front_face, "Mesh") and front_face.Mesh:
            b = front_face.Mesh.BoundBox
            diag = math.sqrt((b.XMax - b.XMin) ** 2 + (b.YMax - b.YMin) ** 2 + (b.ZMax - b.ZMin) ** 2)
        elif mode == "global_percent":
            diag = ref_diag or 1.0
        if diag < 1e-6:
            diag = 1.0
        node_triples.append((front_face, node, diag))
    if mode == "face_percent":
        ref_diag = max((d for _, _, d in node_triples), default=1.0)
    frac = get_pref_node_sphere_fraction_face() if mode == "face_percent" else get_pref_node_sphere_fraction_global()
    for front_face, node, diag in node_triples:
        # ノードの中心位置は変更しない。現在の位置を保持し、球の半径だけ更新する。
        # 親が複数段ある場合、直接の親だけの逆変換だと位置がずれて毎回飛んでいくため、
        # ノードのグローバル Placement と逆変換で正しい Base を算出する。
        center_global = _node_position(node)
        if center_global is None:
            continue
        if not hasattr(center_global, "x"):
            center_global = FreeCAD.Vector(float(center_global[0]), float(center_global[1]), float(center_global[2]))
        used_chain = False
        try:
            pl_global = _get_global_placement(node)
            pl_node = getattr(node, "Placement", None)
            if pl_global and pl_node:
                pl_node_inv = _placement_inverse(pl_node)
                parent_chain = pl_global.multiply(pl_node_inv)
                parent_chain_inv = _placement_inverse(parent_chain)
                center_local = parent_chain_inv.multVec(center_global)
                used_chain = True
                # #region agent log
                if not getattr(run_set_node_point_sizes, "_logged", False):
                    run_set_node_point_sizes._logged = True
                    _dbg_log("core.py:run_set_node_point_sizes", "node_place", {"nodeName": node.Name, "center_global": [round(center_global.x, 2), round(center_global.y, 2), round(center_global.z, 2)], "parent_chain_base": [round(parent_chain.Base.x, 2), round(parent_chain.Base.y, 2), round(parent_chain.Base.z, 2)], "center_local": [round(center_local.x, 2), round(center_local.y, 2), round(center_local.z, 2)]}, "H1")
                # #endregion
            else:
                center_local = center_global
        except Exception as e:
            center_local = center_global
            # #region agent log
            if not getattr(run_set_node_point_sizes, "_logged", False):
                run_set_node_point_sizes._logged = True
                _dbg_log("core.py:run_set_node_point_sizes", "node_place_except", {"nodeName": node.Name, "err": str(type(e).__name__), "center_global": [round(center_global.x, 2), round(center_global.y, 2), round(center_global.z, 2)]}, "H4")
            # #endregion
        radius_mm = diag * scale * frac
        radius_mm = max(get_pref_node_sphere_radius_min_mm(), min(get_pref_node_sphere_radius_max_mm(), radius_mm))
        try:
            node.Shape = Part.makeSphere(radius_mm)
            node.Placement.Base = center_local
            if FreeCAD.GuiUp and hasattr(node, "ViewObject") and hasattr(node.ViewObject, "ShapeColor"):
                node.ViewObject.ShapeColor = (1.0, 1.0, 0.0)  # 黄色
        except Exception:
            if hasattr(node, "ViewObject") and hasattr(node.ViewObject, "PointSize"):
                node.ViewObject.PointSize = max(1, min(50, int(round(radius_mm / get_pref_node_point_size_divisor()))))
    # 伝熱コンダクタンスの線を現在のノード位置で再描画（線がノード位置に追従するように）
    links_group = None
    base_obj = freecad_utils.get_base_object_from_face_groups(face_groups)
    if base_obj:
        links_group = doc.getObject(f"{base_obj.Label}_ConductanceLinks")
    if not links_group:
        for o in doc.Objects:
            if hasattr(o, "Group") and o.Name.endswith("_ConductanceLinks"):
                links_group = o
                break
    _update_conductance_link_shapes(doc, face_groups, links_group)
    doc.recompute()
    if FreeCAD.GuiUp:
        try:
            FreeCADGui.updateGui()
        except Exception:
            pass
    FreeCAD.Console.PrintMessage(f"ノードサイズを設定しました（{mode}, {percent}%）。\n")


# =========================================================
# THERMAL PROPERTY AND MATERIAL HANDLING
#
# Iteration and lookup helpers that expose face-mesh
# objects for bulk property assignment and for feeding
# into the conductance / radiation solvers.
# =========================================================

def _face_group_members(face_group):
    """FaceGroup の直下メンバーと、1段ネストしたグループ内メンバーを平坦に返す（表面/裏面が「面」グループ内にある場合に対応）。"""
    members = list(face_group.Group)
    for g in face_group.Group:
        if hasattr(g, "Group"):
            members.extend(g.Group)
    return members


def get_all_face_meshes_for_bulk_properties(doc):
    """輻射モデル内の全面（表面・裏面）メッシュを返す。一括プロパティ設定用。"""
    return get_face_meshes_for_bulk_properties(doc, face_groups=None)


def get_face_meshes_for_bulk_properties(doc, face_groups=None):
    """
    輻射モデル内の Face メッシュ（表面・裏面）を返す。一括プロパティ設定用。

    - face_groups が None のとき: ドキュメント内の全 FaceGroup を対象
    - face_groups が list のとき: 指定した FaceGroup のみを対象
    """
    if face_groups is None:
        face_groups = freecad_utils.get_face_groups(doc)
    if not face_groups:
        return []
    meshes = []
    for group in face_groups:
        for obj in _face_group_members(group):
            if obj.isDerivedFrom("Mesh::Feature") and "Face_" in obj.Name:
                meshes.append(obj)
    return meshes


def _iter_face_groups_front_and_node(face_groups):
    """各 FaceGroup から (front_mesh, node) を列挙。サブ分割 Face_*_sub_*_front / Node_*_sub_* も扱う。"""
    for group in face_groups:
        front_list = []
        node_by_sub = {}  # sub_index (None for main) -> node
        for obj in _face_group_members(group):
            if obj.Name.endswith("_front") and "Face_" in obj.Name:
                front_list.append(obj)
            if obj.Name.startswith("Node_"):
                if "_sub_" in obj.Name:
                    try:
                        # Node_i_sub_k
                        rest = obj.Name.replace("Node_", "", 1).split("_sub_")
                        if len(rest) == 2:
                            k = int(rest[1])
                            node_by_sub[k] = obj
                    except (ValueError, IndexError):
                        pass
                else:
                    node_by_sub[None] = obj
        has_subs = any("_sub_" in f.Name for f in front_list)
        if has_subs:
            for front in front_list:
                if "_sub_" not in front.Name:
                    continue
                try:
                    # Face_i_sub_k_front
                    rest = front.Name.replace("Face_", "", 1).split("_sub_")[1]
                    k = int(rest.replace("_front", ""))
                    node = node_by_sub.get(k) or node_by_sub.get(None)
                    if node:
                        yield (front, node)
                except (ValueError, IndexError, AttributeError):
                    pass
        else:
            node = node_by_sub.get(None)
            if not node:
                continue
            for f in front_list:
                if "_sub_" in f.Name:
                    continue
                yield (f, node)


def _iter_radiation_patch_meshes(face_groups):
    """
    ActiveSide に応じて輻射パッチ用の (mesh_obj, node) を列挙する。
    - 表面: Face_*_front のみ（外側法線）
    - 裏面: Face_*_back のみ（内側法線）
    - 両面: front と back を別パッチとして両方出す。
    """
    for group in face_groups:
        members = _face_group_members(group)
        front_list = []
        node_by_sub = {}
        back_by_front_name = {}
        for obj in members:
            if obj.Name.endswith("_front") and "Face_" in obj.Name:
                front_list.append(obj)
            elif obj.Name.endswith("_back") and "Face_" in obj.Name:
                front_name = obj.Name.replace("_back", "_front")
                back_by_front_name[front_name] = obj
            if obj.Name.startswith("Node_"):
                if "_sub_" in obj.Name:
                    try:
                        rest = obj.Name.replace("Node_", "", 1).split("_sub_")
                        if len(rest) == 2:
                            k = int(rest[1])
                            node_by_sub[k] = obj
                    except (ValueError, IndexError):
                        pass
                else:
                    node_by_sub[None] = obj
        has_subs = any("_sub_" in f.Name for f in front_list)
        active_side = getattr(front_list[0], "ActiveSide", "両面") if front_list else "両面"
        if has_subs:
            for front in front_list:
                if "_sub_" not in front.Name:
                    continue
                try:
                    rest = front.Name.replace("Face_", "", 1).split("_sub_")[1]
                    k = int(rest.replace("_front", ""))
                    node = node_by_sub.get(k) or node_by_sub.get(None)
                except (ValueError, IndexError, AttributeError):
                    node = None
                if not node:
                    continue
                back = back_by_front_name.get(front.Name)
                if active_side == "表面":
                    yield (front, node)
                elif active_side == "裏面":
                    if back:
                        yield (back, node)
                else:
                    yield (front, node)
                    if back:
                        yield (back, node)
        else:
            node = node_by_sub.get(None)
            if not node:
                continue
            for front in front_list:
                if "_sub_" in front.Name:
                    continue
                back = back_by_front_name.get(front.Name)
                if active_side == "表面":
                    yield (front, node)
                elif active_side == "裏面":
                    if back:
                        yield (back, node)
                else:
                    yield (front, node)
                    if back:
                        yield (back, node)


# =========================================================
# THERMAL NETWORK CALCULATION
#
# Three sub-groups, executed in order by the user:
#
#   1. THERMAL MASS
#      calculate_thermal_mass()
#      Computes Cp × mass for each node from mesh geometry
#      and material properties.
#
#   2. CONDUCTION CONDUCTANCE
#      calculate_conductance(), add_manual_conductance()
#      Finds shared edges between adjacent face-mesh patches
#      and computes kA/L conduction links.
#      export_nodes_and_conductance_dat() writes a .dat file.
#
#   3. RADIATION CONDUCTANCE  (Monte Carlo ray tracing)
#      calculate_radiation_conductance()
#      Builds surface patches, shoots random rays to estimate
#      view factors, then writes radiation links to the doc.
#      export_radiation_dat() writes a .dat file.
# =========================================================

def calculate_thermal_mass():
    doc = FreeCAD.ActiveDocument
    if not doc:
        return
    doc.recompute()
    face_groups = freecad_utils.get_face_groups(doc)
    if not face_groups:
        FreeCAD.Console.PrintError("'FaceGroup' が見つかりません。先にモデルを準備してください。\n")
        return
    FreeCAD.Console.PrintMessage("熱容量の計算を開始します...\n")
    node_capacities = []
    for front_face, node in _iter_face_groups_front_and_node(face_groups):
        if not getattr(front_face, "Mesh", None):
            continue
        area_m2 = front_face.Mesh.Area / 1000000.0
        thickness_m, density, specific_heat, _ = _get_face_thermal_values(front_face)
        cap = calculation.calc_thermal_capacity(
            area_m2,
            thickness_m,
            density,
            specific_heat,
        )
        node_number = getattr(node, "NodeNumber", id(node) % 1000000)
        node_capacities.append((node, node_number, cap))
    capacity_by_node_number = {}
    for node, node_number, cap in node_capacities:
        capacity_by_node_number[node_number] = capacity_by_node_number.get(node_number, 0.0) + cap
    for node, node_number, _ in node_capacities:
        if not hasattr(node, "ThermalCapacity"):
            node.addProperty("App::PropertyFloat", "ThermalCapacity", "Thermal", "熱容量 [J/K]")
        node.ThermalCapacity = capacity_by_node_number[node_number]
        if not hasattr(node, "HeatSource"):
            node.addProperty("App::PropertyFloat", "HeatSource", "Thermal", "発熱量 [W]")
            node.HeatSource = 0.0
    FreeCAD.Console.PrintMessage("熱容量の計算とノードへの設定が完了しました。\n")
    doc.recompute()

def _get_shared_edges_two_faces(face1, face2):
    """
    2つの面が共有するエッジのリストを返す。
    common() は接するだけの面では空になり得るため、両面のエッジを比較して同一幾何のものを返す。
    """
    shared = []
    for e1 in face1.Edges:
        for e2 in face2.Edges:
            if e1.isSame(e2):
                shared.append(e1)
                break
            v1 = e1.Vertexes
            v2 = e2.Vertexes
            if len(v1) != 2 or len(v2) != 2:
                continue
            d00 = v1[0].Point.distanceToPoint(v2[0].Point)
            d11 = v1[1].Point.distanceToPoint(v2[1].Point)
            d01 = v1[0].Point.distanceToPoint(v2[1].Point)
            d10 = v1[1].Point.distanceToPoint(v2[0].Point)
            if (d00 < 1e-9 and d11 < 1e-9) or (d01 < 1e-9 and d10 < 1e-9):
                shared.append(e1)
                break
    return shared


def _edges_to_global(edges, placement):
    """
    ローカル座標のエッジ列を、placement で変換したグローバル座標のエッジ列に変換する。
    ノード位置（グローバル）との距離判定に使う。
    """
    if not placement or not edges:
        return list(edges)
    out = []
    for e in edges:
        vts = e.Vertexes
        if len(vts) != 2:
            continue
        a = placement.multVec(FreeCAD.Vector(vts[0].Point))
        b = placement.multVec(FreeCAD.Vector(vts[1].Point))
        try:
            seg = Part.LineSegment(a, b).toShape()
            if seg.Edges:
                out.append(seg.Edges[0])
        except Exception:
            pass
    return out


def _get_all_nodes_with_positions(face_group):
    """
    FaceGroup に属する全ノードを (node_obj, 世界座標Vector) のリストで返す。
    分割面のサブノードも含む。
    """
    out = []
    for o in _face_group_members(face_group):
        n = getattr(o, "Name", "")
        if not n.startswith("Node_"):
            continue
        pos = _node_position(o)
        if pos is not None:
            out.append((o, pos))
    return out


def _distance_and_param_to_edge(point, edge):
    """
    点（FreeCAD.Vector）からエッジ（線分）への最短距離と、エッジ上のパラメータ t in [0,1] を返す。
    戻り値: (distance_mm, t_param) または (float('inf'), 0.5)。
    """
    try:
        vts = edge.Vertexes
        if len(vts) != 2:
            return (float("inf"), 0.5)
        a = FreeCAD.Vector(vts[0].Point)
        b = FreeCAD.Vector(vts[1].Point)
        ab = b - a
        length_sq = ab.x * ab.x + ab.y * ab.y + ab.z * ab.z
        if length_sq < 1e-18:
            d = point.distanceToPoint(a)
            return (d, 0.0)
        ap = point - a
        t = (ap.x * ab.x + ap.y * ab.y + ap.z * ab.z) / length_sq
        t = max(0.0, min(1.0, t))
        closest = FreeCAD.Vector(a.x + t * ab.x, a.y + t * ab.y, a.z + t * ab.z)
        d = point.distanceToPoint(closest)
        return (d, t)
    except Exception:
        return (float("inf"), 0.5)


def _param_along_edges(point, edges):
    """
    点が複数エッジからなる「稜線」のどこに相当するかを [0,1] のパラメータで返す。
    各エッジは線分。全エッジの長さで重み付けてパラメータを計算する。
    戻り値: (distance_mm, global_param) 。distance は稜線までの最短距離。
    """
    if not edges:
        return (float("inf"), 0.5)
    total_length = sum(e.Length for e in edges)
    if total_length < 1e-9:
        return (float("inf"), 0.5)
    best_dist = float("inf")
    best_param = 0.5
    cum = 0.0
    for e in edges:
        d, t = _distance_and_param_to_edge(point, e)
        local_param = cum + t * e.Length
        global_param = local_param / total_length
        if d < best_dist:
            best_dist = d
            best_param = min(1.0, max(0.0, global_param))
        cum += e.Length
    return (best_dist, best_param)


def _get_nodes_near_edges(face_group, edges, tolerance_mm=5.0):
    """
    共有エッジから tolerance_mm 以内にあるノードを、(node_obj, position, param_along_edge) のリストで返す。
    param_along_edge は [0,1] で稜線上の順序付けに使う。
    """
    total_length = sum(e.Length for e in edges)
    if total_length < 1e-9:
        return []
    nodes_with_pos = _get_all_nodes_with_positions(face_group)
    out = []
    for node_obj, pos in nodes_with_pos:
        dist, param = _param_along_edges(pos, edges)
        if dist <= tolerance_mm:
            out.append((node_obj, pos, param))
    return out


def _pair_nodes_by_nearest(nodes_a, nodes_b):
    """
    2つのリスト nodes_a, nodes_b はそれぞれ [(node_obj, position, param), ...]。
    パラメータ順で対応付ける（稜線に沿った順序で 1 対 1）。
    長さが異なる場合は短い方の要素数だけペアを作り、パラメータでソートして先頭同士を対応させる。
    戻り値: [(node_a, node_b), ...]
    """
    if not nodes_a or not nodes_b:
        return []
    sa = sorted(nodes_a, key=lambda x: x[2])
    sb = sorted(nodes_b, key=lambda x: x[2])
    n = min(len(sa), len(sb))
    return [(sa[i][0], sb[i][0]) for i in range(n)]


def _iter_adjacent_sub_pairs_in_face_group(face_group):
    """
    1つの FaceGroup 内で、グリッド上隣接するサブ対 (k1, k2) を列挙する。
    サブが無い場合は何も返さない。face_index / model_name は group の SurfaceNumber / ModelName から取得。
    """
    face_index = getattr(face_group, "SurfaceNumber", None)
    if face_index is None:
        try:
            n = face_group.Name.replace("FaceGroup_", "").strip()
            face_index = int(n.split("_")[-1]) if "_" in n else int(n)
        except (ValueError, AttributeError):
            return
    model_name = getattr(face_group, "ModelName", None) or ""
    san = _name_sanitize(model_name) if model_name else ""
    prefix_face_new = f"Face_{san}_{face_index}_sub_" if san else ""
    prefix_face_old = f"Face_{face_index}_sub_"
    prefix_node_new = f"Node_{san}_{face_index}_sub_" if san else ""
    prefix_node_old = f"Node_{face_index}_sub_"
    sub_fronts = []
    sub_nodes = []
    for o in face_group.Group:
        nm = getattr(o, "Name", "")
        if nm.endswith("_front") and ("_sub_" in nm):
            for pre in (prefix_face_new, prefix_face_old):
                if pre and nm.startswith(pre):
                    try:
                        k = int(nm[len(pre):].replace("_front", ""))
                        sub_fronts.append((k, o))
                    except ValueError:
                        pass
                    break
        if nm.startswith("Node_") and "_sub_" in nm:
            for pre in (prefix_node_new, prefix_node_old):
                if pre and nm.startswith(pre):
                    try:
                        k = int(nm[len(pre):])
                        sub_nodes.append((k, o))
                    except ValueError:
                        pass
                    break
    if not sub_fronts or not sub_nodes:
        return
    sub_fronts.sort(key=lambda x: x[0])
    sub_nodes.sort(key=lambda x: x[0])
    ks = sorted(set(f[0] for f in sub_fronts) & set(n[0] for n in sub_nodes))
    n_total = len(ks)
    if n_total == 0:
        return
    # nu * nv = n_total の因数のうち、nu <= nv で nu を最大化（できるだけ正方形に近い）
    nu, nv = 1, n_total
    for u in range(1, int(n_total ** 0.5) + 1):
        if n_total % u == 0:
            nu, nv = u, n_total // u
    k_to_front = dict(sub_fronts)
    k_to_node = dict(sub_nodes)
    for k in ks:
        ci, cj = k // nv, k % nv
        if cj < nv - 1 and (k + 1) in k_to_front and (k + 1) in k_to_node:
            yield (k, k + 1)
        if ci < nu - 1 and (k + nv) in k_to_front and (k + nv) in k_to_node:
            yield (k, k + nv)


def _find_node_by_number(doc, face_groups, node_number):
    """NodeNumber が一致するノードオブジェクトを返す。見つからなければ None。"""
    for g in face_groups or []:
        for obj in _face_group_members(g):
            if obj.Name.startswith("Node_") and getattr(obj, "NodeNumber", None) == node_number:
                return obj
    return None


def add_manual_conductance(node1_obj, node2_obj, conductance_w_per_k):
    """2つのノード間に手動で伝熱コンダクタンスリンクを追加する。"""
    doc = FreeCAD.ActiveDocument
    if not doc:
        raise RuntimeError("アクティブなドキュメントがありません。")
    face_groups = freecad_utils.get_face_groups(doc)
    if not face_groups:
        raise RuntimeError("FaceGroup が見つかりません。先にモデルを準備してください。")
    base_obj = freecad_utils.get_base_object_from_face_groups(face_groups)
    if not base_obj:
        raise RuntimeError("元の形状オブジェクトが見つかりません。")
    n1 = getattr(node1_obj, "NodeNumber", None)
    n2 = getattr(node2_obj, "NodeNumber", None)
    if n1 is None or n2 is None:
        raise RuntimeError("NodeNumber を持たないノードが選択されています。")
    if n1 == n2:
        raise RuntimeError("同一ノード間にはコンダクタンスを追加できません。")
    links_group_name = f"{base_obj.Label}_ConductanceLinks"
    links_group = doc.getObject(links_group_name)
    if not links_group:
        links_group = doc.addObject("App::DocumentObjectGroup", links_group_name)
        if not hasattr(links_group, "ModelName"):
            links_group.addProperty("App::PropertyString", "ModelName", "Internal")
        links_group.ModelName = getattr(face_groups[0], "ModelName", None) or _sanitize_model_name(getattr(base_obj, "Label", "Model"))
        parent_group = None
        if hasattr(face_groups[0], "InList") and face_groups[0].InList:
            for cand in face_groups[0].InList:
                if hasattr(cand, "Group") and face_groups[0] in cand.Group:
                    parent_group = cand
                    break
        if parent_group:
            parent_group.addObject(links_group)
    # 既存の最大 ConductanceNumber を取得
    max_seq = 0
    for link in getattr(links_group, "Group", []) or []:
        seq = getattr(link, "ConductanceNumber", 0)
        if isinstance(seq, int) and seq > max_seq:
            max_seq = seq
    conductance_seq = max_seq + 1
    p1 = _node_position(node1_obj)
    p2 = _node_position(node2_obj)
    if p1 is None or p2 is None:
        raise RuntimeError("ノード位置を取得できませんでした。")
    line_shape = Part.LineSegment(p1, p2).toShape()
    link_name = f"Link_Node{n1}_Node{n2}"
    link_obj = doc.addObject("Part::Feature", link_name)
    link_obj.Shape = line_shape
    if not hasattr(link_obj, "Conductance"):
        link_obj.addProperty("App::PropertyFloat", "Conductance", "Thermal", "伝熱コンダクタンス [W/K]")
    link_obj.Conductance = float(conductance_w_per_k)
    if not hasattr(link_obj, "FormulaString"):
        link_obj.addProperty("App::PropertyString", "FormulaString", "Thermal", "計算式")
    link_obj.FormulaString = f"{float(conductance_w_per_k):.6g}"
    if not hasattr(link_obj, "NodeNumber1"):
        link_obj.addProperty("App::PropertyInteger", "NodeNumber1", "Thermal", "ノード番号1")
    if not hasattr(link_obj, "NodeNumber2"):
        link_obj.addProperty("App::PropertyInteger", "NodeNumber2", "Thermal", "ノード番号2")
    link_obj.NodeNumber1 = int(n1)
    link_obj.NodeNumber2 = int(n2)
    if not hasattr(link_obj, "ConductanceNumber"):
        link_obj.addProperty("App::PropertyInteger", "ConductanceNumber", "Thermal", "コンダクタンス番号")
    link_obj.ConductanceNumber = conductance_seq
    model_name = getattr(links_group, "ModelName", None) or _sanitize_model_name(getattr(base_obj, "Label", "Model"))
    link_obj.Label = f"{model_name}.{conductance_seq}"
    links_group.addObject(link_obj)
    _apply_conduction_link_view(link_obj)
    doc.recompute()
    FreeCAD.Console.PrintMessage(f"手動コンダクタンスを追加しました: Node#{n1} <-> Node#{n2}, G = {float(conductance_w_per_k):.6g} W/K (導体#{conductance_seq})\n")


def _update_conductance_link_shapes(doc, face_groups, links_group):
    """伝熱コンダクタンスの線形状を、現在のノード位置で再描画する。"""
    # #region agent log
    _dbg_log("core.py:_update_conductance_link_shapes", "entry", {"links_group": links_group.Name if links_group else None, "n_links": len(getattr(links_group, "Group", [])) if links_group else 0, "n_face_groups": len(face_groups) if face_groups else 0}, "H2")
    # #endregion
    if not links_group or not getattr(links_group, "Group", None) or not face_groups:
        return
    updated = 0
    for link in links_group.Group:
        if not hasattr(link, "NodeNumber1") or not hasattr(link, "NodeNumber2"):
            continue
        n1 = getattr(link, "NodeNumber1", None)
        n2 = getattr(link, "NodeNumber2", None)
        if n1 is None or n2 is None:
            continue
        node1 = _find_node_by_number(doc, face_groups, n1)
        node2 = _find_node_by_number(doc, face_groups, n2)
        if not node1 or not node2:
            continue
        p1 = _node_position(node1)
        p2 = _node_position(node2)
        if p1 is None or p2 is None:
            continue
        try:
            link.Shape = Part.LineSegment(p1, p2).toShape()
            updated += 1
            # #region agent log
            if updated == 1:
                _dbg_log("core.py:_update_conductance_link_shapes", "first link updated", {"p1": [round(p1.x, 2), round(p1.y, 2), round(p1.z, 2)], "p2": [round(p2.x, 2), round(p2.y, 2), round(p2.z, 2)], "n1": n1, "n2": n2}, "H2")
            # #endregion
        except Exception:
            pass
    # #region agent log
    _dbg_log("core.py:_update_conductance_link_shapes", "exit", {"updated": updated}, "H2")
    # #endregion


def _get_representative_face_and_node_for_conductance(doc, face_group):
    """
    伝熱コンダクタンス用に、FaceGroup の代表メッシュオブジェクトとノードを1つ返す。
    戻り値: (face_mesh_obj, node_obj) または (None, None)
    """
    if not face_group or not hasattr(face_group, "Group"):
        return (None, None)
    face_obj = None
    node_obj = None
    for o in _face_group_members(face_group):
        n = getattr(o, "Name", "")
        if not n:
            continue
        if o.isDerivedFrom("Mesh::Feature") and "_front" in n and "Face_" in n and "_sub_" not in n:
            face_obj = o
            if node_obj:
                break
        elif o.isDerivedFrom("Mesh::Feature") and "_sub_" in n and n.endswith("_front"):
            if face_obj is None:
                face_obj = o
            if node_obj:
                break
        if n.startswith("Node_") and "_sub_" not in n:
            node_obj = o
            if face_obj:
                break
        if n.startswith("Node_") and "_sub_" in n:
            if node_obj is None:
                node_obj = o
            if face_obj:
                break
    return (face_obj, node_obj)


def calculate_conductance():
    doc = FreeCAD.ActiveDocument
    if not doc:
        return
    face_groups = freecad_utils.get_face_groups(doc)
    if not face_groups:
        FreeCAD.Console.PrintError("FaceGroupが見つかりません。\n")
        return

    # BaseObject ごとに FaceGroup をまとめる
    base_to_groups = {}
    for fg in face_groups:
        base = getattr(fg, "BaseObject", None)
        if base is None:
            continue
        base_to_groups.setdefault(base, []).append(fg)

    if not base_to_groups:
        FreeCAD.Console.PrintError("FaceGroup に対応する元の形状オブジェクトが見つかりません。\n")
        return

    FreeCAD.Console.PrintMessage("伝熱コンダクタンスの計算を開始します...\n")

    # 各 BaseObject ごとにコンダクタンスを計算
    for base_obj, groups_for_base in base_to_groups.items():
        if not base_obj:
            continue

        model_name = getattr(groups_for_base[0], "ModelName", None) or _sanitize_model_name(
            getattr(base_obj, "Label", "Model")
        )
        shape = base_obj.Shape
        faces = shape.Faces
        links_group_name = f"{base_obj.Label}_ConductanceLinks"

        # 既存リンクグループの削除
        old_links = doc.getObject(links_group_name)
        if old_links:
            for child in list(getattr(old_links, "Group", [])):
                try:
                    doc.removeObject(child.Name)
                except Exception:
                    pass
            doc.removeObject(links_group_name)

        # 新しいリンクグループの作成
        links_group = doc.addObject("App::DocumentObjectGroup", links_group_name)
        if not hasattr(links_group, "ModelName"):
            links_group.addProperty("App::PropertyString", "ModelName", "Internal")
        links_group.ModelName = model_name

        # 親グループにぶら下げる（あれば）
        parent_group = None
        if groups_for_base and hasattr(groups_for_base[0], "InList") and groups_for_base[0].InList:
            for cand in groups_for_base[0].InList:
                if hasattr(cand, "Group") and groups_for_base[0] in cand.Group:
                    parent_group = cand
                    break
        if parent_group:
            parent_group.addObject(links_group)

        num_faces = len(faces)
        conductance_seq = 1  # 1始まり（.inp および導体番号の慣例に合わせる）

        # 異なる面同士のコンダクタンス（共有エッジ付近のノードを稜線順でペアにし、各ペアに1本ずつリンクを作成）
        edge_node_tolerance_mm = get_pref_edge_node_tolerance_mm()
        base_placement_global = _get_global_placement(base_obj)
        for i, j in itertools.combinations(range(len(faces)), 2):
            face1 = faces[i]
            face2 = faces[j]
            common_edges = _get_shared_edges_two_faces(face1, face2)
            if not common_edges:
                continue
            # ノード位置はグローバル座標のため、共有エッジもグローバルに変換してから距離判定する
            common_edges_global = _edges_to_global(common_edges, base_placement_global)
            if not common_edges_global:
                common_edges_global = common_edges
            total_shared_length_m = sum(edge.Length for edge in common_edges) / 1000.0
            fg_i = _get_face_group_by_shape_index(doc, groups_for_base, base_obj, i)
            fg_j = _get_face_group_by_shape_index(doc, groups_for_base, base_obj, j)
            if not fg_i or not fg_j:
                continue
            face1_obj, _ = _get_representative_face_and_node_for_conductance(doc, fg_i)
            face2_obj, _ = _get_representative_face_and_node_for_conductance(doc, fg_j)
            if not face1_obj or not face2_obj:
                continue
            t1, _, _, k1 = _get_face_thermal_values(face1_obj)
            t2, _, _, k2 = _get_face_thermal_values(face2_obj)
            k_avg = (k1 + k2) / 2.0
            thickness_m = (t1 + t2) / 2.0

            nodes_i = _get_nodes_near_edges(fg_i, common_edges_global, edge_node_tolerance_mm)
            nodes_j = _get_nodes_near_edges(fg_j, common_edges_global, edge_node_tolerance_mm)
            pairs = _pair_nodes_by_nearest(nodes_i, nodes_j)

            if not pairs:
                # 稜線付近にノードが無い場合は従来どおり代表ノード1本だけ作成
                node1 = _get_representative_face_and_node_for_conductance(doc, fg_i)[1]
                node2 = _get_representative_face_and_node_for_conductance(doc, fg_j)[1]
                if not node1 or not node2:
                    continue
                pairs = [(node1, node2)]

            num_pairs = len(pairs)
            shared_length_per_link_m = total_shared_length_m / num_pairs

            for node1, node2 in pairs:
                n1 = getattr(node1, "NodeNumber", i)
                n2 = getattr(node2, "NodeNumber", j)
                if n1 == n2:
                    continue
                p1 = _node_position(node1)
                p2 = _node_position(node2)
                if p1 is None or p2 is None:
                    continue
                distance_m = p1.distanceToPoint(p2) / 1000.0
                conductance = calculation.calc_conductance(
                    k_avg,
                    thickness_m,
                    shared_length_per_link_m,
                    distance_m,
                )
                if conductance is None:
                    continue
                line_shape = Part.LineSegment(p1, p2).toShape()
                link_obj = doc.addObject("Part::Feature", f"Link_Node{n1}_Node{n2}_{conductance_seq}")
                link_obj.Shape = line_shape
                if not hasattr(link_obj, "Conductance"):
                    link_obj.addProperty(
                        "App::PropertyFloat", "Conductance", "Thermal", "伝熱コンダクタンス [W/K]"
                    )
                link_obj.Conductance = conductance
                if not hasattr(link_obj, "FormulaString"):
                    link_obj.addProperty(
                        "App::PropertyString", "FormulaString", "Thermal", "計算式"
                    )
                link_obj.FormulaString = (
                    f"({k_avg:.6g}*{shared_length_per_link_m:.6g}*{thickness_m:.6g}/{distance_m:.6g})"
                )
                if not hasattr(link_obj, "NodeNumber1"):
                    link_obj.addProperty(
                        "App::PropertyInteger", "NodeNumber1", "Thermal", "ノード番号1"
                    )
                if not hasattr(link_obj, "NodeNumber2"):
                    link_obj.addProperty(
                        "App::PropertyInteger", "NodeNumber2", "Thermal", "ノード番号2"
                    )
                link_obj.NodeNumber1 = n1
                link_obj.NodeNumber2 = n2
                if not hasattr(link_obj, "ConductanceNumber"):
                    link_obj.addProperty(
                        "App::PropertyInteger", "ConductanceNumber", "Thermal", "コンダクタンス番号"
                    )
                link_obj.ConductanceNumber = conductance_seq
                link_obj.Label = f"{model_name}.{conductance_seq}"
                links_group.addObject(link_obj)
                _apply_conduction_link_view(link_obj)
                conductance_seq += 1
                FreeCAD.Console.PrintMessage(
                    f"{base_obj.Label}: Node#{n1} <-> Node#{n2} : "
                    f"G = {conductance:.4f} W/K (導体#{link_obj.ConductanceNumber})\n"
                )

        # 分割された面内の隣接サブ同士のコンダクタンスを追加
        for fi in range(num_faces):
            group = _get_face_group_by_shape_index(doc, groups_for_base, base_obj, fi)
            if not group or not hasattr(group, "Group"):
                continue
            model_fi = getattr(group, "ModelName", None) or model_name
            for (k1, k2) in _iter_adjacent_sub_pairs_in_face_group(group):
                front1 = doc.getObject(
                    _face_sub_mesh_name(model_fi, fi, k1, "front")
                ) or doc.getObject(f"Face_{fi}_sub_{k1}_front")
                front2 = doc.getObject(
                    _face_sub_mesh_name(model_fi, fi, k2, "front")
                ) or doc.getObject(f"Face_{fi}_sub_{k2}_front")
                node1 = doc.getObject(
                    _node_sub_name(model_fi, fi, k1)
                ) or doc.getObject(f"Node_{fi}_sub_{k1}")
                node2 = doc.getObject(
                    _node_sub_name(model_fi, fi, k2)
                ) or doc.getObject(f"Node_{fi}_sub_{k2}")
                if not all([front1, front2, node1, node2]):
                    continue
                n1 = getattr(node1, "NodeNumber", fi * 1000 + k1)
                n2 = getattr(node2, "NodeNumber", fi * 1000 + k2)
                if n1 == n2:
                    continue
                area1_m2 = front1.Mesh.Area / 1000000.0
                area2_m2 = front2.Mesh.Area / 1000000.0
                shared_length_m = (float(area1_m2 ** 0.5) + float(area2_m2 ** 0.5)) / 2.0
                if shared_length_m <= 0:
                    continue
                p1 = _node_position(node1)
                p2 = _node_position(node2)
                if p1 is None or p2 is None:
                    continue
                distance_m = p1.distanceToPoint(p2) / 1000.0
                t1, _, _, k1f = _get_face_thermal_values(front1)
                t2, _, _, k2f = _get_face_thermal_values(front2)
                k_avg = (k1f + k2f) / 2.0
                thickness_m = (t1 + t2) / 2.0
                conductance = calculation.calc_conductance(
                    k_avg, thickness_m, shared_length_m, distance_m
                )
                if conductance is None:
                    continue
                line_shape = Part.LineSegment(p1, p2).toShape()
                link_name = f"Link_Node{fi}_sub{k1}_Node{fi}_sub{k2}"
                link_obj = doc.addObject("Part::Feature", link_name)
                link_obj.Shape = line_shape
                if not hasattr(link_obj, "Conductance"):
                    link_obj.addProperty(
                        "App::PropertyFloat", "Conductance", "Thermal", "伝熱コンダクタンス [W/K]"
                    )
                link_obj.Conductance = conductance
                if not hasattr(link_obj, "FormulaString"):
                    link_obj.addProperty(
                        "App::PropertyString", "FormulaString", "Thermal", "計算式"
                    )
                link_obj.FormulaString = (
                    f"({k_avg:.6g}*{shared_length_m:.6g}*{thickness_m:.6g}/{distance_m:.6g})"
                )
                if not hasattr(link_obj, "NodeNumber1"):
                    link_obj.addProperty(
                        "App::PropertyInteger", "NodeNumber1", "Thermal", "ノード番号1"
                    )
                if not hasattr(link_obj, "NodeNumber2"):
                    link_obj.addProperty(
                        "App::PropertyInteger", "NodeNumber2", "Thermal", "ノード番号2"
                    )
                link_obj.NodeNumber1 = n1
                link_obj.NodeNumber2 = n2
                if not hasattr(link_obj, "ConductanceNumber"):
                    link_obj.addProperty(
                        "App::PropertyInteger", "ConductanceNumber", "Thermal", "コンダクタンス番号"
                    )
                link_obj.ConductanceNumber = conductance_seq
                link_obj.Label = f"{model_fi}.{conductance_seq}"
                links_group.addObject(link_obj)
                _apply_conduction_link_view(link_obj)
                conductance_seq += 1
                FreeCAD.Console.PrintMessage(
                    f"{base_obj.Label}: Node_{fi}_sub_{k1}(#{n1}) <-> Node_{fi}_sub_{k2}(#{n2}) : "
                    f"G = {conductance:.4f} W/K (導体#{link_obj.ConductanceNumber})\n"
                )

    # すべてのリンクオブジェクトを作成し終えた後に一度だけ再計算
    try:
        doc.recompute()
    except Exception:
        pass
                
def export_nodes_and_conductance_dat(filepath):
    """
    ノードリストとコンダクタンスリストを .dat 形式でファイルに書き出す。
    列: ノードID, X, Y, Z, SurfaceId, ThermalCapacity / ConductanceId, Node1Id, Node2Id, Conductance
    """
    doc = FreeCAD.ActiveDocument
    if not doc:
        raise RuntimeError("アクティブなドキュメントがありません。")
    face_groups = freecad_utils.get_face_groups(doc)
    if not face_groups:
        raise RuntimeError("FaceGroup が見つかりません。先にモデルを準備してください。")
    base_obj = freecad_utils.get_base_object_from_face_groups(face_groups)
    links_group = None
    if base_obj:
        links_group = doc.getObject(f"{base_obj.Label}_ConductanceLinks")
    if not links_group:
        for o in doc.Objects:
            if hasattr(o, "Group") and o.Name.endswith("_ConductanceLinks"):
                links_group = o
                break
    sep = "\t"
    lines = []
    # ノードリスト: NodeId, X, Y, Z, SurfaceId, ThermalCapacity
    header_nodes = ["NodeId", "X_mm", "Y_mm", "Z_mm", "SurfaceId", "ThermalCapacity"]
    lines.append(sep.join(header_nodes))
    for group in face_groups:
        model_name = getattr(group, "ModelName", None) or _sanitize_model_name(getattr(base_obj, "Label", "Model"))
        for (front_face, node) in _iter_face_groups_front_and_node([group]):
            surface_number = getattr(front_face, "SurfaceNumber", getattr(group, "SurfaceNumber", 0))
            node_number = getattr(node, "NodeNumber", 0)
            node_id = f"{model_name}.{node_number}"
            surface_id = f"{model_name}.{surface_number}"
            pt = _node_position(node)
            if pt is None:
                continue
            x, y, z = pt.x, pt.y, pt.z
            thermal_cap = getattr(node, "ThermalCapacity", None)
            cap_str = f"{thermal_cap:.6f}" if thermal_cap is not None else ""
            lines.append(sep.join([
                node_id,
                f"{x:.6f}", f"{y:.6f}", f"{z:.6f}",
                surface_id,
                cap_str,
            ]))
    # コンダクタンスリスト: ConductanceId, Node1Id, Node2Id, Conductance_W_per_K
    lines.append("")
    header_cond = ["ConductanceId", "Node1Id", "Node2Id", "Conductance_W_per_K"]
    lines.append(sep.join(header_cond))
    if links_group and hasattr(links_group, "Group"):
        link_model_name = getattr(links_group, "ModelName", None) or (base_obj and _sanitize_model_name(getattr(base_obj, "Label", "Model"))) or "Model"
        for link in links_group.Group:
            if not hasattr(link, "Conductance"):
                continue
            cond_id = getattr(link, "Label", None) or (f"{link_model_name}.{getattr(link, 'ConductanceNumber', 0)}")
            n1 = getattr(link, "NodeNumber1", 0)
            n2 = getattr(link, "NodeNumber2", 0)
            node1_id = f"{link_model_name}.{n1}"
            node2_id = f"{link_model_name}.{n2}"
            g = link.Conductance
            lines.append(sep.join([cond_id, node1_id, node2_id, f"{g:.6f}"]))
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    FreeCAD.Console.PrintMessage(f"ノード・コンダクタンスリストをエクスポートしました: {filepath}\n")


# ---------------------------------------------------------------------------
# 輻射コンダクタンス（レイトレーシングでビューファクター計算）
# ---------------------------------------------------------------------------

def _ray_triangle_intersect(origin, direction, v0, v1, v2):
    """
    Möller–Trumbore: レイと三角形の交差。origin/direction は (x,y,z)。
    v0,v1,v2 は (x,y,z)。戻り値は交差距離 t (>0) または None。
    """
    eps = 1e-9
    e1 = (v1[0] - v0[0], v1[1] - v0[1], v1[2] - v0[2])
    e2 = (v2[0] - v0[0], v2[1] - v0[1], v2[2] - v0[2])
    h = (
        direction[1] * e2[2] - direction[2] * e2[1],
        direction[2] * e2[0] - direction[0] * e2[2],
        direction[0] * e2[1] - direction[1] * e2[0],
    )
    a = e1[0] * h[0] + e1[1] * h[1] + e1[2] * h[2]
    if -eps < a < eps:
        return None
    f = 1.0 / a
    s = (origin[0] - v0[0], origin[1] - v0[1], origin[2] - v0[2])
    u = f * (s[0] * h[0] + s[1] * h[1] + s[2] * h[2])
    if u < 0 or u > 1:
        return None
    q = (
        s[1] * e1[2] - s[2] * e1[1],
        s[2] * e1[0] - s[0] * e1[2],
        s[0] * e1[1] - s[1] * e1[0],
    )
    v = f * (direction[0] * q[0] + direction[1] * q[1] + direction[2] * q[2])
    if v < 0 or u + v > 1:
        return None
    t = f * (e2[0] * q[0] + e2[1] * q[1] + e2[2] * q[2])
    return t if t > eps else None


def _build_radiation_patches(face_groups):
    """
    ActiveSide に応じた (表面/裏面/両面) のメッシュを1パッチとして、
    重心・法線・面積・三角形リスト・放射率などを返す。
    戻り値: list of dict {center, normal, area_m2, triangles, patch_index, node_number, model_name, emissivity}
    同一ノード（両面時の front/back）は同じ node_number になるよう、NodeNumber 未設定時は id(node) で安定化する。
    """
    patches = []
    _node_id_to_num = {}  # 同一 node オブジェクトに同じ番号を振る（空間マージ用）
    for idx, (face_mesh_obj, node) in enumerate(_iter_radiation_patch_meshes(face_groups)):
        if not hasattr(face_mesh_obj, "Mesh") or not face_mesh_obj.Mesh:
            continue
        mesh = face_mesh_obj.Mesh
        try:
            points = [_mesh_point_to_xyz(p) for p in mesh.Points]
            facets = list(mesh.Facets)
        except Exception:
            continue
        if not points or not facets:
            continue

        def facet_triple(fa):
            if hasattr(fa, "PointIndices"):
                return tuple(fa.PointIndices)
            return (fa[0], fa[1], fa[2])

        triangles = []
        sum_cx, sum_cy, sum_cz = 0.0, 0.0, 0.0
        sum_nx, sum_ny, sum_nz = 0.0, 0.0, 0.0
        total_area = 0.0
        for fa in facets:
            i, j, k = facet_triple(fa)
            p0, p1, p2 = points[i], points[j], points[k]
            triangles.append((p0, p1, p2))
            cx = (p0[0] + p1[0] + p2[0]) / 3.0
            cy = (p0[1] + p1[1] + p2[1]) / 3.0
            cz = (p0[2] + p1[2] + p2[2]) / 3.0
            sum_cx += cx
            sum_cy += cy
            sum_cz += cz
            # 法線（外側）と面積の2倍
            e1 = (p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2])
            e2 = (p2[0] - p0[0], p2[1] - p0[1], p2[2] - p0[2])
            nx = e1[1] * e2[2] - e1[2] * e2[1]
            ny = e1[2] * e2[0] - e1[0] * e2[2]
            nz = e1[0] * e2[1] - e1[1] * e2[0]
            area2 = math.sqrt(nx * nx + ny * ny + nz * nz)
            if area2 > 1e-18:
                total_area += area2 * 0.5
                sum_nx += nx
                sum_ny += ny
                sum_nz += nz
        n_f = len(triangles)
        if n_f == 0:
            continue
        center = (sum_cx / n_f, sum_cy / n_f, sum_cz / n_f)
        nlen = math.sqrt(sum_nx * sum_nx + sum_ny * sum_ny + sum_nz * sum_nz)
        if nlen < 1e-18:
            normal = (0, 0, 1)
        else:
            normal = (sum_nx / nlen, sum_ny / nlen, sum_nz / nlen)
        area_m2 = (mesh.Area / 1000000.0) if hasattr(mesh, "Area") else (total_area / 1000000.0)
        emissivity = float(getattr(face_mesh_obj, "InfraredEmissivity", 0.85))
        transmittance = float(getattr(face_mesh_obj, "Transmittance", 0.0))
        transmittance = max(0.0, min(1.0, transmittance))
        model_name = str(getattr(node, "ModelName", "Model"))
        node_number = getattr(node, "NodeNumber", None)
        if node_number is None:
            # 同一ノードを安定して識別（FreeCAD では id(node) が変わり得るため Name を使用）
            node_key = (model_name, getattr(node, "Name", ""), getattr(node, "Label", ""))
            if node_key not in _node_id_to_num:
                _node_id_to_num[node_key] = len(_node_id_to_num)
            node_number = _node_id_to_num[node_key]
        node_number = int(node_number)
        # NumPy 配列として保持（multiprocessing で渡すため）
        center_np = np.array(center, dtype=np.float64)
        normal_np = np.array(normal, dtype=np.float64)
        triangles_np = np.array(triangles, dtype=np.float64)  # shape (n_tri, 3, 3)
        patches.append({
            "center": center_np,
            "normal": normal_np,
            "area_m2": area_m2,
            "triangles": triangles_np,
            "patch_index": len(patches),
            "node_number": node_number,
            "model_name": model_name,
            "emissivity": emissivity,
            "transmittance": transmittance,
        })
    return patches


def _random_hemisphere_direction(normal):
    """法線方向を上とした半球上でコサイン重み付きランダム方向を返す。(dx,dy,dz) 単位ベクトル。"""
    u = random.random()
    v = random.random()
    theta = math.acos(math.sqrt(u))
    phi = 2.0 * math.pi * v
    # 法線方向が (0,0,1) のときの半球上の点
    dx = math.sin(theta) * math.cos(phi)
    dy = math.sin(theta) * math.sin(phi)
    dz = math.cos(theta)
    # normal が (nx,ny,nz) になるように回転
    nx, ny, nz = normal[0], normal[1], normal[2]
    if abs(nz) < 0.999:
        ax, ay, az = -ny, nx, 0.0
    else:
        ax, ay, az = 0.0, -nz, ny
    alen = math.sqrt(ax * ax + ay * ay + az * az)
    if alen < 1e-18:
        return (dx, dy, dz)
    ax, ay, az = ax / alen, ay / alen, az / alen
    # ローカル (dx,dy,dz) をワールドに: 上方向が normal
    bx = ay * nz - az * ny
    by = az * nx - ax * nz
    bz = ax * ny - ay * nx
    wx = ax * dx + bx * dy + nx * dz
    wy = ay * dx + by * dy + ny * dz
    wz = az * dx + bz * dy + nz * dz
    wlen = math.sqrt(wx * wx + wy * wy + wz * wz)
    if wlen < 1e-18:
        return normal
    return (wx / wlen, wy / wlen, wz / wlen)


def _find_next_hit(origin, direction, patches, exclude_patch=None):
    """
    与えられた origin, direction から全パッチとの交点のうち、
    正の最小距離のパッチを返す。交差がなければ (None, None)。
    exclude_patch: このインデックスのパッチは無視（透過後の自己交差回避用）。
    """
    t_min = None
    j_hit = None
    for j in range(len(patches)):
        if exclude_patch is not None and j == exclude_patch:
            continue
        for tri in patches[j]["triangles"]:
            v0, v1, v2 = tri[0], tri[1], tri[2]
            t = _ray_triangle_intersect(origin, direction, tuple(v0), tuple(v1), tuple(v2))
            if t is not None and t > 1e-8 and (t_min is None or t < t_min):
                t_min = t
                j_hit = j
    return (j_hit, t_min)


def _monte_carlo_view_factors_sequential(patches, rays_per_patch):
    """
    並列化なしのモンテカルロ。透過率 > 0 の面ではレイが透過し、
    不透明面または空間に到達するまで追跡する。透過率 0 の場合は反射として扱う。
    """
    n = len(patches)
    Vf = [[0.0] * n for _ in range(n)]
    Vf_to_space = [0.0] * n
    eps_origin = 0.01
    eps_step = 1e-5
    for i in range(n):
        pi = patches[i]
        center = pi["center"]
        normal = pi["normal"]
        hits = [0] * n
        for _ in range(rays_per_patch):
            direction = _random_hemisphere_direction(tuple(normal))
            origin_off = (
                float(center[0]) + float(normal[0]) * eps_origin,
                float(center[1]) + float(normal[1]) * eps_origin,
                float(center[2]) + float(normal[2]) * eps_origin,
            )
            j_hit, t_min = _find_next_hit(origin_off, direction, patches, exclude_patch=i)
            while j_hit is not None:
                tau = patches[j_hit].get("transmittance", 0.0)
                if tau <= 0.0 or random.random() >= tau:
                    hits[j_hit] += 1
                    break
                hit_pt = (
                    origin_off[0] + direction[0] * t_min,
                    origin_off[1] + direction[1] * t_min,
                    origin_off[2] + direction[2] * t_min,
                )
                origin_off = (
                    hit_pt[0] + direction[0] * eps_step,
                    hit_pt[1] + direction[1] * eps_step,
                    hit_pt[2] + direction[2] * eps_step,
                )
                j_hit, t_min = _find_next_hit(origin_off, direction, patches, exclude_patch=j_hit)
            if j_hit is None:
                Vf_to_space[i] += 1.0
        for j in range(n):
            Vf[i][j] = hits[j] / rays_per_patch if rays_per_patch > 0 else 0.0
        space_fraction = Vf_to_space[i] if rays_per_patch > 0 else 0.0
        Vf_to_space[i] = space_fraction / rays_per_patch if rays_per_patch > 0 else 0.0
    return Vf, Vf_to_space


def _monte_carlo_view_factors(patches, rays_per_patch):
    """
    各パッチから半球方向にレイを発射し、当たったパッチをカウントしてビューファクターを推定。
    FreeCAD 内では multiprocessing の spawn が「-E」オプションエラーを起こすため逐次計算のみ行う。
    戻り値: (Vf[i][j] の 2次元リスト, Vf_to_space[i] のリスト)
    """
    n = len(patches)
    if n == 0:
        return [], []
    Vf = [[0.0] * n for _ in range(n)]
    Vf_to_space = [0.0] * n

    # FreeCAD 組み込み Python では spawn が FreeCAD 実行形式を -E 付きで起動し「unrecognised option '-E'」ダイアログが大量に出るため、並列は使わず逐次計算のみ行う。
    Vf, Vf_to_space = _monte_carlo_view_factors_sequential(patches, rays_per_patch)
    return Vf, Vf_to_space


def calculate_radiation_conductance(rays_per_patch=None):
    """
    レイトレーシングでビューファクターを計算し、輻射コンダクタンス係数 R'=ε×Vf×A（σ除く）を
    RadiationLinks グループに格納する。空間への輻射は SPACE.9999 ノードとのリンクとして出力。
    """
    doc = FreeCAD.ActiveDocument
    if not doc:
        return
    doc.recompute()
    face_groups = freecad_utils.get_face_groups(doc)
    if not face_groups:
        FreeCAD.Console.PrintError("FaceGroup が見つかりません。先にモデルを準備してください。\n")
        return
    base_obj = freecad_utils.get_base_object_from_face_groups(face_groups)
    model_name = getattr(face_groups[0], "ModelName", None) or _sanitize_model_name(getattr(base_obj, "Label", "Model"))

    patches = _build_radiation_patches(face_groups)
    if not patches:
        FreeCAD.Console.PrintError("輻射計算用のパッチが1つも取得できませんでした。\n")
        return

    rays_per_patch = rays_per_patch if rays_per_patch is not None else _RAYS_PER_PATCH_DEFAULT
    FreeCAD.Console.PrintMessage(f"輻射ビューファクターを計算します（パッチ数={len(patches)}、1パッチあたりレイ数={rays_per_patch}）...\n")
    Vf, Vf_to_space = _monte_carlo_view_factors(patches, rays_per_patch)

    # 各パッチで Vf の合計が 1 であることを検証（許容誤差 5%）
    n = len(patches)
    vf_sum_tolerance = 0.05
    bad_patches = []
    for i in range(n):
        vf_sum = sum(Vf[i][j] for j in range(n)) + Vf_to_space[i]
        if abs(vf_sum - 1.0) > vf_sum_tolerance:
            bad_patches.append((i, vf_sum))
    if bad_patches:
        msg_lines = [
            "一部のパッチでビューファクターの合計が 1 から 5% 以上ずれています。",
            "（レイ数を増やすと改善する場合があります）",
            "",
        ]
        for idx, vf_sum in bad_patches[:10]:
            node_num = patches[idx].get("node_number", idx)
            msg_lines.append(f"  パッチ {idx} (ノード {node_num}): 合計 = {vf_sum:.4f}")
        if len(bad_patches) > 10:
            msg_lines.append(f"  ... 他 {len(bad_patches) - 10} パッチ")
        msg = "\n".join(msg_lines)
        FreeCAD.Console.PrintWarning(msg + "\n")
        if FreeCAD.GuiUp:
            try:
                import FreeCADGui
                from PySide import QtGui
                QtGui.QMessageBox.warning(None, "輻射計算の検証", msg)
            except Exception:
                pass

    # 既存の RadiationLinks をすべて削除（同名・別名の残りを防ぐ）
    links_group_name = f"{getattr(base_obj, 'Label', 'Model')}_RadiationLinks"
    for obj in list(doc.Objects):
        if getattr(obj, "Name", "").endswith("_RadiationLinks") or getattr(obj, "Label", "").endswith("_RadiationLinks"):
            try:
                doc.removeObject(obj.Name)
            except Exception:
                pass
    doc.recompute()
    links_group = doc.addObject("App::DocumentObjectGroup", links_group_name)
    if not hasattr(links_group, "ModelName"):
        links_group.addProperty("App::PropertyString", "ModelName", "Internal")
    links_group.ModelName = model_name
    # 親グループに追加（伝熱コンダクタンスと同様）
    parent_group = None
    if face_groups and hasattr(face_groups[0], "InList") and face_groups[0].InList:
        for cand in face_groups[0].InList:
            if hasattr(cand, "Group") and face_groups[0] in getattr(cand, "Group", []):
                parent_group = cand
                break
    if parent_group:
        parent_group.addObject(links_group)

    seq = 0
    n = len(patches)
    # 面間の輻射リンク: ペア (i,j) を i < j で1本にまとめ、R'_ij と R'_ji の両方を持つ
    for i in range(n):
        for j in range(i + 1, n):
            vf_ij = Vf[i][j]
            vf_ji = Vf[j][i]
            if vf_ij <= 0.0 and vf_ji <= 0.0:
                continue
            pi, pj = patches[i], patches[j]
            node_i_id = f"{pi['model_name']}.{pi['node_number']}"
            node_j_id = f"{pj['model_name']}.{pj['node_number']}"
            # ノード番号の小さい方を Node1 にする（一意な並びのため）
            if pi["node_number"] <= pj["node_number"]:
                n1_id, n2_id = node_i_id, node_j_id
                R_prime_12 = calculation.calc_radiation_factor(pi["emissivity"], vf_ij, pi["area_m2"]) if vf_ij > 0 else 0.0
                R_prime_21 = calculation.calc_radiation_factor(pj["emissivity"], vf_ji, pj["area_m2"]) if vf_ji > 0 else 0.0
                formula_12 = f"({pi['emissivity']:.6g}*{vf_ij:.6g}*{pi['area_m2']:.6g})" if vf_ij > 0 else "0"
                formula_21 = f"({pj['emissivity']:.6g}*{vf_ji:.6g}*{pj['area_m2']:.6g})" if vf_ji > 0 else "0"
                p1, p2 = FreeCAD.Vector(*pi["center"]), FreeCAD.Vector(*pj["center"])
            else:
                n1_id, n2_id = node_j_id, node_i_id
                R_prime_12 = calculation.calc_radiation_factor(pj["emissivity"], vf_ji, pj["area_m2"]) if vf_ji > 0 else 0.0
                R_prime_21 = calculation.calc_radiation_factor(pi["emissivity"], vf_ij, pi["area_m2"]) if vf_ij > 0 else 0.0
                formula_12 = f"({pj['emissivity']:.6g}*{vf_ji:.6g}*{pj['area_m2']:.6g})" if vf_ji > 0 else "0"
                formula_21 = f"({pi['emissivity']:.6g}*{vf_ij:.6g}*{pi['area_m2']:.6g})" if vf_ij > 0 else "0"
                p1, p2 = FreeCAD.Vector(*pj["center"]), FreeCAD.Vector(*pi["center"])
            link_name = f"RadiationLink_{seq}"
            link_obj = doc.addObject("Part::Feature", link_name)
            link_obj.Shape = Part.LineSegment(p1, p2).toShape()
            if not hasattr(link_obj, "RadiationFactor"):
                link_obj.addProperty("App::PropertyFloat", "RadiationFactor", "Radiation", "R' Node1→Node2 [m²]")
            if not hasattr(link_obj, "RadiationFactor_2to1"):
                link_obj.addProperty("App::PropertyFloat", "RadiationFactor_2to1", "Radiation", "R' Node2→Node1 [m²]")
            if not hasattr(link_obj, "FormulaString"):
                link_obj.addProperty("App::PropertyString", "FormulaString", "Radiation", "計算式 Node1→Node2")
            if not hasattr(link_obj, "FormulaString_2to1"):
                link_obj.addProperty("App::PropertyString", "FormulaString_2to1", "Radiation", "計算式 Node2→Node1")
            if not hasattr(link_obj, "Node1Id"):
                link_obj.addProperty("App::PropertyString", "Node1Id", "Radiation", "ノード1 ID")
            if not hasattr(link_obj, "Node2Id"):
                link_obj.addProperty("App::PropertyString", "Node2Id", "Radiation", "ノード2 ID")
            link_obj.RadiationFactor = R_prime_12
            link_obj.RadiationFactor_2to1 = R_prime_21
            link_obj.FormulaString = formula_12
            link_obj.FormulaString_2to1 = formula_21
            # ツリー・エクスポート用: 1コンダクタンス値（両方向とも>0なら平均、そうでなければ非ゼロ側）
            if not hasattr(link_obj, "RadiationFactorEffective"):
                link_obj.addProperty("App::PropertyFloat", "RadiationFactorEffective", "Radiation", "R' 有効 [m²]（両方向の平均 or 片方向）")
            if R_prime_12 > 0.0 and R_prime_21 > 0.0:
                link_obj.RadiationFactorEffective = (R_prime_12 + R_prime_21) * 0.5
            else:
                link_obj.RadiationFactorEffective = R_prime_12 if R_prime_12 > 0.0 else R_prime_21
            link_obj.Node1Id = n1_id
            link_obj.Node2Id = n2_id
            link_obj.Label = f"{model_name}.{seq}"
            links_group.addObject(link_obj)
            _apply_radiation_link_view(link_obj)
            seq += 1
    # 空間への輻射: 同一ノード（両面など）は1本にマージし、R' を合算して計算式は連結
    space_by_node = defaultdict(list)  # (model_name, node_number) -> [(patch_index, R_prime, formula_str), ...]
    for i in range(n):
        vf_space = Vf_to_space[i]
        if vf_space <= 0.0:
            continue
        pi = patches[i]
        R_prime = calculation.calc_radiation_factor(pi["emissivity"], vf_space, pi["area_m2"])
        formula = f"({pi['emissivity']:.6g}*{vf_space:.6g}*{pi['area_m2']:.6g})"
        key = (str(pi["model_name"]), int(pi["node_number"]))
        space_by_node[key].append((i, R_prime, formula))
    for (model_name, node_number), parts in space_by_node.items():
        node_i_id = f"{model_name}.{node_number}"
        R_prime_total = sum(r for (_, r, _) in parts)
        formula_parts = [f for (_, _, f) in parts]
        formula_merged = "+".join(formula_parts) if len(formula_parts) > 1 else formula_parts[0]
        first_idx = parts[0][0]
        pi = patches[first_idx]
        link_name = f"RadiationLink_{seq}"
        link_obj = doc.addObject("Part::Feature", link_name)
        p1 = FreeCAD.Vector(*pi["center"])
        nx, ny, nz = pi["normal"]
        p2 = FreeCAD.Vector(
            pi["center"][0] + nx * 100.0,
            pi["center"][1] + ny * 100.0,
            pi["center"][2] + nz * 100.0,
        )
        link_obj.Shape = Part.LineSegment(p1, p2).toShape()
        if not hasattr(link_obj, "RadiationFactor"):
            link_obj.addProperty("App::PropertyFloat", "RadiationFactor", "Radiation", "R'=ε×Vf×A [m²]")
        if not hasattr(link_obj, "FormulaString"):
            link_obj.addProperty("App::PropertyString", "FormulaString", "Radiation", "計算式")
        if not hasattr(link_obj, "Node1Id"):
            link_obj.addProperty("App::PropertyString", "Node1Id", "Radiation", "ノード1 ID")
        if not hasattr(link_obj, "Node2Id"):
            link_obj.addProperty("App::PropertyString", "Node2Id", "Radiation", "ノード2 ID")
        link_obj.RadiationFactor = R_prime_total
        link_obj.FormulaString = formula_merged
        link_obj.Node1Id = node_i_id
        link_obj.Node2Id = _SPACE_NODE_ID
        link_obj.Label = f"{model_name}.{seq}"
        links_group.addObject(link_obj)
        _apply_radiation_link_view(link_obj)
        seq += 1

    if hasattr(links_group, "touch"):
        links_group.touch()
    FreeCAD.Console.PrintMessage(f"輻射コンダクタンスの計算が完了しました（リンク数={seq}）。\n")
    doc.recompute()


def export_radiation_dat(filepath):
    """
    輻射コンダクタンスリストを .dat 形式で書き出す（1リンク1行・1コンダクタンス値）。
    列: Node1Id, Node2Id, RadiationFactor_R_prime_m2, FormulaString
    面間は有効値 (R'12+R'21)/2、空間は Node2Id=SPACE.9999。
    """
    doc = FreeCAD.ActiveDocument
    if not doc:
        raise RuntimeError("アクティブなドキュメントがありません。")
    face_groups = freecad_utils.get_face_groups(doc)
    if not face_groups:
        raise RuntimeError("FaceGroup が見つかりません。")
    base_obj = freecad_utils.get_base_object_from_face_groups(face_groups)
    rad_group = None
    if base_obj:
        rad_group = doc.getObject(f"{base_obj.Label}_RadiationLinks")
    if not rad_group:
        for o in doc.Objects:
            if hasattr(o, "Group") and o.Name.endswith("_RadiationLinks"):
                rad_group = o
                break
    if not rad_group or not hasattr(rad_group, "Group"):
        raise RuntimeError("輻射リンクグループが見つかりません。先に輻射コンダクタンスを計算してください。")
    sep = "\t"
    lines = [
        sep.join(["Node1Id", "Node2Id", "RadiationFactor_R_prime_m2", "FormulaString"]),
    ]
    for link in rad_group.Group:
        n1 = getattr(link, "Node1Id", "")
        n2 = getattr(link, "Node2Id", "")
        rp1 = getattr(link, "RadiationFactor", 0.0)
        formula = getattr(link, "FormulaString", "(ε×Vf×A)")
        rp2 = getattr(link, "RadiationFactor_2to1", None)
        formula2 = getattr(link, "FormulaString_2to1", "") if rp2 is not None else ""
        if rp2 is not None and rp2 > 0.0 and rp1 > 0.0:
            rp_eff = (rp1 + rp2) * 0.5
            formula_eff = f"(({formula})+({formula2}))/2"
        else:
            rp_eff = rp1 if rp1 > 0.0 else (rp2 if rp2 is not None else 0.0)
            formula_eff = formula if rp1 > 0.0 else (formula2 if formula2 else formula)
        if rp_eff > 0.0:
            lines.append(sep.join([n1, n2, f"{rp_eff:.6e}", formula_eff]))
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    FreeCAD.Console.PrintMessage(f"輻射コンダクタンスリストをエクスポートしました: {filepath}\n")


# =========================================================
# SOLVER FILE EXPORT  (combined .inp)
#
# Writes the complete thermal model (nodes, conduction links,
# radiation links, OPTIONS / CONTROL headers) into a single
# .inp file consumed by the external thermal solver.
# Individual .dat exports live in the CONDUCTANCE section
# above; this function combines everything.
# =========================================================

def export_thermal_model_inp(filepath, options_data=None, control_data=None, default_initial_temperature=20.0):
    """
    README2.md に従い、熱解析ソルバー用 .inp を1ファイルで出力する。
    options_data: HEADER OPTIONS DATA の KEY=VALUE の dict（例: {"OUTPUT.DQ": "TRUE", "OUTPUT.GRAPH": "FALSE"}）
    control_data: HEADER CONTROL DATA の KEY=VALUE の dict（例: {"TIMESTART": "0", "TIMEND": "3600", "DT": "60", "ANALYSIS": "STEADY"}）
    """
    doc = FreeCAD.ActiveDocument
    if not doc:
        raise RuntimeError("アクティブなドキュメントがありません。")
    face_groups = freecad_utils.get_face_groups(doc)
    if not face_groups:
        raise RuntimeError("FaceGroup が見つかりません。先にモデルを準備してください。")

    # BaseObject（元形状オブジェクト）ごとにグループ分けし、サブモデル単位で出力する
    base_groups_map = {}
    for g in face_groups:
        base = getattr(g, "BaseObject", None)
        base_groups_map.setdefault(base, []).append(g)

    options_data = options_data or {}
    control_data = control_data or {}

    lines = []
    lines.append("# Thermal Model Export - RadiationAnalysis")
    lines.append("")

    # データ行の先頭に付ける8文字半角空白
    _pad = "        "

    # HEADER OPTIONS DATA
    lines.append("HEADER OPTIONS DATA")
    for k, v in options_data.items():
        lines.append(f"{_pad}{k} = {v}")
    lines.append("")

    # HEADER CONTROL DATA
    lines.append("HEADER CONTROL DATA")
    for k, v in control_data.items():
        lines.append(f"{_pad}{k} = {v}")
    lines.append("")

    # BaseObject（サブモデル）ごとに NODE / CONDUCTOR / SOURCE / RAD データを一旦集めてから、
    # ユーザ指定の順序で出力する。
    model_order = []
    node_lines_by_model = {}
    source_lines_by_model = {}
    cond_lines_by_model = {}
    rad_entries = []
    needs_space_node = False

    for base_obj, groups in base_groups_map.items():
        model_name = getattr(groups[0], "ModelName", None) or _sanitize_model_name(
            getattr(base_obj, "Label", getattr(base_obj, "Name", "Model"))
        )
        model_order.append(model_name)

        # 各 BaseObject に対応するリンクグループ・輻射グループを取得
        links_group = doc.getObject(f"{getattr(base_obj, 'Label', '')}_ConductanceLinks") if base_obj else None
        if not links_group:
            for o in doc.Objects:
                if hasattr(o, "Group") and o.Name.endswith("_ConductanceLinks") and getattr(o, "ModelName", None) == model_name:
                    links_group = o
                    break
        rad_group = doc.getObject(f"{getattr(base_obj, 'Label', '')}_RadiationLinks") if base_obj else None
        if not rad_group:
            for o in doc.Objects:
                if hasattr(o, "Group") and o.Name.endswith("_RadiationLinks") and getattr(o, "ModelName", None) == model_name:
                    rad_group = o
                    break

        # NODE DATA, <model_name>
        node_lines = []
        seen_node_numbers = set()
        for group in groups:
            for (_front_face, node) in _iter_face_groups_front_and_node([group]):
                node_number = getattr(node, "NodeNumber", 0)
                if node_number in seen_node_numbers:
                    continue
                seen_node_numbers.add(node_number)
                cap = getattr(node, "ThermalCapacity", None)
                if cap is None:
                    cap_str = "0"
                elif cap < 0:
                    cap_str = "-1.0"
                else:
                    # 熱容量を計算式で出力: Area*Thickness*Density*SpecificHeat
                    if getattr(_front_face, "Mesh", None):
                        area_m2 = _front_face.Mesh.Area / 1000000.0
                        t_m, d, sh, _ = _get_face_thermal_values(_front_face)
                        cap_str = f"({area_m2:.6g}*{t_m:.6g}*{d:.6g}*{sh:.6g})"
                    else:
                        cap_str = f"{cap:.6g}"
                node_lines.append(f"{_pad}{node_number}, {default_initial_temperature}, {cap_str}")
        node_lines_by_model[model_name] = node_lines

        # BASE ごとの SOURCE DATA を収集
        source_lines = []
        seen_source_nodes = set()
        for group in groups:
            for (_front_face, node) in _iter_face_groups_front_and_node([group]):
                node_number = getattr(node, "NodeNumber", 0)
                if node_number in seen_source_nodes:
                    continue
                heat = getattr(node, "HeatSource", 0.0)
                if not isinstance(heat, (int, float)) or abs(float(heat)) < 1e-12:
                    continue
                seen_source_nodes.add(node_number)
                source_lines.append(f"{_pad}{node_number}, {float(heat):.6g}")
        source_lines_by_model[model_name] = source_lines

        # CONDUCTOR DATA（導体）を収集
        cond_lines = []
        cond_seq = 1
        if links_group and hasattr(links_group, "Group"):
            link_model_name = getattr(links_group, "ModelName", None) or model_name
            for link in links_group.Group:
                if not hasattr(link, "Conductance"):
                    continue
                cid = getattr(link, "ConductanceNumber", None)
                if cid is None:
                    cid = cond_seq
                    cond_seq += 1
                else:
                    cond_seq = max(cond_seq, cid + 1)
                n1 = getattr(link, "NodeNumber1", 0)
                n2 = getattr(link, "NodeNumber2", 0)
                node1_id = f"{link_model_name}.{n1}"
                node2_id = f"{link_model_name}.{n2}"
                g_expr = getattr(link, "FormulaString", None)
                if not g_expr:
                    g_expr = f"{link.Conductance:.6g}"
                cond_lines.append(f"{_pad}{cid}, {node1_id}, {node2_id}, {g_expr}")
        cond_lines_by_model[model_name] = cond_lines

        # 輻射コンダクタンスは RADK セクション用に別途蓄積
        if rad_group and hasattr(rad_group, "Group"):
            for link in rad_group.Group:
                n1 = getattr(link, "Node1Id", "")
                n2 = getattr(link, "Node2Id", "")
                rp1 = getattr(link, "RadiationFactor", 0.0)
                rp_expr = getattr(link, "FormulaString", None)
                if not rp_expr:
                    rp_expr = f"{rp1:.6g}"
                rp2 = getattr(link, "RadiationFactor_2to1", None)
                rp_expr2 = getattr(link, "FormulaString_2to1", None) if rp2 is not None else None
                if rp_expr2 is None and rp2 is not None and rp2 > 0.0:
                    rp_expr2 = f"{rp2:.6g}"
                # 1ペア1行・1コンダクタンス値: 面間で両方向>0なら (R'12+R'21)/2、片方向のみならその値
                if rp2 is not None and rp2 > 0.0 and rp1 > 0.0:
                    g_rad_expr = f"(({rp_expr})+({rp_expr2}))/(2.0*{_STEFAN_BOLTZMANN_CONST:.6g})"
                else:
                    g_rad_expr = f"({rp_expr})/{_STEFAN_BOLTZMANN_CONST:.6g}"
                rad_entries.append((n1, n2, g_rad_expr))
                if n2 == _SPACE_NODE_ID or n1 == _SPACE_NODE_ID:
                    needs_space_node = True

    # まず NODE DATA（各サブモデル）を出力
    for model_name in model_order:
        lines.append(f"HEADER NODE DATA, {model_name}")
        lines.extend(node_lines_by_model.get(model_name, []))
        lines.append("")

    # 空間ノード（SPACE）はまとめて 1 つだけ出力
    if needs_space_node:
        lines.append("HEADER NODE DATA, SPACE")
        lines.append(f"{_pad}-9999, -273.15, BOUNDARY")
        lines.append("")

    # 次に CONDUCTOR DATA（各サブモデルの導体）を出力
    for model_name in model_order:
        lines.append(f"HEADER CONDUCTOR DATA, {model_name}")
        lines.extend(cond_lines_by_model.get(model_name, []))
        lines.append("")

    # 輻射コンダクタンスは HEADER CONDUCTOR DATA, RADK にまとめ、行頭は -連番 とする
    if rad_entries:
        lines.append("HEADER CONDUCTOR DATA, RADK")
        rad_seq = 1
        for (n1, n2, g_rad_expr) in rad_entries:
            lines.append(f"{_pad}-{rad_seq}, {n1}, {n2}, {g_rad_expr}")
            rad_seq += 1
        lines.append("")

    # 最後に SOURCE DATA（各サブモデル）を出力
    for model_name in model_order:
        lines.append(f"HEADER SOURCE DATA, {model_name}")
        lines.extend(source_lines_by_model.get(model_name, []))
        lines.append("")

    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    FreeCAD.Console.PrintMessage(f"Thermal Model Export しました: {filepath}\n")