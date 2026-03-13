# -*- coding: utf-8 -*-
"""
ThermalAnalysis GUI コマンドクラス群。
FreeCAD ツールバー・メニューに登録されるコマンド（ThermalAnalysis_*）と
レガシーエイリアス（_LegacyRadiationCommandAlias）を収容する。
登録処理は InitGui.py が行う。
"""

import os
import sys

import FreeCAD
import FreeCADGui


# ===================================================================================
# === モデリング コマンド (ThermalAnalysis_Modeling_*)
# ===================================================================================

class ThermalAnalysis_Modeling_PrepareModel:
    @staticmethod
    def _get_path():
        for p in sys.path:
            if os.path.basename(p) == "ThermalAnalysis": return p
        return os.path.join(FreeCAD.getUserAppDataDir(), "Mod", "ThermalAnalysis")
    def GetResources(self):
        workbench_path = self._get_path()
        icon_path = os.path.join(workbench_path, "Resources", "icons", "RadiationAnalysis_PrepareModel_Icon.svg")
        return {
            'Pixmap': icon_path,
            'MenuText': "モデルを準備",
            'ToolTip': "面ごとのメッシュと、面の中心ノードを作成します。オブジェクトのみ選択で全面変換。面をサブ選択すると選択した面のみ変換。サーフェースのみのオブジェクト（Shell等）も選択可能。",
        }
    def Activated(self):
        from ThermalAnalysis.gui.panels import PrepareModelDialog
        from ThermalAnalysis.modeling import core
        dlg = PrepareModelDialog()
        if not dlg.exec_():
            return
        linear_deflection, angular_deflection, one_node_per_solid = dlg.get_values()
        core.run_prepare_model(
            linear_deflection=linear_deflection,
            angular_deflection=angular_deflection,
            one_node_per_solid=one_node_per_solid,
        )

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None


class ThermalAnalysis_Modeling_Defeaturing:
    @staticmethod
    def _get_path():
        for p in sys.path:
            if os.path.basename(p) == "ThermalAnalysis":
                return p
        return os.path.join(FreeCAD.getUserAppDataDir(), "Mod", "ThermalAnalysis")

    def GetResources(self):
        workbench_path = self._get_path()
        icon_path = os.path.join(workbench_path, "Resources", "icons", "RadiationAnalysis_PrepareModel_Icon.svg")
        return {
            "Pixmap": icon_path,
            "MenuText": "形状の簡略化（穴・フィレット削除）",
            "ToolTip": "選択した Part から、指定した直径以下の穴と R 以下のフィレットを削除した新しい形状を作成します。解析用の単純化に利用できます。",
        }

    def Activated(self):
        from ThermalAnalysis.gui.panels import DefeaturingDialog
        from ThermalAnalysis.modeling import defeaturing
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


class ThermalAnalysis_Modeling_DefeaturingSelected:
    @staticmethod
    def _get_path():
        for p in sys.path:
            if os.path.basename(p) == "ThermalAnalysis":
                return p
        return os.path.join(FreeCAD.getUserAppDataDir(), "Mod", "ThermalAnalysis")

    def GetResources(self):
        workbench_path = self._get_path()
        icon_path = os.path.join(workbench_path, "Resources", "icons", "RadiationAnalysis_PrepareModel_Icon.svg")
        return {
            "Pixmap": icon_path,
            "MenuText": "形状の簡略化（選択した面のみ）",
            "ToolTip": "オブジェクトを選択したうえで、削除したい面を Ctrl+クリックでサブ選択してから実行します。選択した面だけを Defeaturing で削除した新しい形状を作成します。",
        }

    def Activated(self):
        from ThermalAnalysis.modeling import defeaturing
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


class ThermalAnalysis_Modeling_EditProperties:
    def GetResources(self):
        return {
            "MenuText": "プロパティ編集",
            "ToolTip": "選択したオブジェクトのプロパティを編集します。",
        }

    def Activated(self):
        from ThermalAnalysis.gui.panels import EditPropertiesTaskPanel
        self.panel = EditPropertiesTaskPanel()
        FreeCADGui.Control.showDialog(self.panel)

    def IsActive(self):
        selection = FreeCADGui.Selection.getSelection()
        if not selection: return False
        return all(sel.isDerivedFrom("Mesh::Feature") and "Face_" in sel.Name for sel in selection)


class ThermalAnalysis_Modeling_BulkSetProperties:
    def GetResources(self):
        return {
            "MenuText": "面の一括プロパティ設定",
            "ToolTip": "輻射モデル内の全面に同じ熱物性・光学特性を一括で設定します。",
        }

    def Activated(self):
        from ThermalAnalysis.gui.panels import BulkPropertiesDialog
        dlg = BulkPropertiesDialog()
        dlg.exec_()

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None


class ThermalAnalysis_Modeling_ManageMaterials:
    def GetResources(self):
        return {
            "MenuText": "マテリアル編集",
            "ToolTip": "マテリアルライブラリを編集します。",
        }

    def Activated(self):
        from ThermalAnalysis.gui.panels import MaterialEditorDialog
        self.dialog = MaterialEditorDialog()
        self.dialog.exec_()

    def IsActive(self):
        return True


class ThermalAnalysis_Modeling_VisualizeActiveSide:
    def GetResources(self): return {'MenuText': "アクティブ面 表示", 'ToolTip': "アクティブ面の設定に応じて色分け表示します。"}
    def Activated(self): from ThermalAnalysis.modeling import core; core.visualize_active_side()
    def IsActive(self): return FreeCAD.ActiveDocument is not None


class ThermalAnalysis_Modeling_VisualizeAbsorptivity:
    def GetResources(self): return {'MenuText': "吸収率 表示", 'ToolTip': "太陽光吸収率をコンター表示します。"}
    def Activated(self): from ThermalAnalysis.modeling import core; core.visualize_property_contour("SolarAbsorptivity", "太陽光吸収率")
    def IsActive(self): return FreeCAD.ActiveDocument is not None


class ThermalAnalysis_Modeling_VisualizeEmissivity:
    def GetResources(self): return {'MenuText': "放射率 表示", 'ToolTip': "赤外放射率をコンター表示します。"}
    def Activated(self): from ThermalAnalysis.modeling import core; core.visualize_property_contour("InfraredEmissivity", "赤外放射率")
    def IsActive(self): return FreeCAD.ActiveDocument is not None


class ThermalAnalysis_Modeling_VisualizeTransmittance:
    def GetResources(self): return {'MenuText': "透過率 表示", 'ToolTip': "透過率をコンター表示します。"}
    def Activated(self): from ThermalAnalysis.modeling import core; core.visualize_property_contour("Transmittance", "透過率")
    def IsActive(self): return FreeCAD.ActiveDocument is not None


class ThermalAnalysis_Modeling_RestoreDefaultDisplay:
    def GetResources(self):
        return {
            'MenuText': "表示をデフォルトに戻す",
            'ToolTip': "アクティブ面・吸収率・放射率・透過率の色分けをやめ、全面をデフォルト色に戻します。",
        }
    def Activated(self):
        from ThermalAnalysis.modeling import core
        core.restore_default_display()
    def IsActive(self):
        return FreeCAD.ActiveDocument is not None


class ThermalAnalysis_Modeling_DisplayOptions:
    def GetResources(self):
        return {
            "MenuText": "表示設定",
            "ToolTip": "表示モード（アクティブ面・吸収率・放射率・透過率・デフォルト）を排他的に選ぶダイアログを開きます。",
        }

    def Activated(self):
        from ThermalAnalysis.gui.panels import DisplayOptionsDialog
        dlg = DisplayOptionsDialog()
        dlg.exec_()

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None


class ThermalAnalysis_DisplayParametersSettings:
    def GetResources(self):
        return {
            "MenuText": "表示・伝導パラメータ設定",
            "ToolTip": "ノード表示・コンダクタンス線・伝導コンダクタンスのペア選定パラメータを設定します。",
        }

    def Activated(self):
        from ThermalAnalysis.gui.panels import DisplayParametersSettingsDialog
        dlg = DisplayParametersSettingsDialog()
        dlg.exec_()

    def IsActive(self):
        return True


class ThermalAnalysis_ToggleHoverLabel:
    def GetResources(self):
        return {
            "MenuText": "面・ノード番号のホバー表示",
            "ToolTip": "3Dビューでマウスを重ねたときの面・ノード番号表示をオン/オフします。複雑な形状で重い場合はオフにすると軽くなります。",
        }

    def Activated(self):
        p = FreeCAD.ParamGet("User parameter:Base/App/Preferences/Mod/ThermalAnalysis")
        current = p.GetBool("HoverLabelEnabled", True)
        p.SetBool("HoverLabelEnabled", not current)
        if not current:
            FreeCAD.Console.PrintMessage("ThermalAnalysis: 面・ノード番号のホバー表示をオンにしました。\n")
        else:
            try:
                doc = FreeCAD.ActiveDocument
                if doc:
                    from ThermalAnalysis.modeling import core
                    core.clear_hover_label(doc)
            except Exception:
                pass
            FreeCAD.Console.PrintMessage("ThermalAnalysis: 面・ノード番号のホバー表示をオフにしました。\n")

    def IsActive(self):
        return True

    def GetState(self):
        """チェック可能メニュー用: オンなら 1、オフなら 0。"""
        p = FreeCAD.ParamGet("User parameter:Base/App/Preferences/Mod/ThermalAnalysis")
        return 1 if p.GetBool("HoverLabelEnabled", True) else 0


class ThermalAnalysis_Modeling_CalculateThermalMass:
    def GetResources(self): return {'MenuText': "熱容量計算", 'ToolTip': "設定された物性値から各ノードの熱容量を計算します。"}
    def Activated(self): from ThermalAnalysis.modeling import core; core.calculate_thermal_mass()
    def IsActive(self): return FreeCAD.ActiveDocument is not None


class ThermalAnalysis_Modeling_CalculateConductance:
    def GetResources(self): return {'MenuText': "伝熱コンダクタンス計算", 'ToolTip': "隣接するメッシュ間の伝熱コンダクタンスを計算します。"}
    def Activated(self): from ThermalAnalysis.modeling import core; core.calculate_conductance()
    def IsActive(self): return FreeCAD.ActiveDocument is not None


class ThermalAnalysis_Modeling_CalculateRadiationConductance:
    def GetResources(self):
        return {
            "MenuText": "輻射コンダクタンス計算",
            "ToolTip": "レイトレーシングでビューファクターを計算し、輻射コンダクタンス係数 R'=ε×Vf×A を計算します。空間への輻射は SPACE.9999 ノードとして出力します。",
        }
    def Activated(self):
        from ThermalAnalysis.modeling import core
        from ThermalAnalysis.gui.panels import RadiationParamsDialog
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
        from ThermalAnalysis.modeling import core
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


class ThermalAnalysis_Modeling_ThermalModelExport:
    def GetResources(self):
        return {
            "MenuText": "Thermal Model Export",
            "ToolTip": "HEADER OPTIONS/CONTROL を設定し、ノード・伝熱・輻射コンダクタンスを熱解析ソルバー用 .inp で出力します。",
        }

    def Activated(self):
        from ThermalAnalysis.modeling import core
        from ThermalAnalysis.gui.panels import ThermalModelExportDialog
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
        from ThermalAnalysis.modeling.freecad_utils import get_default_export_dir
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


class ThermalAnalysis_Modeling_SubdivideSurface:
    def GetResources(self):
        return {'MenuText': "サーフェースを分割", 'ToolTip': "選択したFaceGroupのメッシュをグリッドで分割し、サブサーフェースとノードを作成します。"}

    def Activated(self):
        from ThermalAnalysis.gui.panels import SubdivideSurfaceDialog
        from ThermalAnalysis.modeling import core
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


# ===================================================================================
# === ポスト処理コマンド (ThermalAnalysis_Post_*)
# ===================================================================================

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
        from ThermalAnalysis.gui.panels import PostProcessingDialog
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
        from ThermalAnalysis.gui.orbit_gui import OrbitEnvironmentDialog
        from ThermalAnalysis.orbit_heat import orbit_core, orbit_visualization
        doc = FreeCAD.ActiveDocument
        if not doc:
            QtGui.QMessageBox.warning(
                None, "ThermalAnalysis", "アクティブなドキュメントがありません。"
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
            None, "ThermalAnalysis",
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
        from ThermalAnalysis.orbit_heat import orbit_core

        data = orbit_core.get_last_heat_data()
        if not data:
            QtGui.QMessageBox.information(
                None, "ThermalAnalysis",
                "保存するデータがありません。\n先に「軌道計算と描画」を実行してください。",
            )
            return
        times, heat_array, meta = data
        from ThermalAnalysis.modeling.freecad_utils import get_default_export_dir
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
            QtGui.QMessageBox.information(None, "ThermalAnalysis", "保存しました:\n{}".format(path))
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
        from ThermalAnalysis.gui.orbit_gui import OrbitEnvironmentDialog
        from ThermalAnalysis.orbit_heat import orbit_core

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
        from ThermalAnalysis.modeling.freecad_utils import get_default_export_dir
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
            QtGui.QMessageBox.information(None, "ThermalAnalysis", "保存しました:\n{}".format(path))
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
            QtGui.QMessageBox.information(None, "ThermalAnalysis", "OrbitVisualization グループが見つかりません。")
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
        QtGui.QMessageBox.information(None, "ThermalAnalysis", "OrbitVisualization をクリアしました。")


class ThermalAnalysis_Orbit_StepOrbitFrames:
    def GetResources(self):
        return {
            "MenuText": "軌道コマ送り",
            "ToolTip": "各計算点での衛星の位置・向きをコマ送りで確認します。",
        }

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        from ThermalAnalysis.gui.orbit_step_dialog import OrbitStepDialog
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
        from ThermalAnalysis.orbit_heat import orbit_core, orbit_radiation
        from ThermalAnalysis.bridge import orbit_heat_bridge as bridge

        state = orbit_core.get_last_orbit_state()
        if not state:
            QtGui.QMessageBox.information(
                None, "ThermalAnalysis",
                "軌道データがありません。先に「軌道計算と描画」を実行してください。",
            )
            return
        times, _, attitude_mode, orbit_input, heat_array = state
        if heat_array is None or len(times) == 0:
            QtGui.QMessageBox.warning(None, "ThermalAnalysis", "熱入力データがありません。")
            return
        doc = FreeCAD.ActiveDocument
        if not doc:
            return
        try:
            surfaces = bridge.get_surfaces_for_orbit_heat(doc)
        except Exception as e:
            QtGui.QMessageBox.critical(
                None, "ThermalAnalysis",
                "輻射モデルの取得に失敗しました:\n{}".format(e),
            )
            return
        if not surfaces:
            QtGui.QMessageBox.information(
                None, "ThermalAnalysis",
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
        from ThermalAnalysis.modeling.freecad_utils import get_default_export_dir
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
                    None, "ThermalAnalysis", "HeatSource を更新し、CSV を保存しました:\n{}".format(path),
                )
            except Exception as e:
                QtGui.QMessageBox.warning(None, "ThermalAnalysis", "CSV 保存に失敗:\n{}".format(e))
        else:
            QtGui.QMessageBox.information(
                None, "ThermalAnalysis", "輻射モデルのノードに軌道平均熱入力を適用しました。",
            )


# ===================================================================================
# === レガシーエイリアス
# ===================================================================================

class _LegacyRadiationCommandAlias:
    """
    旧 RadiationAnalysis_* コマンド名から新しい ThermalAnalysis_* コマンドへのエイリアス。
    ユーザ設定やカスタムツールバーが古いコマンド名を参照していてもエラーにならないようにする。
    """

    def __init__(self, new_name):
        self._new_name = new_name

    def GetResources(self):
        return {
            "MenuText": "Legacy alias",
            "ToolTip": "旧 RadiationAnalysis_* コマンドのエイリアスです。",
        }

    def IsActive(self):
        try:
            cmd = FreeCADGui.getCommand(self._new_name)
            return bool(cmd and getattr(cmd, "IsActive", lambda: False)())
        except Exception:
            return False

    def Activated(self):
        try:
            FreeCADGui.runCommand(self._new_name)
        except Exception:
            FreeCAD.Console.PrintError(
                f"Legacy command alias '{self._new_name}' の実行に失敗しました。\n"
            )
