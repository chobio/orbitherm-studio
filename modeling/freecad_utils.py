import os

import FreeCAD
import FreeCADGui


def get_default_export_dir():
    """アクティブなドキュメントの保存先ディレクトリを返す。未保存の場合は空文字。"""
    doc = FreeCAD.ActiveDocument
    if doc and getattr(doc, "FileName", None) and doc.FileName:
        d = os.path.dirname(doc.FileName)
        if d and os.path.isdir(d):
            return d
    return ""


def get_face_mesh_objects_from_selection():
    """
    現在の選択からフェイスメッシュオブジェクトのリストを取得する。
    元の `core.get_face_mesh_objects_from_selection` の実装をここに集約。
    """
    doc = FreeCAD.ActiveDocument
    if not doc:
        return []

    selection = FreeCADGui.Selection.getSelection()
    if not selection:
        FreeCAD.Console.PrintError("オブジェクトを選択してください。\n")
        return []

    face_meshes = []
    for sel_obj in selection:
        if sel_obj.isDerivedFrom("App::DocumentObjectGroup"):
            for obj in sel_obj.Group:
                if obj.isDerivedFrom("Mesh::Feature"):
                    face_meshes.append(obj)
                elif hasattr(obj, "Group"):
                    face_meshes.extend(
                        [o for o in obj.Group if o.isDerivedFrom("Mesh::Feature")]
                    )
        elif sel_obj.isDerivedFrom("Mesh::Feature"):
            face_meshes.append(sel_obj)
        elif (
            hasattr(sel_obj, "Source")
            and sel_obj.Source
            and sel_obj.Source.isDerivedFrom("App::DocumentObjectGroup")
        ):
            for obj in sel_obj.Source.Group:
                if obj.isDerivedFrom("Mesh::Feature"):
                    face_meshes.append(obj)
                elif hasattr(obj, "Group"):
                    face_meshes.extend(
                        [o for o in obj.Group if o.isDerivedFrom("Mesh::Feature")]
                    )

    if not face_meshes:
        FreeCAD.Console.PrintError(
            "選択対象から有効なフェイスメッシュが見つかりません。\n"
        )
        return []

    # 重複を順序を保ったまま除去
    return list(dict.fromkeys(face_meshes))


def build_face_pairs(face_meshes):
    """
    Face_x_front / Face_x_back のペアを構築して dict で返す。
    戻り値: { base_name: { 'front': obj, 'back': obj }, ... }
    """
    face_pairs = {}
    for obj in face_meshes:
        base_name, _, side = obj.Name.rpartition("_")
        if base_name not in face_pairs:
            face_pairs[base_name] = {}
        face_pairs[base_name][side] = obj
    return face_pairs


def sync_active_side(front_obj, back_obj):
    """
    front/back の ActiveSide プロパティを同期する。
    必要であれば back 側に列挙プロパティを追加して同じ値に揃える。
    """
    active_side = getattr(front_obj, "ActiveSide", getattr(back_obj, "ActiveSide", "未設定"))

    if hasattr(front_obj, "ActiveSide"):
        if not hasattr(back_obj, "ActiveSide") or back_obj.ActiveSide != front_obj.ActiveSide:
            if not hasattr(back_obj, "ActiveSide"):
                back_obj.addProperty(
                    "App::PropertyEnumeration",
                    "ActiveSide",
                    "Thermal",
                    "輻射計算の対象面",
                )
                back_obj.ActiveSide = ["両面", "表面", "裏面"]
            back_obj.ActiveSide = front_obj.ActiveSide

    return active_side


def _mesh_outward_normal(front_obj):
    """表面メッシュの第1ファセットから外向き法線を取得。失敗時は None。"""
    if not hasattr(front_obj, "Mesh") or not front_obj.Mesh:
        return None
    mesh = front_obj.Mesh
    if not getattr(mesh, "Facets", None) or not getattr(mesh, "Points", None):
        return None
    facets = mesh.Facets
    points = mesh.Points
    if len(facets) == 0 or len(points) < 3:
        return None
    fa = facets[0]
    if hasattr(fa, "PointIndices"):
        i, j, k = fa.PointIndices
    else:
        i, j, k = int(fa[0]), int(fa[1]), int(fa[2])
    def to_vec(p):
        if hasattr(p, "x"):
            return FreeCAD.Vector(float(p.x), float(p.y), float(p.z))
        return FreeCAD.Vector(float(p[0]), float(p[1]), float(p[2]))
    p0 = to_vec(points[i])
    p1 = to_vec(points[j])
    p2 = to_vec(points[k])
    n = (p1 - p0).cross(p2 - p0)
    if n.Length < 1e-10:
        return None
    n.normalize()
    return n


# 表裏メッシュを法線方向にずらす距離 [mm]。同一平面だと裏だけヒットするため、わずかに分離する。
_FACE_PAIR_OFFSET_MM = 0.02


def apply_face_pair_offset(face_meshes):
    """
    表裏メッシュを法線方向にわずかにオフセットし、表からは表面・裏からは裏面が
    選択・表示されるようにする。Placement.Base のみ変更する。
    """
    if not face_meshes:
        return
    face_pairs = build_face_pairs(face_meshes)
    offset_mm = _FACE_PAIR_OFFSET_MM
    for _base_name, sides in face_pairs.items():
        front_obj = sides.get("front")
        back_obj = sides.get("back")
        if not front_obj or not back_obj:
            continue
        n = _mesh_outward_normal(front_obj)
        if n is None:
            continue
        try:
            front_obj.Placement.Base = n * offset_mm
            back_obj.Placement.Base = -n * offset_mm
        except Exception:
            pass


def clear_face_pair_offset(face_meshes):
    """
    表裏メッシュの Placement.Base を (0,0,0) に戻し、オフセット表示を解除する。
    表示をデフォルトに戻すときに使用する。
    """
    if not face_meshes:
        return
    try:
        zero = FreeCAD.Vector(0, 0, 0)
    except Exception:
        return
    face_pairs = build_face_pairs(face_meshes)
    for _base_name, sides in face_pairs.items():
        front_obj = sides.get("front")
        back_obj = sides.get("back")
        if front_obj:
            try:
                front_obj.Placement.Base = zero
            except Exception:
                pass
        if back_obj:
            try:
                back_obj.Placement.Base = zero
            except Exception:
                pass


def apply_active_side_visibility(face_meshes):
    """
    アクティブ面表示用に表裏の ViewObject.Visibility を更新する。
    片面アクティブでも表裏とも表示し、色（緑=アクティブ/赤=非アクティブ）で
    区別する。見る方向で「表=緑・裏=赤」が分かる。
    """
    if not face_meshes or not FreeCAD.GuiUp:
        return
    face_pairs = build_face_pairs(face_meshes)
    for _base_name, sides in face_pairs.items():
        front_obj = sides.get("front")
        back_obj = sides.get("back")
        if not front_obj or not back_obj:
            continue
        # 表裏とも常に表示し、色でアクティブ/非アクティブを区別する
        front_obj.ViewObject.Visibility = True
        back_obj.ViewObject.Visibility = True
    # 表裏をわずかにオフセットして両方選択・表示できるようにする
    apply_face_pair_offset(face_meshes)


def get_face_groups(doc):
    """
    ドキュメントから FaceGroup_ で始まるグループオブジェクトを列挙する。
    """
    return [obj for obj in doc.Objects if obj.Name.startswith("FaceGroup_")]


def get_base_object_from_face_groups(face_groups):
    """
    FaceGroup から元の BaseObject を取得する。
    現状は先頭グループの BaseObject を返す実装。
    """
    if not face_groups:
        return None
    first_group = face_groups[0]
    return getattr(first_group, "BaseObject", None)

