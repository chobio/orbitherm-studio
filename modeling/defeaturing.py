# -*- coding: utf-8 -*-
"""
Defeaturing: 穴とフィレットをまとめて削除する処理。
ThermalAnalysis ワークベンチのコマンドおよびマクロから利用する。
"""

import FreeCAD
import Part
import os
import json
import time

# #region agent log
def _dbg_log(location, message, data, hypothesis_id):
    try:
        mod_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        log_path = os.path.join(mod_dir, "debug-32be65.log")
        payload = {"sessionId": "32be65", "hypothesisId": hypothesis_id, "location": location, "message": message, "data": data, "timestamp": int(time.time() * 1000)}
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass
# #endregion


def _is_hole_face(face, hole_max_radius_mm):
    """穴の円筒面かどうか（半径 <= hole_max_radius_mm）"""
    if hole_max_radius_mm <= 0:
        return False
    try:
        surf = face.Surface
        if surf is None:
            return False
        r = getattr(surf, "Radius", None)
        if r is not None and float(r) <= hole_max_radius_mm:
            return True
    except Exception:
        pass
    return False


def _is_fillet_face(face, fillet_max_radius_mm):
    """フィレットのトーラス面かどうか（MinorRadius <= fillet_max_radius_mm）"""
    if fillet_max_radius_mm <= 0:
        return False
    try:
        surf = face.Surface
        if surf is None:
            return False
        minor_r = getattr(surf, "MinorRadius", None)
        if minor_r is not None and float(minor_r) <= fillet_max_radius_mm:
            return True
        r2 = getattr(surf, "Radius2", None)
        if r2 is not None and float(r2) <= fillet_max_radius_mm:
            return True
    except Exception:
        pass
    return False


def _collect_faces_to_remove(shape, hole_max_radius_mm, fillet_max_radius_mm):
    """形状から削除対象の面（穴・フィレット）を収集"""
    to_remove = []
    try:
        faces = getattr(shape, "Faces", None) or []
    except Exception:
        return to_remove
    for f in faces:
        if _is_hole_face(f, hole_max_radius_mm):
            to_remove.append(f)
        elif _is_fillet_face(f, fillet_max_radius_mm):
            to_remove.append(f)
    return to_remove


def run_defeaturing(hole_max_diameter_mm=6.5, fillet_max_radius_mm=4.0):
    """
    選択中の Part オブジェクトに対して、穴とフィレットを削除した新しい形状を作成する。

    Args:
        hole_max_diameter_mm: 削除する穴の最大直径 [mm]。この値以下の円筒面を穴として削除する。
        fillet_max_radius_mm: 削除するフィレットの最大 R [mm]。この値以下のトーラス面を削除する。

    Returns:
        bool: 成功した場合 True、選択なし・エラー時は False。
    """
    doc = FreeCAD.ActiveDocument
    if not doc:
        FreeCAD.Console.PrintError("アクティブなドキュメントがありません。\n")
        return False

    try:
        sel = FreeCAD.Gui.Selection.getSelectionEx()
    except Exception:
        sel = []
    if not sel:
        FreeCAD.Console.PrintError("オブジェクトを1つ選択してから実行してください。\n")
        return False

    obj = sel[0].Object
    # #region agent log
    inlist = getattr(obj, "InList", []) or []
    _dbg_log("defeaturing.py:entry", "run_defeaturing entry", {"objName": getattr(obj, "Name", None), "objLabel": getattr(obj, "Label", None), "inListLen": len(inlist), "parentTypes": [type(p).__name__ for p in inlist[:5]]}, "A")
    # #endregion
    try:
        shape = obj.Shape
    except Exception as e:
        FreeCAD.Console.PrintError("形状を取得できません: {}\n".format(e))
        return False

    if not shape or not getattr(shape, "Faces", None):
        FreeCAD.Console.PrintError("選択したオブジェクトに面がありません。Part ソリッドを選択してください。\n")
        return False

    hole_max_radius_mm = float(hole_max_diameter_mm) / 2.0 if hole_max_diameter_mm > 0 else 0.0
    fillet_max_radius_mm = float(fillet_max_radius_mm)

    solids = getattr(shape, "Solids", None) or []
    if not solids and getattr(shape, "Solid", None):
        solids = [shape.Solid]
    if not solids:
        faces_to_remove = _collect_faces_to_remove(shape, hole_max_radius_mm, fillet_max_radius_mm)
        if not faces_to_remove:
            FreeCAD.Console.PrintMessage("削除対象の穴・フィレット面は見つかりませんでした。\n")
            return False
        FreeCAD.Console.PrintMessage("削除対象: {} 面（穴・フィレット）\n".format(len(faces_to_remove)))
        try:
            new_shape = shape.defeaturing(faces_to_remove)
        except Exception as e:
            FreeCAD.Console.PrintError("Defeaturing に失敗しました: {}\n".format(e))
            return False
    else:
        new_solids = []
        total_removed = 0
        for solid in solids:
            faces_to_remove = _collect_faces_to_remove(solid, hole_max_radius_mm, fillet_max_radius_mm)
            total_removed += len(faces_to_remove)
            if faces_to_remove:
                try:
                    new_solids.append(solid.defeaturing(faces_to_remove))
                except Exception as e:
                    FreeCAD.Console.PrintWarning("ソリッドの Defeaturing でスキップ: {}\n".format(e))
                    new_solids.append(solid)
            else:
                new_solids.append(solid)

        if total_removed == 0:
            FreeCAD.Console.PrintMessage("削除対象の穴・フィレット面は見つかりませんでした。\n")
            return False
        FreeCAD.Console.PrintMessage("削除対象: 合計 {} 面（穴・フィレット）\n".format(total_removed))

        if len(new_solids) == 1:
            new_shape = new_solids[0]
        else:
            new_shape = Part.Compound(new_solids)

    # 新オブジェクトの表示名は元の Label を継承
    original_label = (getattr(obj, "Label", None) or getattr(obj, "Name", "")) or "Part"
    # 内部名は一意にする（英数字と _ のみ）。元の Name に _Defeatured を付与
    safe_name = "".join(c for c in getattr(obj, "Name", "Part") if c.isalnum() or c in "._") or "Part"
    base_name = (safe_name[:72] + "_Defeatured") if len(safe_name) > 72 else (safe_name + "_Defeatured")
    name = base_name
    if doc.getObject(name):
        suffix = 1
        while doc.getObject("{}_{:03d}".format(base_name, suffix)):
            suffix += 1
        name = "{}_{:03d}".format(base_name, suffix)
    new_obj = doc.addObject("Part::Feature", name)
    new_obj.Label = original_label
    new_obj.Shape = new_shape
    # 元パーツと同じ位置・向きで表示するため Placement をコピー（アッセンブリの場合はグローバル Placement）
    try:
        from orbitherm_studio.modeling.core import _get_global_placement
        pl = _get_global_placement(obj)
        if pl is not None:
            new_obj.Placement = pl
        else:
            new_obj.Placement = getattr(obj, "Placement", new_obj.Placement)
    except Exception:
        new_obj.Placement = getattr(obj, "Placement", new_obj.Placement)
    # #region agent log
    _dbg_log("defeaturing.py:after_new_obj", "new_obj created and Shape set", {"newObjName": new_obj.Name}, "E")
    # #endregion

    # Original フォルダへ移動するのは、親が App::DocumentObjectGroup のときのみ行う。
    # 親が Part（アッセンブリ等）のときに removeObject を呼ぶと GUI 更新で Access violation を起こすためスキップする。
    move_to_original = False
    for parent in getattr(obj, "InList", []) or []:
        if getattr(parent, "Group", None) is not None and obj in list(parent.Group):
            move_to_original = getattr(parent, "TypeId", "") == "App::DocumentObjectGroup"
            # #region agent log
            _dbg_log("defeaturing.py:parent_check", "parent type check", {"parentName": getattr(parent, "Name", None), "parentTypeId": getattr(parent, "TypeId", None), "move_to_original": move_to_original}, "A")
            # #endregion
            break

    if move_to_original:
        original_group = doc.getObject("Original")
        if original_group is None:
            original_group = doc.addObject("App::DocumentObjectGroup", "Original")
            original_group.Label = "Original"
        for parent in getattr(obj, "InList", []) or []:
            if getattr(parent, "Group", None) is not None and obj in list(parent.Group):
                try:
                    parent.removeObject(obj)
                except Exception:
                    pass
                break
        try:
            original_group.addObject(obj)
        except Exception as e:
            FreeCAD.Console.PrintWarning("Original への移動でスキップしました: {}\n".format(e))

    # #region agent log
    _dbg_log("defeaturing.py:before_visibility", "before Visibility=False", {"guiUp": bool(FreeCAD.GuiUp), "moved_to_original": move_to_original}, "C")
    # #endregion
    if FreeCAD.GuiUp and getattr(obj, "ViewObject", None) is not None:
        obj.ViewObject.Visibility = False
    # #region agent log
    _dbg_log("defeaturing.py:before_recompute", "before doc.recompute", {}, "D")
    # #endregion
    doc.recompute()
    # #region agent log
    _dbg_log("defeaturing.py:after_recompute", "after doc.recompute", {}, "D")
    # #endregion
    if move_to_original:
        FreeCAD.Console.PrintMessage("オブジェクト '{}' を作成し、元のパーツを Original に移動しました。\n".format(new_obj.Label))
    else:
        FreeCAD.Console.PrintMessage("オブジェクト '{}' を作成しました。元のパーツは非表示のまま現在の階層に残しています。\n".format(new_obj.Label))
    return True


def _parse_face_indices_from_sub_names(sub_element_names):
    """SubElementNames から Face インデックス（0-based）のリストを重複除去・ソートして返す。"""
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


def run_defeaturing_selected_faces():
    """
    選択したオブジェクトのうち、サブ選択された面だけを Defeaturing で削除した新しい形状を作成する。
    オブジェクトを選択したうえで、削除したい面を Ctrl+クリックで複数選択してから実行する。

    Returns:
        bool: 成功した場合 True。
    """
    doc = FreeCAD.ActiveDocument
    if not doc:
        FreeCAD.Console.PrintError("アクティブなドキュメントがありません。\n")
        return False

    try:
        sel = FreeCAD.Gui.Selection.getSelectionEx()
    except Exception:
        sel = []
    if not sel:
        FreeCAD.Console.PrintError("オブジェクトを選択し、削除する面をサブ選択してから実行してください。\n")
        return False

    obj = sel[0].Object
    sub_names = getattr(sel[0], "SubElementNames", []) or []
    face_indices = _parse_face_indices_from_sub_names(sub_names)
    if not face_indices:
        FreeCAD.Console.PrintError("削除する面をサブ選択してください（3Dビューで面を Ctrl+クリック）。\n")
        return False

    try:
        shape = obj.Shape
    except Exception as e:
        FreeCAD.Console.PrintError("形状を取得できません: {}\n".format(e))
        return False

    if not shape or not getattr(shape, "Faces", None):
        FreeCAD.Console.PrintError("選択したオブジェクトに面がありません。\n")
        return False

    faces_to_remove = []
    for i in face_indices:
        if i < len(shape.Faces):
            faces_to_remove.append(shape.Faces[i])

    if not faces_to_remove:
        FreeCAD.Console.PrintError("有効な面が選択されていません。\n")
        return False

    solids = getattr(shape, "Solids", None) or []
    if not solids and getattr(shape, "Solid", None):
        solids = [shape.Solid]

    if not solids:
        try:
            new_shape = shape.defeaturing(faces_to_remove)
        except Exception as e:
            FreeCAD.Console.PrintError("Defeaturing に失敗しました: {}\n".format(e))
            return False
    else:
        # 複数ソリッド時: shape.Faces の並びは先頭ソリッドの面から順なので、グローバル面インデックスでソリッドを特定する
        new_solids = []
        offset = 0
        for solid in solids:
            nf = len(solid.Faces)
            solid_faces_to_remove = []
            for local_j in range(nf):
                if (offset + local_j) in face_indices:
                    solid_faces_to_remove.append(solid.Faces[local_j])
            offset += nf
            if not solid_faces_to_remove:
                new_solids.append(solid)
                continue
            try:
                new_solids.append(solid.defeaturing(solid_faces_to_remove))
            except Exception as e:
                FreeCAD.Console.PrintWarning("ソリッドの Defeaturing でスキップ: {}\n".format(e))
                new_solids.append(solid)
        new_shape = new_solids[0] if len(new_solids) == 1 else Part.Compound(new_solids)

    original_label = (getattr(obj, "Label", None) or getattr(obj, "Name", "")) or "Part"
    safe_name = "".join(c for c in getattr(obj, "Name", "Part") if c.isalnum() or c in "._") or "Part"
    base_name = (safe_name[:72] + "_Defeatured") if len(safe_name) > 72 else (safe_name + "_Defeatured")
    name = base_name
    if doc.getObject(name):
        suffix = 1
        while doc.getObject("{}_{:03d}".format(base_name, suffix)):
            suffix += 1
        name = "{}_{:03d}".format(base_name, suffix)
    new_obj = doc.addObject("Part::Feature", name)
    new_obj.Label = original_label
    new_obj.Shape = new_shape
    try:
        from orbitherm_studio.modeling.core import _get_global_placement
        pl = _get_global_placement(obj)
        if pl is not None:
            new_obj.Placement = pl
        else:
            new_obj.Placement = getattr(obj, "Placement", new_obj.Placement)
    except Exception:
        new_obj.Placement = getattr(obj, "Placement", new_obj.Placement)

    move_to_original = False
    for parent in getattr(obj, "InList", []) or []:
        if getattr(parent, "Group", None) is not None and obj in list(parent.Group):
            move_to_original = getattr(parent, "TypeId", "") == "App::DocumentObjectGroup"
            break
    if move_to_original:
        original_group = doc.getObject("Original")
        if original_group is None:
            original_group = doc.addObject("App::DocumentObjectGroup", "Original")
            original_group.Label = "Original"
        for parent in getattr(obj, "InList", []) or []:
            if getattr(parent, "Group", None) is not None and obj in list(parent.Group):
                try:
                    parent.removeObject(obj)
                except Exception:
                    pass
                break
        try:
            original_group.addObject(obj)
        except Exception as e:
            FreeCAD.Console.PrintWarning("Original への移動でスキップしました: {}\n".format(e))
    if FreeCAD.GuiUp and getattr(obj, "ViewObject", None) is not None:
        obj.ViewObject.Visibility = False

    doc.recompute()
    FreeCAD.Console.PrintMessage("選択した {} 面を削除したオブジェクト '{}' を作成しました。\n".format(len(faces_to_remove), new_obj.Label))
    return True
