# -*- coding: utf-8 -*-
# InitGui.py (バージョン 5.2)
"""
Orbitherm Studio — FreeCAD entry point.

FreeCAD-based thermal modeling workbench for spacecraft and engineering systems.
Public brand name  : Orbitherm Studio
Workbench selector : Orbitherm
Internal package   : ThermalAnalysis (gradual migration to orbitherm_studio planned)

Note:
- Canonical command definitions live in ThermalAnalysis.gui.commands
- Some local class definitions remain temporarily for compatibility
- Registration is currently finalized via imported command definitions
"""

import os
import sys

# FreeCAD が Mod\orbitherm-studio をカレントにしている場合、
# 親の Mod を path に追加して "orbitherm_studio" パッケージを import 可能にする
try:
    _this_dir = os.path.dirname(os.path.abspath(__file__))
    _mod_dir = os.path.dirname(_this_dir)
except NameError:
    # __file__ が未定義のとき（FreeCAD の実行コンテキストによる）
    import FreeCAD
    _mod_dir = os.path.join(FreeCAD.getUserAppDataDir(), "Mod")
    _this_dir = os.path.join(_mod_dir, "orbitherm-studio")
if _mod_dir not in sys.path:
    sys.path.insert(0, _mod_dir)

# フォルダ名が orbitherm-studio（ハイフン）の場合、Python は orbitherm_studio パッケージを
# 自動検出できないため、sys.modules に手動登録する
if "orbitherm_studio" not in sys.modules:
    import importlib.util as _ilu
    _init_file = os.path.join(_this_dir, "__init__.py")
    if os.path.isfile(_init_file):
        _spec = _ilu.spec_from_file_location(
            "orbitherm_studio",
            _init_file,
            submodule_search_locations=[_this_dir],
        )
        _pkg = _ilu.module_from_spec(_spec)
        _pkg.__path__ = [_this_dir]
        _pkg.__package__ = "orbitherm_studio"
        sys.modules["orbitherm_studio"] = _pkg
        _spec.loader.exec_module(_pkg)
        del _init_file, _spec, _pkg
    del _ilu

import time
import FreeCAD
import FreeCADGui
from PySide import QtCore, QtGui, QtWidgets

# from orbitherm_studio.modeling.gui_panels import EditPropertiesTaskPanel, MaterialEditorDialog


def _is_radiation_analysis_tree_object(obj):
    """面・ノード・輻射モデル用オブジェクトかどうか（ツリー右クリックメニュー用）。"""
    if obj is None:
        return False
    name = getattr(obj, "Name", "") or ""
    if name.startswith("FaceGroup_"):
        return True
    if name.startswith("FaceSurfaces_"):
        return True
    if name.startswith("Face_") and ("_front" in name or "_back" in name):
        return True
    if name.startswith("Node_"):
        return True
    label = getattr(obj, "Label", "") or ""
    if label.endswith("輻射モデル"):
        return True
    return False


def _get_object_from_tree_index(tree, pos):
    """ツリーの pos（ビューポート座標）にあるインデックスから DocumentObject を取得。取れなければ None。"""
    from PySide import QtCore
    if tree is None:
        return None
    index = tree.indexAt(pos)
    if not index.isValid():
        return None
    model = tree.model()
    if model is None:
        return None
    # FreeCAD のツリーモデルは UserRole や objectFromIndex / internalPointer でオブジェクトを保持することがある
    obj = model.data(index, QtCore.Qt.UserRole)
    if obj is not None and hasattr(obj, "Name"):
        return obj
    if hasattr(model, "objectFromIndex"):
        obj = model.objectFromIndex(index)
        if obj is not None:
            return obj
    if hasattr(index, "internalPointer"):
        obj = index.internalPointer()
        if obj is not None and hasattr(obj, "Name"):
            return obj
    return None


class _TreeContextMenuFilter(QtCore.QObject):
    """面・ノードの右クリック時は輻射解析用メニューのみ表示しデフォルトメニューを出さない。ダブルクリックでプロパティパネルを開く。"""

    @staticmethod
    def _is_radiation_analysis_tree_object(obj):
        """面・ノード・輻射モデル用オブジェクトかどうか（ツリー右クリックメニュー用）。クラス内定義で初期化時の NameError を防ぐ。"""
        if obj is None:
            return False
        name = getattr(obj, "Name", "") or ""
        if name.startswith("FaceGroup_"):
            return True
        if name.startswith("FaceSurfaces_"):
            return True
        if name.startswith("Face_") and ("_front" in name or "_back" in name):
            return True
        if name.startswith("Node_"):
            return True
        label = getattr(obj, "Label", "") or ""
        if label.endswith("輻射モデル"):
            return True
        return False

    def __init__(self, workbench, tree_view):
        super().__init__()  # クラス名を書かないことで、コールバック時スコープに _TreeContextMenuFilter が無くても動作
        self._workbench = workbench
        self._tree_view = tree_view
        self._command_names = [
            "ThermalAnalysis_Modeling_EditProperties",
            "ThermalAnalysis_Modeling_BulkSetProperties",
            "ThermalAnalysis_Modeling_SubdivideSurface",
            "ThermalAnalysis_Modeling_DisplayOptions",
            "ThermalAnalysis_Modeling_VisualizeActiveSide",
            "ThermalAnalysis_Modeling_VisualizeAbsorptivity",
            "ThermalAnalysis_Modeling_VisualizeEmissivity",
            "ThermalAnalysis_Modeling_VisualizeTransmittance",
            "ThermalAnalysis_Modeling_RestoreDefaultDisplay",
            "ThermalAnalysis_Post_PostProcessing",
        ]

    def _get_object_from_tree_index_local(self, tree, pos):
        """ツリーの pos から DocumentObject を取得（グローバル関数未定義時のフォールバックも兼ねる）。"""
        try:
            # まずはグローバルの実装があればそれを使う
            if "_get_object_from_tree_index" in globals():
                return _get_object_from_tree_index(tree, pos)
        except Exception:
            pass
        # フォールバック実装
        if tree is None:
            return None
        index = tree.indexAt(pos)
        if not index.isValid():
            return None
        model = tree.model()
        if model is None:
            return None
        obj = None
        if hasattr(model, "objectFromIndex"):
            try:
                obj = model.objectFromIndex(index)
            except Exception:
                obj = None
        if obj is None and hasattr(index, "internalPointer"):
            ptr = index.internalPointer()
            if ptr is not None and hasattr(ptr, "Name"):
                obj = ptr
        return obj if obj is not None and hasattr(obj, "Name") else None

    def _target_objects_for_position(self, tree, position):
        """ツリー上の position（ビューポート座標）から輻射解析対象オブジェクトのリストを返す。"""
        is_ra = self._is_radiation_analysis_tree_object
        target = self._get_object_from_tree_index_local(tree, position)
        if target is not None and is_ra(target):
            return [target]
        sel = FreeCADGui.Selection.getSelection()
        if sel and all(is_ra(o) for o in sel):
            return sel
        return []

    def _target_objects_for_event(self, obj, event):
        """イベント発生位置から輻射解析対象オブジェクトのリストを返す。"""
        tree = self._tree_view
        pos = event.pos()
        if obj != tree and hasattr(obj, "parent") and obj.parent() == tree:
            pos = obj.mapTo(tree, pos)
        return self._target_objects_for_position(tree, pos)

    def eventFilter(self, obj, event):
        from PySide import QtCore  # コールバック時スコープで QtCore が未定義になる問題への対処
        t = event.type()
        if t == QtCore.QEvent.ContextMenu:
            targets = self._target_objects_for_event(obj, event)
            if not targets:
                return False
            # デフォルトのコンテキストメニューを出さないためイベントを消費し、輻射解析用メニューのみ表示
            menu = QtGui.QMenu()
            for cmd_name in self._command_names:
                cmd = FreeCADGui.getCommand(cmd_name)
                if cmd and getattr(cmd, "IsActive", lambda: False)():
                    action = menu.addAction(getattr(cmd, "GetResources", lambda: {})().get("MenuText", cmd_name))
                    action.triggered.connect(lambda c=cmd: c.Activated())
            if menu.isEmpty():
                return True
            # メニュー表示前に選択をクリック位置のオブジェクトに合わせる
            doc = FreeCAD.ActiveDocument
            if doc and targets:
                FreeCADGui.Selection.clearSelection()
                for o in targets:
                    FreeCADGui.Selection.addSelection(doc, o.Name)
            menu.exec_(QtGui.QCursor.pos())
            return True

        if t == QtCore.QEvent.MouseButtonDblClick and event.button() == QtCore.Qt.LeftButton:
            targets = self._target_objects_for_event(obj, event)
            if not targets:
                return False
            o = targets[0]
            name = getattr(o, "Name", "") or ""
            # サーフェス（Face_*_front/back）またはノード（Node_*）のときプロパティパネルを開く
            is_face = name.startswith("Face_") and ("_front" in name or "_back" in name)
            is_node = name.startswith("Node_")
            if not (is_face or is_node):
                return False
            doc = FreeCAD.ActiveDocument
            if doc:
                FreeCADGui.Selection.clearSelection()
                FreeCADGui.Selection.addSelection(doc, o.Name)
                from orbitherm_studio.gui.panels import EditPropertiesTaskPanel
                panel = EditPropertiesTaskPanel()
                FreeCADGui.Control.showDialog(panel)
            return True

        return False


def _find_tree_view():
    # コールバックが別スコープで実行されると QtGui が未定義になるため、関数内でインポート
    from PySide import QtGui
    mw = FreeCADGui.getMainWindow()
    if mw is None:
        return None
    for w in mw.findChildren(QtGui.QTreeView):
        if w.objectName() in ("treeView", "TreeView", "") or "tree" in w.objectName().lower():
            return w
    return mw.findChild(QtGui.QTreeView)


# #region agent log helper
def _agent_debug_log(hypothesis_id, location, message, data=None, run_id="initial"):
    """
    Debug モード用の簡易ロガー。debug-db71c7.log に NDJSON を 1 行追記する。
    """
    try:
        import json, time, os
        payload = {
            "sessionId": "db71c7",
            "id": f"log_{int(time.time() * 1000)}",
            "timestamp": int(time.time() * 1000),
            "location": location,
            "message": message,
            "data": data or {},
            "runId": run_id,
            "hypothesisId": hypothesis_id,
        }
        # FreeCAD の実行コンテキストによって __file__ が未定義/変化することがあるため、
        # UserAppDataDir を優先して安定した場所に書き込む。
        try:
            import FreeCAD
            base_dir = os.path.join(FreeCAD.getUserAppDataDir(), "Mod", "orbitherm_studio")
        except Exception:
            base_dir = os.path.dirname(__file__) if "__file__" in globals() else os.getcwd()
        log_path = os.path.join(base_dir, "debug-db71c7.log")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        # ログで本処理を壊さない
        pass
# #endregion


# ===================================================================================
# === コマンドクラスの定義（gui/commands.py に移動済み）
# 以下のローカル定義は後方互換のために残してあるが、
# 登録処理直前の import * によって gui/commands.py の定義に上書きされる。
# ===================================================================================

# --- コマンド1: モデル準備 ---
class ThermalAnalysis_Modeling_PrepareModel:
    @staticmethod
    def _get_path():
        for p in sys.path:
            if os.path.basename(p) in ("orbitherm-studio", "orbitherm_studio", "ThermalAnalysis"): return p
        return os.path.join(FreeCAD.getUserAppDataDir(), "Mod", "orbitherm-studio")
    def GetResources(self):
        workbench_path = self._get_path()
        icon_path = os.path.join(workbench_path, "Resources", "icons", "RadiationAnalysis_PrepareModel_Icon.svg")
        return {
            'Pixmap': icon_path,
            'MenuText': "モデルを準備",
            'ToolTip': "面ごとのメッシュと、面の中心ノードを作成します。オブジェクトのみ選択で全面変換。面をサブ選択すると選択した面のみ変換。サーフェースのみのオブジェクト（Shell等）も選択可能。",
        }
    def Activated(self):
        # #region agent log
        log_fn = globals().get("_agent_debug_log", None)
        if callable(log_fn):
            log_fn(
                hypothesis_id="H1",
                location="InitGui.py:ThermalAnalysis_Modeling_PrepareModel.Activated",
                message="PrepareModel Activated entry",
                data={
                    "sel_len": (len(FreeCADGui.Selection.getSelectionEx()) if hasattr(FreeCADGui, "Selection") else None),
                    "sel_names": [getattr(getattr(s, "Object", None), "Name", None) for s in (FreeCADGui.Selection.getSelectionEx() if hasattr(FreeCADGui, "Selection") else [])][:5],
                },
                run_id="initial",
            )
        # #endregion
        from orbitherm_studio.gui.panels import PrepareModelDialog
        from orbitherm_studio.modeling import core
        dlg = PrepareModelDialog()
        if not dlg.exec_():
            return
        linear_deflection, angular_deflection, one_node_per_solid = dlg.get_values()
        # 将来的な拡張に備えてキーワード引数で呼び出す
        core.run_prepare_model(
            linear_deflection=linear_deflection,
            angular_deflection=angular_deflection,
            one_node_per_solid=one_node_per_solid,
        )

    def IsActive(self):
        """
        以前は「SelectionEx に有効な Object があるときのみ True」にしていたが、
        選択状態に依存しすぎてコマンドが再実行できないケースが多かったため、
        現在は「アクティブなドキュメントがあれば常に True」とする。
        実際の対象オブジェクトの妥当性チェックは Activated 側の処理に任せる。
        """
        ok = FreeCAD.ActiveDocument is not None
        # #region agent log
        log_fn = globals().get("_agent_debug_log", None)
        if callable(log_fn):
            try:
                sel_ex = FreeCADGui.Selection.getSelectionEx()
                first_obj = getattr(getattr(sel_ex[0], "Object", None), "Name", None) if sel_ex else None
                sel_len = len(sel_ex) if sel_ex is not None else None
            except Exception:
                first_obj = None
                sel_len = None
            log_fn(
                hypothesis_id="H4",
                location="InitGui.py:ThermalAnalysis_Modeling_PrepareModel.IsActive",
                message="PrepareModel IsActive evaluated (doc-based)",
                data={
                    "ok": ok,
                    "sel_len": sel_len,
                    "first_obj": first_obj,
                },
                run_id="initial",
            )
        # #endregion
        return ok


# --- コマンド1b: 形状の簡略化（穴・フィレット削除）---
class ThermalAnalysis_Modeling_Defeaturing:
    @staticmethod
    def _get_path():
        for p in sys.path:
            if os.path.basename(p) in ("orbitherm-studio", "orbitherm_studio", "ThermalAnalysis"):
                return p
        return os.path.join(FreeCAD.getUserAppDataDir(), "Mod", "orbitherm-studio")

    def GetResources(self):
        workbench_path = self._get_path()
        icon_path = os.path.join(workbench_path, "Resources", "icons", "RadiationAnalysis_PrepareModel_Icon.svg")
        return {
            "Pixmap": icon_path,
            "MenuText": "形状の簡略化（穴・フィレット削除）",
            "ToolTip": "選択した Part から、指定した直径以下の穴と R 以下のフィレットを削除した新しい形状を作成します。解析用の単純化に利用できます。",
        }

    def Activated(self):
        from orbitherm_studio.gui.panels import DefeaturingDialog
        from orbitherm_studio.modeling import defeaturing
        dlg = DefeaturingDialog()
        if not dlg.exec_():
            return
        hole_max_diameter_mm, fillet_max_radius_mm = dlg.get_values()
        defeaturing.run_defeaturing(
            hole_max_diameter_mm=hole_max_diameter_mm,
            fillet_max_radius_mm=fillet_max_radius_mm,
        )

    def IsActive(self):
        try:
            sel = FreeCADGui.Selection.getSelectionEx()
            if not sel or len(sel) != 1:
                return False
            obj = getattr(sel[0], "Object", None)
            if obj is None:
                return False
            shape = getattr(obj, "Shape", None)
            return shape is not None and getattr(shape, "Faces", None) is not None
        except Exception:
            return False


# --- コマンド1c: 形状の簡略化（選択した面のみ）---
class ThermalAnalysis_Modeling_DefeaturingSelected:
    @staticmethod
    def _get_path():
        for p in sys.path:
            if os.path.basename(p) in ("orbitherm-studio", "orbitherm_studio", "ThermalAnalysis"):
                return p
        return os.path.join(FreeCAD.getUserAppDataDir(), "Mod", "orbitherm-studio")

    def GetResources(self):
        workbench_path = self._get_path()
        icon_path = os.path.join(workbench_path, "Resources", "icons", "RadiationAnalysis_PrepareModel_Icon.svg")
        return {
            "Pixmap": icon_path,
            "MenuText": "形状の簡略化（選択した面のみ）",
            "ToolTip": "オブジェクトを選択したうえで、削除したい面を Ctrl+クリックでサブ選択してから実行します。選択した面だけを Defeaturing で削除した新しい形状を作成します。",
        }

    def Activated(self):
        from orbitherm_studio.modeling import defeaturing
        defeaturing.run_defeaturing_selected_faces()

    def IsActive(self):
        try:
            sel = FreeCADGui.Selection.getSelectionEx()
            if not sel or len(sel) != 1:
                return False
            obj = getattr(sel[0], "Object", None)
            if obj is None:
                return False
            sub = getattr(sel[0], "SubElementNames", []) or []
            has_face = any(isinstance(n, str) and n.startswith("Face") for n in sub)
            if not has_face:
                return False
            shape = getattr(obj, "Shape", None)
            return shape is not None and getattr(shape, "Faces", None) is not None
        except Exception:
            return False


# --- コマンド2: プロパティ編集 ---
class ThermalAnalysis_Modeling_EditProperties:
    def GetResources(self):
        return {
            "MenuText": "プロパティ編集",
            "ToolTip": "選択したオブジェクトのプロパティを編集します。",
        }

    def Activated(self):
        from orbitherm_studio.gui.panels import EditPropertiesTaskPanel
        self.panel = EditPropertiesTaskPanel()
        FreeCADGui.Control.showDialog(self.panel)
    def IsActive(self):
        selection = FreeCADGui.Selection.getSelection()
        if not selection: return False
        return all(sel.isDerivedFrom("Mesh::Feature") and "Face_" in sel.Name for sel in selection)


# --- コマンド2b: 面の一括プロパティ設定 ---
class ThermalAnalysis_Modeling_BulkSetProperties:
    def GetResources(self):
        return {
            "MenuText": "面の一括プロパティ設定",
            "ToolTip": "輻射モデル内の全面に同じ熱物性・光学特性を一括で設定します。",
        }

    def Activated(self):
        from orbitherm_studio.gui.panels import BulkPropertiesDialog
        dlg = BulkPropertiesDialog()
        dlg.exec_()

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None


# --- コマンド3: マテリアル編集 ---
class ThermalAnalysis_Modeling_ManageMaterials:
    def GetResources(self):
        return {
            "MenuText": "マテリアル編集",
            "ToolTip": "マテリアルライブラリを編集します。",
        }

    def Activated(self):
        from orbitherm_studio.gui.panels import MaterialEditorDialog
        self.dialog = MaterialEditorDialog()
        self.dialog.exec_()

    def IsActive(self):
        return True


# (以降のコマンドとワークベンチ定義は変更なし)
# --- コマンド4,5,6 (可視化) ---
class ThermalAnalysis_Modeling_VisualizeActiveSide:
    def GetResources(self): return {'MenuText': "アクティブ面 表示", 'ToolTip': "アクティブ面の設定に応じて色分け表示します。"}
    def Activated(self): from orbitherm_studio.modeling import core; core.visualize_active_side()
    def IsActive(self): return FreeCAD.ActiveDocument is not None
class ThermalAnalysis_Modeling_VisualizeAbsorptivity:
    def GetResources(self): return {'MenuText': "吸収率 表示", 'ToolTip': "太陽光吸収率をコンター表示します。"}
    def Activated(self): from orbitherm_studio.modeling import core; core.visualize_property_contour("SolarAbsorptivity", "太陽光吸収率")
    def IsActive(self): return FreeCAD.ActiveDocument is not None
class ThermalAnalysis_Modeling_VisualizeEmissivity:
    def GetResources(self): return {'MenuText': "放射率 表示", 'ToolTip': "赤外放射率をコンター表示します。"}
    def Activated(self): from orbitherm_studio.modeling import core; core.visualize_property_contour("InfraredEmissivity", "赤外放射率")
    def IsActive(self): return FreeCAD.ActiveDocument is not None
class ThermalAnalysis_Modeling_VisualizeTransmittance:
    def GetResources(self): return {'MenuText': "透過率 表示", 'ToolTip': "透過率をコンター表示します。"}
    def Activated(self): from orbitherm_studio.modeling import core; core.visualize_property_contour("Transmittance", "透過率")
    def IsActive(self): return FreeCAD.ActiveDocument is not None
class ThermalAnalysis_Modeling_RestoreDefaultDisplay:
    def GetResources(self):
        return {
            'MenuText': "表示をデフォルトに戻す",
            'ToolTip': "アクティブ面・吸収率・放射率・透過率の色分けをやめ、全面をデフォルト色に戻します。",
        }
    def Activated(self):
        from orbitherm_studio.modeling import core
        core.restore_default_display()
    def IsActive(self):
        return FreeCAD.ActiveDocument is not None
# --- 表示設定 ---
class ThermalAnalysis_Modeling_DisplayOptions:
    def GetResources(self):
        return {
            "MenuText": "表示設定",
            "ToolTip": "表示モード（アクティブ面・吸収率・放射率・透過率・デフォルト）を排他的に選ぶダイアログを開きます。",
        }

    def Activated(self):
        from orbitherm_studio.gui.panels import DisplayOptionsDialog
        dlg = DisplayOptionsDialog()
        dlg.exec_()

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None


# --- 表示・伝導パラメータ設定 ---
class ThermalAnalysis_DisplayParametersSettings:
    def GetResources(self):
        return {
            "MenuText": "表示・伝導パラメータ設定",
            "ToolTip": "ノード表示・コンダクタンス線・伝導コンダクタンスのペア選定パラメータを設定します。",
        }

    def Activated(self):
        from orbitherm_studio.gui.panels import DisplayParametersSettingsDialog
        dlg = DisplayParametersSettingsDialog()
        dlg.exec_()

    def IsActive(self):
        return True


# --- コマンド7: 熱容量計算 ---
class ThermalAnalysis_Modeling_CalculateThermalMass:
    def GetResources(self): return {'MenuText': "熱容量計算", 'ToolTip': "設定された物性値から各ノードの熱容量を計算します。"}
    def Activated(self): from orbitherm_studio.modeling import core; core.calculate_thermal_mass()
    def IsActive(self): return FreeCAD.ActiveDocument is not None
# --- コマンド8: 伝熱コンダクタンス計算 ---
class ThermalAnalysis_Modeling_CalculateConductance:
    def GetResources(self): return {'MenuText': "伝熱コンダクタンス計算", 'ToolTip': "隣接するメッシュ間の伝熱コンダクタンスを計算します。"}
    def Activated(self): from orbitherm_studio.modeling import core; core.calculate_conductance()
    def IsActive(self): return FreeCAD.ActiveDocument is not None
# --- コマンド8b: 輻射コンダクタンス計算 ---
class ThermalAnalysis_Modeling_CalculateRadiationConductance:
    def GetResources(self):
        return {
            "MenuText": "輻射コンダクタンス計算",
            "ToolTip": "レイトレーシングでビューファクターを計算し、輻射コンダクタンス係数 R'=ε×Vf×A を計算します。空間への輻射は SPACE.9999 ノードとして出力します。",
        }
    def Activated(self):
        from orbitherm_studio.modeling import core
        from orbitherm_studio.gui.panels import RadiationParamsDialog
        dlg = RadiationParamsDialog()
        if not dlg.exec_():
            return
        rays = dlg.get_rays_per_patch()
        core.calculate_radiation_conductance(rays_per_patch=rays)
    def IsActive(self):
        return FreeCAD.ActiveDocument is not None


class ThermalAnalysis_Modeling_AddConductance:
    def GetResources(self):
        return {
            "MenuText": "伝熱コンダクタンスを追加",
            "ToolTip": "選択した2ノード間に手動で伝熱コンダクタンスリンクを追加します。",
        }

    def Activated(self):
        from orbitherm_studio.modeling import core
        from PySide import QtGui
        sel = FreeCADGui.Selection.getSelection()
        if len(sel) != 2:
            QtGui.QMessageBox.warning(None, "伝熱コンダクタンスを追加", "2つのノード（またはノードを含むオブジェクト）を選択してください。")
            return
        def _resolve_node(obj):
            if getattr(obj, "Name", "").startswith("Node_"):
                return obj
            if hasattr(obj, "Group"):
                for o in obj.Group:
                    if getattr(o, "Name", "").startswith("Node_"):
                        return o
            return None
        node1 = _resolve_node(sel[0])
        node2 = _resolve_node(sel[1])
        if node1 is None or node2 is None:
            QtGui.QMessageBox.warning(None, "伝熱コンダクタンスを追加", "選択からノードを特定できませんでした。Node_* を含むオブジェクトを選択してください。")
            return
        dialog = QtGui.QInputDialog()
        dialog.setInputMode(QtGui.QInputDialog.DoubleInput)
        dialog.setLabelText("伝熱コンダクタンス [W/K]:")
        dialog.setDoubleDecimals(6)
        dialog.setDoubleMinimum(-1e12)
        dialog.setDoubleMaximum(1e12)
        dialog.setDoubleValue(1.0)
        dialog.setWindowTitle("伝熱コンダクタンスを追加")
        if not dialog.exec_():
            return
        value = dialog.doubleValue()
        try:
            core.add_manual_conductance(node1, node2, value)
        except Exception as e:
            QtGui.QMessageBox.critical(None, "伝熱コンダクタンスを追加", str(e))

    def IsActive(self):
        sel = FreeCADGui.Selection.getSelection()
        return len(sel) == 2
# --- Thermal Model Export（ノード・伝熱・輻射コンダクタンスを .inp で一括出力） ---
class ThermalAnalysis_Modeling_ThermalModelExport:
    def GetResources(self):
        return {
            "MenuText": "Thermal Model Export",
            "ToolTip": "HEADER OPTIONS/CONTROL を設定し、ノード・伝熱・輻射コンダクタンスを熱解析ソルバー用 .inp で出力します。",
        }

    def Activated(self):
        import FreeCAD
        from orbitherm_studio.modeling import core
        from orbitherm_studio.gui.panels import ThermalModelExportDialog
        try:
            from PySide2 import QtWidgets
        except ImportError:
            from PySide import QtGui as QtWidgets
        doc = FreeCAD.ActiveDocument
        if not doc:
            QtWidgets.QMessageBox.warning(None, "Thermal Model Export", "アクティブなドキュメントがありません。")
            return
        dlg = ThermalModelExportDialog()
        if not dlg.exec_():
            return
        from orbitherm_studio.modeling.freecad_utils import get_default_export_dir
        _dir = get_default_export_dir()
        _start = os.path.join(_dir, "thermal_model.inp") if _dir else "thermal_model.inp"
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            None, "Thermal Model Export", _start,
            "INP (*.inp);;All (*)"
        )
        if not path:
            return
        try:
            core.export_thermal_model_inp(
                path,
                options_data=dlg.get_options_data(),
                control_data=dlg.get_control_data(),
                default_initial_temperature=dlg.get_initial_temperature(),
            )
            QtWidgets.QMessageBox.information(None, "Thermal Model Export", "保存しました:\n" + path)
        except Exception as e:
            QtWidgets.QMessageBox.critical(None, "Thermal Model Export", str(e))

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None


# --- サーフェース分割 ---
class ThermalAnalysis_Modeling_SubdivideSurface:
    def GetResources(self):
        return {'MenuText': "サーフェースを分割", 'ToolTip': "選択したFaceGroupのメッシュをグリッドで分割し、サブサーフェースとノードを作成します。"}
    def Activated(self):
        from orbitherm_studio.gui.panels import SubdivideSurfaceDialog
        from orbitherm_studio.modeling import core
        dlg = SubdivideSurfaceDialog()
        if not dlg.exec_():
            return
        nu, nv, merge, surf_start = dlg.get_values()
        core.run_subdivide_surface(nu=nu, nv=nv, merge_subs_into_one_node=merge, surface_number_start=surf_start)
    def IsActive(self):
        sel = FreeCADGui.Selection.getSelection()
        if not sel:
            return False
        doc = FreeCAD.ActiveDocument
        if not doc:
            return False
        for s in sel:
            if s.isDerivedFrom("App::DocumentObjectGroup") and s.Name.startswith("FaceGroup_"):
                return True
            if s.isDerivedFrom("Mesh::Feature") and "Face_" in s.Name:
                for o in doc.Objects:
                    if not hasattr(o, "Group") or s not in o.Group:
                        continue
                    if o.Name.startswith("FaceGroup_"):
                        return True
                    for o2 in doc.Objects:
                        if hasattr(o2, "Group") and o in o2.Group and o2.Name.startswith("FaceGroup_"):
                            return True
        return False


# --- Post Processing（温度結果コンター表示）: ポストメニューに表示 ---
class ThermalAnalysis_Post_PostProcessing:
    def GetResources(self):
        return {
            "MenuText": "Post Processing",
            "ToolTip": "熱解析 .out を読み込み、ノード温度をコンター表示します。過渡解析の複数時刻の切替と温度表示範囲の指定が可能です。",
        }

    def Activated(self):
        try:
            from PySide2 import QtWidgets
        except ImportError:
            from PySide import QtGui as QtWidgets
        from orbitherm_studio.gui.panels import PostProcessingDialog
        doc = FreeCAD.ActiveDocument
        if not doc:
            QtWidgets.QMessageBox.warning(None, "Post Processing", "アクティブなドキュメントがありません。")
            return
        dlg = PostProcessingDialog()
        dlg.exec_()

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None


# ===================================================================================
# === 軌道熱コマンド (ThermalAnalysis_Orbit_*)
# ===================================================================================

class ThermalAnalysis_Orbit_CalcHeatAndVisualize:
    """軌道設定・熱入力計算・軌道描画を行う。CSV 保存は行わない（最後に「熱入力 CSV を保存」で保存）。"""

    def GetResources(self):
        return {
            "MenuText": "軌道計算と描画",
            "ToolTip": "軌道・環境を設定し、熱入力を計算して軌道を描画します。確認後「熱入力 CSV を保存」で保存できます。",
        }

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        from PySide import QtGui
        from orbitherm_studio.gui.orbit_gui import OrbitEnvironmentDialog
        from orbitherm_studio.orbit_heat import orbit_core, orbit_visualization
        doc = FreeCAD.ActiveDocument
        if not doc:
            QtGui.QMessageBox.warning(
                None, "Orbitherm Studio", "アクティブなドキュメントがありません。"
            )
            return

        dlg = OrbitEnvironmentDialog()
        if dlg.exec_() != QtGui.QDialog.Accepted:
            return
        params = dlg.get_parameters()

        try:
            orbit_input, env_params = orbit_core.normalize_inputs(params)
            times = orbit_core.build_time_grid(orbit_input)
            times = orbit_core.refine_with_eclipse_events(orbit_input, times)
            heat_array, meta = orbit_core.compute_heat_array(orbit_input, env_params, times)
        except Exception as e:
            QtGui.QMessageBox.critical(None, "ThermalAnalysis 計算エラー", str(e))
            return

        orbit_core.set_last_heat_data(times, heat_array, meta)

        attitude_mode = params.get("attitude_mode", "nadir")
        orbit_display_scale = params.get("orbit_display_scale", 1.0)
        shadow_length_km = params.get("shadow_length_km", 50000.0)
        try:
            orbit_visualization.create_orbit_scene(
                orbit_input, times,
                attitude_mode=attitude_mode,
                heat_array=heat_array,
                orbit_display_scale=orbit_display_scale,
                shadow_length_km=shadow_length_km,
            )
        except Exception as e:
            QtGui.QMessageBox.warning(
                None, "ThermalAnalysis 可視化エラー",
                "可視化の作成中にエラーが発生しました:\n{}".format(e),
            )
            return

        QtGui.QMessageBox.information(
            None, "Orbitherm Studio",
            "軌道を描画しました。\n確認後、メニュー「熱入力 CSV を保存」で CSV を保存できます。",
        )


class ThermalAnalysis_Orbit_SaveHeatArrayCSV:
    def GetResources(self):
        return {
            "MenuText": "熱入力 CSV を保存",
            "ToolTip": "「軌道計算と描画」で計算した熱入力データを CSV ファイルに保存します。",
        }

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        from PySide import QtGui
        from orbitherm_studio.orbit_heat import orbit_core

        data = orbit_core.get_last_heat_data()
        if not data:
            QtGui.QMessageBox.information(
                None, "Orbitherm Studio",
                "保存するデータがありません。\n先に「軌道計算と描画」を実行してください。",
            )
            return
        times, heat_array, meta = data
        from orbitherm_studio.modeling.freecad_utils import get_default_export_dir
        _dir = get_default_export_dir()
        _start = os.path.join(_dir, "heat_array.csv") if _dir else "heat_array.csv"
        path, _ = QtGui.QFileDialog.getSaveFileName(
            None, "熱入力 CSV の保存先を選択", _start,
            "CSV Files (*.csv);;All Files (*)",
        )
        if not path:
            return
        try:
            orbit_core.export_heat_array_csv(path, times, heat_array, meta)
            QtGui.QMessageBox.information(None, "Orbitherm Studio", "保存しました:\n{}".format(path))
        except Exception as e:
            QtGui.QMessageBox.critical(None, "ThermalAnalysis CSV 出力エラー", str(e))


class ThermalAnalysis_Orbit_ExportHeatArrayOnly:
    def GetResources(self):
        return {
            "MenuText": "計算して CSV 保存",
            "ToolTip": "軌道・環境を設定し、熱入力を計算して CSV のみ保存します（軌道は描画しません）。",
        }

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        from PySide import QtGui
        from orbitherm_studio.gui.orbit_gui import OrbitEnvironmentDialog
        from orbitherm_studio.orbit_heat import orbit_core

        dlg = OrbitEnvironmentDialog()
        if dlg.exec_() != QtGui.QDialog.Accepted:
            return
        params = dlg.get_parameters()
        try:
            orbit_input, env_params = orbit_core.normalize_inputs(params)
            times = orbit_core.build_time_grid(orbit_input)
            times = orbit_core.refine_with_eclipse_events(orbit_input, times)
            heat_array, meta = orbit_core.compute_heat_array(orbit_input, env_params, times)
        except Exception as e:
            QtGui.QMessageBox.critical(None, "ThermalAnalysis 計算エラー", str(e))
            return
        from orbitherm_studio.modeling.freecad_utils import get_default_export_dir
        _dir = get_default_export_dir()
        _start = os.path.join(_dir, "heat_array.csv") if _dir else "heat_array.csv"
        path, _ = QtGui.QFileDialog.getSaveFileName(
            None, "熱入力 CSV の保存先を選択", _start,
            "CSV Files (*.csv);;All Files (*)",
        )
        if not path:
            return
        try:
            orbit_core.export_heat_array_csv(path, times, heat_array, meta)
            QtGui.QMessageBox.information(None, "Orbitherm Studio", "保存しました:\n{}".format(path))
        except Exception as e:
            QtGui.QMessageBox.critical(None, "ThermalAnalysis CSV 出力エラー", str(e))


class ThermalAnalysis_Orbit_ClearVisualization:
    def GetResources(self):
        return {
            "MenuText": "Clear Orbit Visualization",
            "ToolTip": "Remove OrbitVisualization group and its objects from the document.",
        }

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        from PySide import QtGui
        doc = FreeCAD.ActiveDocument
        if not doc:
            return
        group = doc.getObject("OrbitVisualization")
        if not group:
            QtGui.QMessageBox.information(None, "Orbitherm Studio", "OrbitVisualization グループが見つかりません。")
            return
        for obj in list(getattr(group, "Group", []) or []):
            try:
                doc.removeObject(obj.Name)
            except Exception:
                pass
        try:
            doc.removeObject(group.Name)
        except Exception:
            pass
        doc.recompute()
        QtGui.QMessageBox.information(None, "Orbitherm Studio", "OrbitVisualization をクリアしました。")


class ThermalAnalysis_Orbit_StepOrbitFrames:
    def GetResources(self):
        return {
            "MenuText": "軌道コマ送り",
            "ToolTip": "各計算点での衛星の位置・向きをコマ送りで確認します。",
        }

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        from orbitherm_studio.gui.orbit_step_dialog import OrbitStepDialog
        dlg = OrbitStepDialog()
        dlg.exec_()


class ThermalAnalysis_Orbit_ApplyOrbitHeatToRadiation:
    def GetResources(self):
        return {
            "MenuText": "輻射モデルに軌道熱を適用",
            "ToolTip": "最後に計算した軌道・熱環境で面ごと熱入力を計算し、輻射モデルのノードの HeatSource に軌道平均を書き込みます。",
        }

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        from PySide import QtGui
        from orbitherm_studio.orbit_heat import orbit_core, orbit_radiation
        from orbitherm_studio.bridge import orbit_heat_bridge as bridge

        state = orbit_core.get_last_orbit_state()
        if not state:
            QtGui.QMessageBox.information(
                None, "Orbitherm Studio",
                "軌道データがありません。先に「軌道計算と描画」を実行してください。",
            )
            return
        times, _, attitude_mode, orbit_input, heat_array = state
        if heat_array is None or len(times) == 0:
            QtGui.QMessageBox.warning(None, "Orbitherm Studio", "熱入力データがありません。")
            return
        doc = FreeCAD.ActiveDocument
        if not doc:
            return
        try:
            surfaces = bridge.get_surfaces_for_orbit_heat(doc)
        except Exception as e:
            QtGui.QMessageBox.critical(
                None, "Orbitherm Studio",
                "輻射モデルの取得に失敗しました:\n{}".format(e),
            )
            return
        if not surfaces:
            QtGui.QMessageBox.information(
                None, "Orbitherm Studio",
                "ドキュメントに輻射モデル（FaceGroup）がありません。モデリングでモデルを準備してください。",
            )
            return
        try:
            results, _ = orbit_radiation.compute_face_heat_inputs(
                surfaces, orbit_input, times, heat_array, attitude_mode
            )
            orbit_radiation.apply_orbit_heat_to_radiation_model(
                doc, results, surfaces, mode="mean"
            )
        except Exception as e:
            QtGui.QMessageBox.critical(None, "ThermalAnalysis 適用エラー", str(e))
            return
        from orbitherm_studio.modeling.freecad_utils import get_default_export_dir
        _dir = get_default_export_dir()
        _start = os.path.join(_dir, "orbit_face_heat.csv") if _dir else "orbit_face_heat.csv"
        path, _ = QtGui.QFileDialog.getSaveFileName(
            None, "面ごと熱入力 CSV を保存（任意）", _start,
            "CSV Files (*.csv);;All Files (*)",
        )
        if path:
            try:
                orbit_radiation.export_face_heat_csv(path, results)
                QtGui.QMessageBox.information(
                    None, "Orbitherm Studio", "HeatSource を更新し、CSV を保存しました:\n{}".format(path),
                )
            except Exception as e:
                QtGui.QMessageBox.warning(None, "Orbitherm Studio", "CSV 保存に失敗:\n{}".format(e))
        else:
            QtGui.QMessageBox.information(
                None, "Orbitherm Studio", "輻射モデルのノードに軌道平均熱入力を適用しました。",
            )


# === ワークベンチクラスの定義
# ===================================================================================
class OrbithermWorkbench(FreeCADGui.Workbench):
    """Orbitherm Studio — FreeCAD-based thermal modeling workbench."""
    MenuText = "Orbitherm"; ToolTip = "Orbitherm Studio — FreeCADベース熱解析モデリング環境"
    _ra_tree_view = None
    _ra_tree_filter = None
    _ra_tree_context_menu_saved = None  # 復元用に元の contextMenuPolicy を保存

    @staticmethod
    def _get_path():
        for p in sys.path:
            if os.path.basename(p) in ("orbitherm-studio", "orbitherm_studio", "ThermalAnalysis"): return p
        return os.path.join(FreeCAD.getUserAppDataDir(), "Mod", "orbitherm-studio")
    def __init__(self):
        super().__init__()
        workbench_path = self._get_path()
        self.Icon = os.path.join(workbench_path, "Resources", "icons", "Orbitherm_Workbench_Icon.svg")
    def Initialize(self):
        # ツールバー: 表示は「表示設定」のみ（ダイアログで排他選択）
        self.list = [
            'ThermalAnalysis_Modeling_PrepareModel', 'ThermalAnalysis_Modeling_Defeaturing', 'ThermalAnalysis_Modeling_DefeaturingSelected', 'ThermalAnalysis_Modeling_EditProperties', 'ThermalAnalysis_Modeling_BulkSetProperties',
            'ThermalAnalysis_Modeling_ManageMaterials', 'ThermalAnalysis_Modeling_SubdivideSurface',
            'ThermalAnalysis_Modeling_DisplayOptions', 'ThermalAnalysis_DisplayParametersSettings',
            'ThermalAnalysis_Modeling_CalculateThermalMass', 'ThermalAnalysis_Modeling_CalculateConductance',
            'ThermalAnalysis_Modeling_CalculateRadiationConductance', 'ThermalAnalysis_Modeling_AddConductance',
            'ThermalAnalysis_Modeling_ThermalModelExport', 'ThermalAnalysis_Post_PostProcessing',
        ]
        self.appendToolbar("Modeling", self.list)
        # メニュー Modeling（表示設定を直下に含む）、Orbit Heat、Solver、Post
        _modeling_main = [
            "ThermalAnalysis_Modeling_PrepareModel", "ThermalAnalysis_Modeling_Defeaturing", "ThermalAnalysis_Modeling_DefeaturingSelected", "ThermalAnalysis_Modeling_EditProperties", "ThermalAnalysis_Modeling_BulkSetProperties",
            "ThermalAnalysis_Modeling_ManageMaterials", "ThermalAnalysis_Modeling_SubdivideSurface",
            "ThermalAnalysis_Modeling_DisplayOptions", "ThermalAnalysis_DisplayParametersSettings",
            "ThermalAnalysis_Modeling_CalculateThermalMass", "ThermalAnalysis_Modeling_CalculateConductance",
            "ThermalAnalysis_Modeling_CalculateRadiationConductance", "ThermalAnalysis_Modeling_AddConductance",
            "ThermalAnalysis_Modeling_ThermalModelExport", "ThermalAnalysis_Post_PostProcessing",
        ]
        self.appendMenu("Modeling", _modeling_main)
        _orbit_commands = ["ThermalAnalysis_Orbit_CalcHeatAndVisualize", "ThermalAnalysis_Orbit_StepOrbitFrames", "ThermalAnalysis_Orbit_SaveHeatArrayCSV", "ThermalAnalysis_Orbit_ExportHeatArrayOnly", "ThermalAnalysis_Orbit_ApplyOrbitHeatToRadiation", "ThermalAnalysis_Orbit_ClearVisualization"]
        self.appendToolbar("Orbit Heat", _orbit_commands)
        self.appendMenu("Orbit Heat", _orbit_commands)
        self.appendMenu("Solver", [])
        _post_commands = ["ThermalAnalysis_Post_PostProcessing"]
        self.appendMenu("Post", _post_commands)
        FreeCAD.Console.PrintMessage("Orbitherm Studio ワークベンチが初期化されました。\n")
    def Activated(self):
        cls = self.__class__
        find_tree = getattr(self.__class__, "_find_tree_view_fn", None)
        if find_tree is None:
            return
        tree = find_tree()
        if tree is not None and cls._ra_tree_filter is None:
            filter_class = getattr(self.__class__, "_TreeContextMenuFilter_class", None)
            if filter_class is not None:
                cls._ra_tree_filter = filter_class(self, tree)
                tree.installEventFilter(cls._ra_tree_filter)
                if tree.viewport():
                    tree.viewport().installEventFilter(cls._ra_tree_filter)
                # デフォルトの右クリックメニューを出さないようコンテキストメニューを自前に差し替え
                cls._ra_tree_context_menu_saved = tree.contextMenuPolicy()
                tree.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
                tree.customContextMenuRequested.connect(cls._on_tree_context_menu)
                cls._ra_tree_view = tree
    @classmethod
    def _on_tree_context_menu(cls, position):
        """ツリーの右クリック時: 輻射解析対象なら自前メニューのみ表示。"""
        from PySide import QtGui
        tree = cls._ra_tree_view
        if tree is None or cls._ra_tree_filter is None:
            return
        targets = cls._ra_tree_filter._target_objects_for_position(tree, position)
        if not targets:
            return
        menu = QtGui.QMenu()
        for cmd_name in cls._ra_tree_filter._command_names:
            cmd = FreeCADGui.getCommand(cmd_name)
            if cmd and getattr(cmd, "IsActive", lambda: False)():
                action = menu.addAction(getattr(cmd, "GetResources", lambda: {})().get("MenuText", cmd_name))
                action.triggered.connect(lambda c=cmd: c.Activated())
        if menu.isEmpty():
            return
        doc = FreeCAD.ActiveDocument
        if doc and targets:
            FreeCADGui.Selection.clearSelection()
            for o in targets:
                FreeCADGui.Selection.addSelection(doc, o.Name)
        menu.exec_(tree.viewport().mapToGlobal(position))
    def Deactivated(self):
        cls = self.__class__
        # ホバーコールバックはワークベンチに依存しないため、ここでは解除しない（他ワークベンチでも表示する）
        if cls._ra_tree_view is not None and cls._ra_tree_filter is not None:
            try:
                try:
                    cls._ra_tree_view.customContextMenuRequested.disconnect(cls._on_tree_context_menu)
                except Exception:
                    pass
                if cls._ra_tree_context_menu_saved is not None:
                    cls._ra_tree_view.setContextMenuPolicy(cls._ra_tree_context_menu_saved)
                cls._ra_tree_view.removeEventFilter(cls._ra_tree_filter)
                if cls._ra_tree_view.viewport():
                    cls._ra_tree_view.viewport().removeEventFilter(cls._ra_tree_filter)
            except Exception:
                pass
            cls._ra_tree_view = None
            cls._ra_tree_filter = None
            cls._ra_tree_context_menu_saved = None


# コールバックが別スコープで実行されても参照できるようクラス属性をモジュール読み込み時に設定
OrbithermWorkbench._find_tree_view_fn = _find_tree_view
OrbithermWorkbench._TreeContextMenuFilter_class = _TreeContextMenuFilter

# 後方互換エイリアス（既存の参照が壊れないよう維持）
ThermalAnalysisWorkbench = OrbithermWorkbench


# _LegacyRadiationCommandAlias は gui/commands.py に移動済み。
# 登録処理直前の import で上書きされるため、以下の定義は互換用のみ。
class _LegacyRadiationCommandAlias:
    """
    旧 RadiationAnalysis_* コマンド名から新しい ThermalAnalysis_* コマンドへのエイリアス。
    ユーザ設定やカスタムツールバーが古いコマンド名を参照していてもエラーにならないようにする。
    """

    def __init__(self, new_name):
        self._new_name = new_name

    def GetResources(self):
        # メニュー等には特に出さないので最小限
        return {
            "MenuText": "Legacy alias",
            "ToolTip": "旧 RadiationAnalysis_* コマンドのエイリアスです。",
        }

    def IsActive(self):
        # 対象コマンドがアクティブなときだけ有効とする
        try:
            cmd = FreeCADGui.getCommand(self._new_name)
            ok = bool(cmd and getattr(cmd, "IsActive", lambda: False)())
            # #region agent log
            log_fn = globals().get("_agent_debug_log", None)
            if callable(log_fn):
                log_fn(
                    hypothesis_id="H5",
                    location="InitGui.py:_LegacyRadiationCommandAlias.IsActive",
                    message="Legacy alias IsActive evaluated",
                    data={"new_name": self._new_name, "ok": ok},
                    run_id="initial",
                )
            # #endregion
            return ok
        except Exception:
            return False

    def Activated(self):
        # 対応する新コマンドをそのまま呼び出す
        try:
            # #region agent log
            log_fn = globals().get("_agent_debug_log", None)
            if callable(log_fn):
                log_fn(
                    hypothesis_id="H5",
                    location="InitGui.py:_LegacyRadiationCommandAlias.Activated",
                    message="Legacy alias Activated entry",
                    data={"new_name": self._new_name},
                    run_id="initial",
                )
            # #endregion
            FreeCADGui.runCommand(self._new_name)
        except Exception:
            FreeCAD.Console.PrintError(
                f"Legacy command alias '{self._new_name}' の実行に失敗しました。\n"
            )


# ===================================================================================
# === コマンドクラスを gui/commands.py から再インポート（正規の定義元）
# 上で定義したローカルクラスを上書きし、gui/commands.py を単一の定義源にする。
# ===================================================================================
from orbitherm_studio.gui.commands import *  # noqa: F401, F403
from orbitherm_studio.gui.commands import _LegacyRadiationCommandAlias  # noqa: F401


# ===================================================================================
# === 登録処理
# ===================================================================================
try:
    # #region agent log
    _agent_debug_log(
        hypothesis_id="H2",
        location="InitGui.py:register_commands",
        message="Begin command/workbench registration",
        data={},
        run_id="initial",
    )
    # #endregion

    # 新コマンド群
    FreeCADGui.addCommand('ThermalAnalysis_Modeling_PrepareModel', ThermalAnalysis_Modeling_PrepareModel())
    FreeCADGui.addCommand('ThermalAnalysis_Modeling_Defeaturing', ThermalAnalysis_Modeling_Defeaturing())
    FreeCADGui.addCommand('ThermalAnalysis_Modeling_DefeaturingSelected', ThermalAnalysis_Modeling_DefeaturingSelected())
    FreeCADGui.addCommand('ThermalAnalysis_Modeling_EditProperties', ThermalAnalysis_Modeling_EditProperties())
    FreeCADGui.addCommand('ThermalAnalysis_Modeling_BulkSetProperties', ThermalAnalysis_Modeling_BulkSetProperties())
    FreeCADGui.addCommand('ThermalAnalysis_Modeling_ManageMaterials', ThermalAnalysis_Modeling_ManageMaterials())
    FreeCADGui.addCommand('ThermalAnalysis_Modeling_VisualizeActiveSide', ThermalAnalysis_Modeling_VisualizeActiveSide())
    FreeCADGui.addCommand('ThermalAnalysis_Modeling_VisualizeAbsorptivity', ThermalAnalysis_Modeling_VisualizeAbsorptivity())
    FreeCADGui.addCommand('ThermalAnalysis_Modeling_VisualizeEmissivity', ThermalAnalysis_Modeling_VisualizeEmissivity())
    FreeCADGui.addCommand('ThermalAnalysis_Modeling_VisualizeTransmittance', ThermalAnalysis_Modeling_VisualizeTransmittance())
    FreeCADGui.addCommand('ThermalAnalysis_Modeling_RestoreDefaultDisplay', ThermalAnalysis_Modeling_RestoreDefaultDisplay())
    FreeCADGui.addCommand('ThermalAnalysis_Modeling_CalculateThermalMass', ThermalAnalysis_Modeling_CalculateThermalMass())
    FreeCADGui.addCommand('ThermalAnalysis_Modeling_CalculateConductance', ThermalAnalysis_Modeling_CalculateConductance())
    FreeCADGui.addCommand('ThermalAnalysis_Modeling_CalculateRadiationConductance', ThermalAnalysis_Modeling_CalculateRadiationConductance())
    FreeCADGui.addCommand('ThermalAnalysis_Modeling_ThermalModelExport', ThermalAnalysis_Modeling_ThermalModelExport())
    FreeCADGui.addCommand('ThermalAnalysis_Modeling_SubdivideSurface', ThermalAnalysis_Modeling_SubdivideSurface())
    FreeCADGui.addCommand('ThermalAnalysis_Modeling_DisplayOptions', ThermalAnalysis_Modeling_DisplayOptions())
    FreeCADGui.addCommand('ThermalAnalysis_DisplayParametersSettings', ThermalAnalysis_DisplayParametersSettings())
    FreeCADGui.addCommand('ThermalAnalysis_Modeling_AddConductance', ThermalAnalysis_Modeling_AddConductance())
    FreeCADGui.addCommand('ThermalAnalysis_Post_PostProcessing', ThermalAnalysis_Post_PostProcessing())
    FreeCADGui.addCommand('ThermalAnalysis_Orbit_CalcHeatAndVisualize', ThermalAnalysis_Orbit_CalcHeatAndVisualize())
    FreeCADGui.addCommand('ThermalAnalysis_Orbit_StepOrbitFrames', ThermalAnalysis_Orbit_StepOrbitFrames())
    FreeCADGui.addCommand('ThermalAnalysis_Orbit_SaveHeatArrayCSV', ThermalAnalysis_Orbit_SaveHeatArrayCSV())
    FreeCADGui.addCommand('ThermalAnalysis_Orbit_ExportHeatArrayOnly', ThermalAnalysis_Orbit_ExportHeatArrayOnly())
    FreeCADGui.addCommand('ThermalAnalysis_Orbit_ApplyOrbitHeatToRadiation', ThermalAnalysis_Orbit_ApplyOrbitHeatToRadiation())
    FreeCADGui.addCommand('ThermalAnalysis_Orbit_ClearVisualization', ThermalAnalysis_Orbit_ClearVisualization())

    # #region agent log
    try:
        cmds = list(FreeCADGui.listCommands())
    except Exception:
        cmds = []
    _agent_debug_log(
        hypothesis_id="H2",
        location="InitGui.py:register_commands",
        message="Registered core commands (snapshot)",
        data={
            "n_commands": len(cmds),
            "has_prepare": ("ThermalAnalysis_Modeling_PrepareModel" in cmds),
            "has_calc_cond": ("ThermalAnalysis_Modeling_CalculateConductance" in cmds),
        },
        run_id="initial",
    )
    # #endregion

    # 旧 RadiationAnalysis_* コマンドへのエイリアスを登録（ユーザ設定の互換性維持用）
    legacy_map = {
        "RadiationAnalysis_PrepareModel": "ThermalAnalysis_Modeling_PrepareModel",
        "RadiationAnalysis_EditProperties": "ThermalAnalysis_Modeling_EditProperties",
        "RadiationAnalysis_BulkSetProperties": "ThermalAnalysis_Modeling_BulkSetProperties",
        "RadiationAnalysis_ManageMaterials": "ThermalAnalysis_Modeling_ManageMaterials",
        "RadiationAnalysis_SubdivideSurface": "ThermalAnalysis_Modeling_SubdivideSurface",
        "RadiationAnalysis_DisplayOptions": "ThermalAnalysis_Modeling_DisplayOptions",
        "RadiationAnalysis_VisualizeActiveSide": "ThermalAnalysis_Modeling_VisualizeActiveSide",
        "RadiationAnalysis_VisualizeAbsorptivity": "ThermalAnalysis_Modeling_VisualizeAbsorptivity",
        "RadiationAnalysis_VisualizeEmissivity": "ThermalAnalysis_Modeling_VisualizeEmissivity",
        "RadiationAnalysis_CalculateThermalMass": "ThermalAnalysis_Modeling_CalculateThermalMass",
        "RadiationAnalysis_CalculateConductance": "ThermalAnalysis_Modeling_CalculateConductance",
        "RadiationAnalysis_CalculateRadiationConductance": "ThermalAnalysis_Modeling_CalculateRadiationConductance",
        "RadiationAnalysis_AddConductance": "ThermalAnalysis_Modeling_AddConductance",
        "RadiationAnalysis_ThermalModelExport": "ThermalAnalysis_Modeling_ThermalModelExport",
    }
    try:
        existing = set(FreeCADGui.listCommands())
    except Exception:
        existing = set()
    for old_name, new_name in legacy_map.items():
        if old_name in existing:
            continue
        FreeCADGui.addCommand(old_name, _LegacyRadiationCommandAlias(new_name))

    # OrbithermWorkbench の登録（既に存在する場合はスキップ）
    try:
        wbs = getattr(FreeCADGui, "listWorkbenches", lambda: {})()
        if isinstance(wbs, dict) and ("OrbithermWorkbench" in wbs or "ThermalAnalysisWorkbench" in wbs):
            pass
        else:
            FreeCADGui.addWorkbench(OrbithermWorkbench())
    except Exception:
        # 古い FreeCAD などで listWorkbenches が無い場合は従来通り登録を試みる
        try:
            FreeCADGui.addWorkbench(OrbithermWorkbench())
        except Exception:
            pass
except Exception as e:
    # #region agent log
    _agent_debug_log(
        hypothesis_id="H3",
        location="InitGui.py:register_commands",
        message="Exception during command/workbench registration",
        data={"error": str(e)},
        run_id="initial",
    )
    # #endregion
    FreeCAD.Console.PrintError(f"登録中にエラーが発生しました: {e}\n")