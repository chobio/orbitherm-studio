# -*- coding: utf-8 -*-
"""
Persistent 3D label display for ThermalAnalysis workbench.

Labels are rendered directly in the FreeCAD 3D viewer via the Coin3D
scene graph (pivy).  No Part::Feature geometry is created in the document
tree.

Label orientation
-----------------
When a face normal vector is available each label is rendered as a
SoAsciiText node that lies flat on the face surface and reads
horizontally when viewed from outside (from the direction of the normal).
This is achieved by applying a SoTransform whose rotation maps the
default +Z axis onto the face normal, so the text's XY plane coincides
with the face plane.

When no normal is available (rare fallback) a SoText2 screen-space label
is used instead so something is always visible.

Public API
----------
show_face_labels(doc=None)   – display face-number labels in the 3D view
clear_face_labels()          – remove face-number labels
show_node_labels(doc=None)   – display node-number labels in the 3D view
clear_node_labels()          – remove node-number labels
is_face_labels_visible()     – True if face labels are currently shown
is_node_labels_visible()     – True if node labels are currently shown
"""

from __future__ import annotations

import FreeCAD

# ---------------------------------------------------------------------------
# Internal registry  {key: (scene_graph_root, our_SoSeparator)}
# ---------------------------------------------------------------------------
_registry: dict[str, tuple] = {}

_KEY_FACE = "TA_face_labels"
_KEY_NODE = "TA_node_labels"

# Base font size in world-units (mm).  Scaled by LabelScalePercent pref.
_BASE_FONT_MM = 20.0


def _active_view():
    """Return the active FreeCAD 3D view, or None if unavailable."""
    try:
        import FreeCADGui
        return FreeCADGui.ActiveDocument.ActiveView
    except Exception:
        return None


def _label_scale():
    """Return the user-configured label scale (1.0 = 100 %)."""
    try:
        from orbitherm_studio.modeling import core
        return max(0.1, core.get_pref_label_scale_percent() / 100.0)
    except Exception:
        return 1.0


def _make_rotation(normal):
    """
    Build a SbRotation from 3 explicit axes so text is consistently oriented.

    Axes defined as:
      local Z = face_normal           text faces outward (readable from outside)
      local Y = world-Z (or world-Y)  consistent "up" direction, projected onto
                projected onto face    the face plane via Gram-Schmidt
      local X = Y × Z                 character run direction (right-hand system)

    Using SbMatrix avoids the degenerate / antiparallel cases that occur when
    constructing SbRotation from a single (from, to) vector pair.

    Returns None if the rotation cannot be computed.
    """
    import math
    try:
        from pivy import coin

        nx, ny, nz = float(normal[0]), float(normal[1]), float(normal[2])
        length = math.sqrt(nx * nx + ny * ny + nz * nz)
        if length < 1e-9:
            return None

        # Z axis = face normal (normalised)
        zx, zy, zz = nx / length, ny / length, nz / length

        # Up hint: world Z unless normal is nearly parallel to ±Z
        if abs(zz) < 0.9:
            ux, uy, uz = 0.0, 0.0, 1.0   # world Z
        else:
            ux, uy, uz = 0.0, 1.0, 0.0   # world Y

        # Y axis: remove the Z component from up_hint (Gram-Schmidt)
        dot = ux * zx + uy * zy + uz * zz
        yx = ux - dot * zx
        yy = uy - dot * zy
        yz = uz - dot * zz
        ylen = math.sqrt(yx * yx + yy * yy + yz * yz)
        if ylen < 1e-9:
            return None
        yx, yy, yz = yx / ylen, yy / ylen, yz / ylen

        # X axis = Y × Z  (right-hand: X × Y = Z, so Y × Z = X)
        xx = yy * zz - yz * zy
        xy = yz * zx - yx * zz
        xz = yx * zy - yy * zx
        xlen = math.sqrt(xx * xx + xy * xy + xz * xz)
        if xlen < 1e-9:
            return None
        xx, xy, xz = xx / xlen, xy / xlen, xz / xlen

        # Build a row-major rotation matrix with characters running along the normal.
        # local X = face_normal  (character run direction = outward from face)
        # local Y = up_hint projected onto face plane (consistent "up")
        # local Z = -X_old = normal × Y  (text facing direction, right-hand: X_new × Y = Z_new)
        # Coin3D uses row vectors: v' = v * M, so M[row] = world coords of that local axis.
        mat = coin.SbMatrix(
            zx,  zy,  zz,  0.0,   # local X = face_normal
            yx,  yy,  yz,  0.0,   # local Y = "up" direction
            -xx, -xy, -xz, 0.0,   # local Z = normal × Y
            0.0, 0.0, 0.0, 1.0,
        )
        rot = coin.SbRotation()
        rot.setValue(mat)
        return rot
    except Exception:
        return None


def _build_separator(label_data_with_normals):
    """
    Build a root SoSeparator for all labels.

    Parameters
    ----------
    label_data_with_normals : list of (str, (x, y, z), normal_or_None)
        Each tuple is (label_text, world_position_mm, face_normal).
    """
    from pivy import coin

    root = coin.SoSeparator()

    # Shared material: bright yellow, self-illuminated so colour is
    # independent of scene lighting.
    mat = coin.SoMaterial()
    mat.diffuseColor.setValue(1.0, 1.0, 0.0)
    mat.emissiveColor.setValue(1.0, 1.0, 0.0)
    root.addChild(mat)

    font_size = max(1.0, _BASE_FONT_MM * _label_scale())

    for text, (x, y, z), normal in label_data_with_normals:
        sep = coin.SoSeparator()

        rot = _make_rotation(normal) if normal is not None else None

        if rot is not None:
            # -------------------------------------------------------
            # 3-D oriented label: lies flat on the face surface.
            # SoTransform handles both translation and rotation so the
            # text reads horizontally when viewed from outside the face.
            # -------------------------------------------------------
            transform = coin.SoTransform()
            transform.translation.setValue(coin.SbVec3f(float(x), float(y), float(z)))
            transform.rotation.setValue(rot)
            sep.addChild(transform)

            font = coin.SoFont()
            font.name.setValue("Arial:Bold")
            font.size.setValue(font_size)
            sep.addChild(font)

            lbl = coin.SoAsciiText()
            lbl.string.setValue(str(text))
            sep.addChild(lbl)
        else:
            # -------------------------------------------------------
            # Fallback: screen-space label, always faces the camera.
            # -------------------------------------------------------
            tr = coin.SoTranslation()
            tr.translation.setValue(coin.SbVec3f(float(x), float(y), float(z)))
            sep.addChild(tr)

            font = coin.SoFont()
            font.name.setValue("Arial:Bold")
            font.size.setValue(14.0)  # pixels for SoText2
            sep.addChild(font)

            lbl = coin.SoText2()
            lbl.string.setValue(str(text))
            sep.addChild(lbl)

        root.addChild(sep)

    return root


def _show_labels(key, label_data_with_normals):
    """
    Add (or replace) Coin3D labels in the active 3D view.

    Always removes stale labels for *key* before adding the new separator.
    """
    _remove_labels(key)
    if not label_data_with_normals:
        return

    try:
        from pivy import coin  # noqa: F401
    except ImportError:
        FreeCAD.Console.PrintWarning(
            "[ThermalAnalysis] pivy が利用できません。Coin3D ラベルを表示できません。\n"
        )
        return

    view = _active_view()
    if view is None:
        FreeCAD.Console.PrintWarning(
            "[ThermalAnalysis] アクティブな 3D ビューが見つかりません。\n"
        )
        return

    sep = _build_separator(label_data_with_normals)
    scene = view.getSceneGraph()
    scene.addChild(sep)
    _registry[key] = (scene, sep)


def _remove_labels(key):
    """Remove a previously added Coin3D separator from the scene graph."""
    entry = _registry.pop(key, None)
    if entry is None:
        return
    scene, sep = entry
    try:
        scene.removeChild(sep)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def show_face_labels(doc=None):
    """面番号ラベルを 3D ビューに表示する (Coin3D SoAsciiText)。

    ラベルは面の法線方向を向いており、面の外側から見ると横書きに読める。

    Parameters
    ----------
    doc : FreeCAD.Document, optional
        対象ドキュメント。省略時はアクティブドキュメントを使う。
    """
    if doc is None:
        doc = FreeCAD.ActiveDocument
    if doc is None:
        FreeCAD.Console.PrintWarning("[ThermalAnalysis] アクティブなドキュメントがありません。\n")
        return

    from orbitherm_studio.modeling import core
    raw = core.get_face_label_data(doc)
    if not raw:
        FreeCAD.Console.PrintWarning(
            "[ThermalAnalysis] 面ラベルデータがありません。先にモデルを準備してください。\n"
        )
        return

    _show_labels(_KEY_FACE, raw)


def clear_face_labels():
    """面番号ラベルを 3D ビューから削除する。"""
    _remove_labels(_KEY_FACE)


def show_node_labels(doc=None):
    """ノード番号ラベルを 3D ビューに表示する (Coin3D SoAsciiText)。

    Parameters
    ----------
    doc : FreeCAD.Document, optional
        対象ドキュメント。省略時はアクティブドキュメントを使う。
    """
    if doc is None:
        doc = FreeCAD.ActiveDocument
    if doc is None:
        FreeCAD.Console.PrintWarning("[ThermalAnalysis] アクティブなドキュメントがありません。\n")
        return

    from orbitherm_studio.modeling import core
    raw = core.get_node_label_data(doc)
    if not raw:
        FreeCAD.Console.PrintWarning(
            "[ThermalAnalysis] ノードラベルデータがありません。先にモデルを準備してください。\n"
        )
        return

    _show_labels(_KEY_NODE, raw)


def clear_node_labels():
    """ノード番号ラベルを 3D ビューから削除する。"""
    _remove_labels(_KEY_NODE)


def is_face_labels_visible():
    """面番号ラベルが現在表示中かどうかを返す。"""
    return _KEY_FACE in _registry


def is_node_labels_visible():
    """ノード番号ラベルが現在表示中かどうかを返す。"""
    return _KEY_NODE in _registry
