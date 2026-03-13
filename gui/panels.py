import FreeCAD
import FreeCADGui
from PySide import QtCore, QtGui

from ThermalAnalysis.modeling import materials, freecad_utils


def _get_first_optical():
    """materials から先頭の光学マテリアルを返す。get_first_optical が無い古い Mod でも動作する。"""
    fn = getattr(materials, "get_first_optical", None)
    if callable(fn):
        return fn()
    try:
        names = materials.list_optical_names()
        return materials.get_optical(names[0]) if names else None
    except Exception:
        return None


def _get_first_physical():
    """materials から先頭の熱物性マテリアルを返す。get_first_physical が無い古い Mod でも動作する。"""
    fn = getattr(materials, "get_first_physical", None)
    if callable(fn):
        return fn()
    try:
        names = materials.list_physical_names()
        return materials.get_physical(names[0]) if names else None
    except Exception:
        return None


class EditPropertiesTaskPanel:
    """
    もともと InitGui.RadiationAnalysis_EditProperties 内部にあった
    EditPropertiesTaskPanel を独立モジュールとして切り出したもの。
    """

    def __init__(self):
        selection = FreeCADGui.Selection.getSelection()
        self.selected_objects = selection
        self.obj = self.selected_objects[0] if self.selected_objects else None

        num_selected = len(self.selected_objects)
        obj_label = (
            f"{self.obj.Label} (他 {num_selected - 1}個)"
            if num_selected > 1
            else getattr(self.obj, "Label", "なし")
        )

        self.widget = QtGui.QWidget()
        self.layout = QtGui.QVBoxLayout(self.widget)
        self.layout.addWidget(QtGui.QLabel(f"<b>対象オブジェクト:</b> {obj_label}"))

        optical_groupbox = QtGui.QGroupBox("熱光学特性")
        physical_groupbox = QtGui.QGroupBox("熱物性")
        optical_layout = QtGui.QFormLayout(optical_groupbox)
        physical_layout = QtGui.QFormLayout(physical_groupbox)

        self.combo_optical_material = QtGui.QComboBox()
        # materials.json からのみ候補を読み込む（デフォルト値は使わない）
        optical_names = ["カスタム"]
        try:
            optical_names.extend(materials.list_optical_names())
        except Exception:
            pass
        self.combo_optical_material.addItems(optical_names)
        optical_layout.addRow("マテリアル:", self.combo_optical_material)
        self.combo_optical_material.currentTextChanged.connect(self._on_optical_material_changed)

        _opt = _get_first_optical() if self.obj else None
        _abs = getattr(self.obj, "SolarAbsorptivity", None) if self.obj else None
        _abs = _abs if _abs is not None and (isinstance(_abs, (int, float))) else (_opt.get("solar_absorptivity") if _opt else 0.0)
        self.le_absorptivity = QtGui.QLineEdit(str(_abs))
        optical_layout.addRow("太陽光吸収率 [-]:", self.le_absorptivity)

        _ems = getattr(self.obj, "InfraredEmissivity", None) if self.obj else None
        _ems = _ems if _ems is not None and isinstance(_ems, (int, float)) else (_opt.get("infrared_emissivity") if _opt else 0.0)
        self.le_emissivity = QtGui.QLineEdit(str(_ems))
        optical_layout.addRow("赤外放射率 [-]:", self.le_emissivity)

        _tra = getattr(self.obj, "Transmittance", None) if self.obj else None
        _tra = _tra if _tra is not None and isinstance(_tra, (int, float)) else (_opt.get("transmittance", 0.0) if _opt else 0.0)
        self.le_transmittance = QtGui.QLineEdit(str(_tra))
        optical_layout.addRow("透過率 [-]:", self.le_transmittance)

        self.combo_active_side = QtGui.QComboBox()
        self.active_side_options = ["両面", "表面", "裏面"]
        self.combo_active_side.addItems(self.active_side_options)
        current_active_side = getattr(self.obj, "ActiveSide", "両面")
        if current_active_side in self.active_side_options:
            self.combo_active_side.setCurrentIndex(
                self.active_side_options.index(current_active_side)
            )
        optical_layout.addRow("アクティブな面:", self.combo_active_side)

        self.combo_physical_material = QtGui.QComboBox()
        physical_names = ["カスタム"]
        try:
            physical_names.extend(materials.list_physical_names())
        except Exception:
            pass
        self.combo_physical_material.addItems(physical_names)
        physical_layout.addRow("マテリアル:", self.combo_physical_material)
        self.combo_physical_material.currentTextChanged.connect(self._on_physical_material_changed)

        _phy = _get_first_physical() if self.obj else None
        def _obj_float(attr):
            v = getattr(self.obj, attr, None) if self.obj else None
            return v if v is not None and isinstance(v, (int, float)) else None
        _t = _obj_float("Thickness")
        self.le_thickness = QtGui.QLineEdit(str(_t if _t is not None else (_phy.get("thickness") if _phy else 0.0)))
        physical_layout.addRow("厚み [m]:", self.le_thickness)
        _d = _obj_float("Density")
        self.le_density = QtGui.QLineEdit(str(_d if _d is not None else (_phy.get("density") if _phy else 0.0)))
        physical_layout.addRow("密度 [kg/m3]:", self.le_density)
        _sh = _obj_float("SpecificHeat")
        self.le_specific_heat = QtGui.QLineEdit(str(_sh if _sh is not None else (_phy.get("specific_heat") if _phy else 0.0)))
        physical_layout.addRow("比熱 [J/kgK]:", self.le_specific_heat)
        _tc = _obj_float("ThermalConductivity")
        self.le_conductivity = QtGui.QLineEdit(str(_tc if _tc is not None else (_phy.get("thermal_conductivity") if _phy else 0.0)))
        physical_layout.addRow("熱伝導率 [W/mK]:", self.le_conductivity)

        self.layout.addWidget(optical_groupbox)
        self.layout.addWidget(physical_groupbox)

        # 開いた時点でオブジェクトの現在値に一致するマテリアルをコンボに反映
        self._sync_combo_from_object()

        self.face_group = None
        self.node_obj = None
        self.surface_number_obj = None  # サーフェース番号を編集する対象（サブのときはメッシュ自身、それ以外は face_group）
        doc = FreeCAD.ActiveDocument
        if doc and self.obj and self.obj.isDerivedFrom("Mesh::Feature"):
            base_name, _, side = self.obj.Name.rpartition("_")
            if side in ("front", "back") and base_name.startswith("Face_"):
                direct_parent = None
                for o in doc.Objects:
                    if not hasattr(o, "Group"):
                        continue
                    if self.obj not in o.Group:
                        continue
                    direct_parent = o
                    if o.Name.startswith("FaceGroup_"):
                        self.face_group = o
                        break
                if self.face_group is None and direct_parent is not None:
                    for o in doc.Objects:
                        if not hasattr(o, "Group"):
                            continue
                        if direct_parent in o.Group and o.Name.startswith("FaceGroup_"):
                            self.face_group = o
                            break
                if self.face_group:
                    node_candidate_name = "Node_" + base_name.replace("Face_", "", 1)
                    for o in self.face_group.Group:
                        if o.Name == node_candidate_name:
                            self.node_obj = o
                            break
                    if self.node_obj is None:
                        for o in self.face_group.Group:
                            if o.Name.startswith("Node_"):
                                self.node_obj = o
                                break
                    if hasattr(self.obj, "SurfaceNumber"):
                        self.surface_number_obj = self.obj
                    else:
                        self.surface_number_obj = self.face_group
        if self.face_group is not None and self.node_obj is not None:
            number_groupbox = QtGui.QGroupBox("番号（計算・出力用）")
            number_layout = QtGui.QFormLayout(number_groupbox)
            self.spin_surface_number = QtGui.QSpinBox()
            self.spin_surface_number.setRange(-1000000, 1000000)
            surf_val = getattr(self.surface_number_obj, "SurfaceNumber", 0) if self.surface_number_obj else getattr(self.face_group, "SurfaceNumber", 0)
            self.spin_surface_number.setValue(surf_val)
            number_layout.addRow("サーフェース番号:", self.spin_surface_number)
            self.spin_node_number = QtGui.QSpinBox()
            self.spin_node_number.setRange(-1000000, 1000000)
            self.spin_node_number.setValue(getattr(self.node_obj, "NodeNumber", 0))
            number_layout.addRow("ノード番号:", self.spin_node_number)
            # ノード発熱量 [W]
            self.spin_heat_source = QtGui.QDoubleSpinBox()
            self.spin_heat_source.setDecimals(6)
            self.spin_heat_source.setRange(-1e9, 1e9)
            self.spin_heat_source.setValue(getattr(self.node_obj, "HeatSource", 0.0) if hasattr(self.node_obj, "HeatSource") else 0.0)
            number_layout.addRow("発熱量 [W]:", self.spin_heat_source)
            self.layout.addWidget(number_groupbox)

        if self.obj and self.obj.Name.endswith("_back"):
            physical_groupbox.setVisible(False)

        self.form = [self.widget]

    def _on_optical_material_changed(self, name):
        if not name or name == "カスタム":
            return
        try:
            data = materials.get_optical(name)
            if data:
                self.le_absorptivity.setText(str(data.get("solar_absorptivity", 0.0)))
                self.le_emissivity.setText(str(data.get("infrared_emissivity", 0.0)))
                self.le_transmittance.setText(str(data.get("transmittance", 0.0)))
        except Exception:
            pass

    def _on_physical_material_changed(self, name):
        if not name or name == "カスタム":
            return
        try:
            data = materials.get_physical(name)
            if data:
                self.le_thickness.setText(str(data.get("thickness", 0.0)))
                self.le_density.setText(str(data.get("density", 0.0)))
                self.le_specific_heat.setText(str(data.get("specific_heat", 0.0)))
                self.le_conductivity.setText(str(data.get("thermal_conductivity", 0.0)))
        except Exception:
            pass

    def _sync_combo_from_object(self):
        """オブジェクトの現在のプロパティ値に一致するマテリアルをコンボに反映する。プロパティが無い場合はマッチングしない。"""
        if not self.obj:
            return
        try:
            abs_val = getattr(self.obj, "SolarAbsorptivity", None)
            em_val = getattr(self.obj, "InfraredEmissivity", None)
            if abs_val is None or em_val is None:
                pass
            else:
                abs_val, em_val = float(abs_val), float(em_val)
                for i in range(self.combo_optical_material.count()):
                    name = self.combo_optical_material.itemText(i)
                    if name == "カスタム":
                        continue
                    data = materials.get_optical(name)
                    if data and abs(abs_val - data.get("solar_absorptivity", 0)) < 1e-6 and abs(em_val - data.get("infrared_emissivity", 0)) < 1e-6:
                        self.combo_optical_material.blockSignals(True)
                        self.combo_optical_material.setCurrentIndex(i)
                        self.combo_optical_material.blockSignals(False)
                        break
        except Exception:
            pass
        try:
            t = getattr(self.obj, "Thickness", None)
            d = getattr(self.obj, "Density", None)
            sh = getattr(self.obj, "SpecificHeat", None)
            tc = getattr(self.obj, "ThermalConductivity", None)
            if t is None or d is None or sh is None or tc is None:
                pass
            else:
                t, d, sh, tc = float(t), float(d), float(sh), float(tc)
                for i in range(self.combo_physical_material.count()):
                    name = self.combo_physical_material.itemText(i)
                    if name == "カスタム":
                        continue
                    data = materials.get_physical(name)
                    if not data:
                        continue
                    if (
                        abs(t - data.get("thickness", 0)) < 1e-9
                        and abs(d - data.get("density", 0)) < 1e-3
                        and abs(sh - data.get("specific_heat", 0)) < 1e-3
                        and abs(tc - data.get("thermal_conductivity", 0)) < 1e-3
                    ):
                        self.combo_physical_material.blockSignals(True)
                        self.combo_physical_material.setCurrentIndex(i)
                        self.combo_physical_material.blockSignals(False)
                        break
        except Exception:
            pass

    def accept(self):
        if not self.selected_objects:
            FreeCADGui.Control.closeDialog()
            return True
        try:
            doc = FreeCAD.ActiveDocument
            all_objects_to_update = []
            for obj in self.selected_objects:
                all_objects_to_update.append(obj)
                pair_obj = None
                if obj.Name.endswith("_front"):
                    pair_name = obj.Name.replace("_front", "_back")
                    pair_obj = doc.getObject(pair_name)
                elif obj.Name.endswith("_back"):
                    pair_name = obj.Name.replace("_back", "_front")
                    pair_obj = doc.getObject(pair_name)
                if pair_obj:
                    all_objects_to_update.append(pair_obj)

            unique_objects = list(dict.fromkeys(all_objects_to_update))

            absorptivity_val = float(self.le_absorptivity.text())
            emissivity_val = float(self.le_emissivity.text())
            transmittance_val = float(self.le_transmittance.text())
            active_side_val = self.combo_active_side.currentText()
            # 裏面選択時も unique_objects に front が含まれるため、常に物理量を読んでおく（未定義で UnboundLocalError にならないように）
            thickness_val = float(self.le_thickness.text())
            density_val = float(self.le_density.text())
            specific_heat_val = float(self.le_specific_heat.text())
            conductivity_val = float(self.le_conductivity.text())

            for obj_to_set in unique_objects:
                if not hasattr(obj_to_set, "SolarAbsorptivity"):
                    obj_to_set.addProperty(
                        "App::PropertyFloat", "SolarAbsorptivity", "Thermal", "太陽光吸収率"
                    )
                if not hasattr(obj_to_set, "InfraredEmissivity"):
                    obj_to_set.addProperty(
                        "App::PropertyFloat", "InfraredEmissivity", "Thermal", "赤外放射率"
                    )
                if not hasattr(obj_to_set, "Transmittance"):
                    obj_to_set.addProperty(
                        "App::PropertyFloat", "Transmittance", "Thermal", "透過率"
                    )
                if not hasattr(obj_to_set, "ActiveSide"):
                    obj_to_set.addProperty(
                        "App::PropertyEnumeration",
                        "ActiveSide",
                        "Thermal",
                        "輻射計算の対象面",
                    )
                    obj_to_set.ActiveSide = self.active_side_options

                obj_to_set.SolarAbsorptivity = absorptivity_val
                obj_to_set.InfraredEmissivity = emissivity_val
                obj_to_set.Transmittance = max(0.0, min(1.0, transmittance_val))
                obj_to_set.ActiveSide = active_side_val

                if not obj_to_set.Name.endswith("_back"):
                    if not hasattr(obj_to_set, "Thickness"):
                        obj_to_set.addProperty(
                            "App::PropertyFloat", "Thickness", "Thermal", "厚み"
                        )
                    if not hasattr(obj_to_set, "Density"):
                        obj_to_set.addProperty(
                            "App::PropertyFloat", "Density", "Thermal", "密度"
                        )
                    if not hasattr(obj_to_set, "SpecificHeat"):
                        obj_to_set.addProperty(
                            "App::PropertyFloat", "SpecificHeat", "Thermal", "比熱"
                        )
                    if not hasattr(obj_to_set, "ThermalConductivity"):
                        obj_to_set.addProperty(
                            "App::PropertyFloat",
                            "ThermalConductivity",
                            "Thermal",
                            "熱伝導率",
                        )
                    obj_to_set.Thickness = thickness_val
                    obj_to_set.Density = density_val
                    obj_to_set.SpecificHeat = specific_heat_val
                    obj_to_set.ThermalConductivity = conductivity_val

            if self.face_group is not None and getattr(self, "surface_number_obj", None) is not None:
                target = self.surface_number_obj
                if not hasattr(target, "SurfaceNumber"):
                    target.addProperty("App::PropertyInteger", "SurfaceNumber", "Thermal", "サーフェース番号")
                target.SurfaceNumber = self.spin_surface_number.value()
            if self.node_obj is not None:
                if not hasattr(self.node_obj, "NodeNumber"):
                    self.node_obj.addProperty("App::PropertyInteger", "NodeNumber", "Thermal", "ノード番号")
                self.node_obj.NodeNumber = self.spin_node_number.value()
                if not hasattr(self.node_obj, "HeatSource"):
                    self.node_obj.addProperty("App::PropertyFloat", "HeatSource", "Thermal", "発熱量 [W]")
                self.node_obj.HeatSource = float(getattr(self, "spin_heat_source", None).value() if hasattr(self, "spin_heat_source") else 0.0)

            FreeCAD.Console.PrintMessage(
                f"{len(unique_objects)}個のオブジェクトのプロパティを更新しました。\n"
            )
            freecad_utils.apply_active_side_visibility(unique_objects)
            doc.recompute()
        except ValueError:
            FreeCAD.Console.PrintError(
                "数値として無効な入力です。プロパティは更新されませんでした。\n"
            )
        except Exception as e:
            FreeCAD.Console.PrintError(f"プロパティの設定中にエラー: {e}\n")

        FreeCADGui.Control.closeDialog()
        # ダイアログ閉鎖後に3Dビューを更新（色を反映）
        def _deferred_visualize():
            from ThermalAnalysis.modeling import core
            core.visualize_active_side()
        QtCore.QTimer.singleShot(0, _deferred_visualize)
        return True


class BulkPropertiesDialog(QtGui.QDialog):
    """
    輻射モデル内の全面に同じ熱物性・光学特性を一括適用するダイアログ。
    選択不要で、FaceGroup 配下の全 Face_*_front / Face_*_back が対象。
    """

    def __init__(self, parent=None):
        super(BulkPropertiesDialog, self).__init__(parent)
        from ThermalAnalysis.modeling import core
        self._core = core
        self.setWindowTitle("面の一括プロパティ設定")
        self.setMinimumWidth(400)
        layout = QtGui.QVBoxLayout(self)

        # 適用範囲（元オブジェクトの輻射モデル単位）
        scope_gb = QtGui.QGroupBox("適用範囲")
        scope_fl = QtGui.QFormLayout(scope_gb)
        self._scope_combo = QtGui.QComboBox()
        self._scope_combo.addItem("モデル全体（全 BaseObject）", None)
        try:
            doc = FreeCAD.ActiveDocument
            base_objects = []
            if doc:
                for g in freecad_utils.get_face_groups(doc):
                    base = getattr(g, "BaseObject", None)
                    if base and base not in base_objects:
                        base_objects.append(base)
            for base in base_objects:
                self._scope_combo.addItem(getattr(base, "Label", getattr(base, "Name", "BaseObject")), base)
        except Exception:
            pass
        scope_fl.addRow("対象:", self._scope_combo)
        layout.addWidget(scope_gb)

        # 熱光学
        optical_gb = QtGui.QGroupBox("熱光学特性")
        optical_fl = QtGui.QFormLayout(optical_gb)
        self.le_absorptivity = QtGui.QLineEdit("0.5")
        self.le_emissivity = QtGui.QLineEdit("0.9")
        self.le_transmittance = QtGui.QLineEdit("0.0")
        self.combo_active_side = QtGui.QComboBox()
        self.combo_active_side.addItems(["両面", "表面", "裏面"])
        optical_fl.addRow("太陽光吸収率 [-]:", self.le_absorptivity)
        optical_fl.addRow("赤外放射率 [-]:", self.le_emissivity)
        optical_fl.addRow("透過率 [-]:", self.le_transmittance)
        optical_fl.addRow("アクティブな面:", self.combo_active_side)
        layout.addWidget(optical_gb)

        # 熱物性（表面メッシュにのみ適用。裏面は光学のみ）
        physical_gb = QtGui.QGroupBox("熱物性（表面メッシュに適用）")
        physical_fl = QtGui.QFormLayout(physical_gb)
        self.le_thickness = QtGui.QLineEdit(str(core._DEFAULT_THICKNESS))
        self.le_density = QtGui.QLineEdit(str(core._DEFAULT_DENSITY))
        self.le_specific_heat = QtGui.QLineEdit(str(core._DEFAULT_SPECIFIC_HEAT))
        self.le_conductivity = QtGui.QLineEdit(str(core._DEFAULT_THERMAL_CONDUCTIVITY))
        physical_fl.addRow("厚み [m]:", self.le_thickness)
        physical_fl.addRow("密度 [kg/m³]:", self.le_density)
        physical_fl.addRow("比熱 [J/kgK]:", self.le_specific_heat)
        physical_fl.addRow("熱伝導率 [W/mK]:", self.le_conductivity)
        layout.addWidget(physical_gb)

        layout.addWidget(QtGui.QLabel("※ 選択した範囲の Face メッシュに上記を適用します。"))
        btn_layout = QtGui.QHBoxLayout()
        btn_layout.addStretch()
        self.btn_apply = QtGui.QPushButton("適用")
        self.btn_cancel = QtGui.QPushButton("キャンセル")
        self.btn_apply.clicked.connect(self._on_apply)
        self.btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_apply)
        btn_layout.addWidget(self.btn_cancel)
        layout.addLayout(btn_layout)

    def _on_apply(self):
        try:
            absorptivity_val = float(self.le_absorptivity.text())
            emissivity_val = float(self.le_emissivity.text())
            transmittance_val = float(self.le_transmittance.text())
            active_side_val = self.combo_active_side.currentText()
            thickness_val = float(self.le_thickness.text())
            density_val = float(self.le_density.text())
            specific_heat_val = float(self.le_specific_heat.text())
            conductivity_val = float(self.le_conductivity.text())
        except ValueError:
            FreeCAD.Console.PrintError("数値として無効な入力があります。\n")
            return
        doc = FreeCAD.ActiveDocument
        if not doc:
            FreeCAD.Console.PrintError("アクティブなドキュメントがありません。\n")
            return
        base_obj = self._scope_combo.currentData()
        if base_obj is None:
            face_groups = None  # 全 BaseObject（従来どおり）
        else:
            all_groups = freecad_utils.get_face_groups(doc)
            face_groups = [g for g in all_groups if getattr(g, "BaseObject", None) is base_obj]
        meshes = self._core.get_face_meshes_for_bulk_properties(doc, face_groups=face_groups)
        if not meshes:
            FreeCAD.Console.PrintError("輻射モデルの面が見つかりません。先にモデル準備を実行してください。\n")
            return
        active_side_options = ["両面", "表面", "裏面"]
        transmittance_val = max(0.0, min(1.0, transmittance_val))
        for obj in meshes:
            if not hasattr(obj, "SolarAbsorptivity"):
                obj.addProperty("App::PropertyFloat", "SolarAbsorptivity", "Thermal", "太陽光吸収率")
            if not hasattr(obj, "InfraredEmissivity"):
                obj.addProperty("App::PropertyFloat", "InfraredEmissivity", "Thermal", "赤外放射率")
            if not hasattr(obj, "Transmittance"):
                obj.addProperty("App::PropertyFloat", "Transmittance", "Thermal", "透過率")
            if not hasattr(obj, "ActiveSide"):
                obj.addProperty(
                    "App::PropertyEnumeration", "ActiveSide", "Thermal", "輻射計算の対象面"
                )
                obj.ActiveSide = active_side_options
            obj.SolarAbsorptivity = absorptivity_val
            obj.InfraredEmissivity = emissivity_val
            obj.Transmittance = transmittance_val
            obj.ActiveSide = active_side_val
            if not obj.Name.endswith("_back"):
                if not hasattr(obj, "Thickness"):
                    obj.addProperty("App::PropertyFloat", "Thickness", "Thermal", "厚み")
                if not hasattr(obj, "Density"):
                    obj.addProperty("App::PropertyFloat", "Density", "Thermal", "密度")
                if not hasattr(obj, "SpecificHeat"):
                    obj.addProperty("App::PropertyFloat", "SpecificHeat", "Thermal", "比熱")
                if not hasattr(obj, "ThermalConductivity"):
                    obj.addProperty(
                        "App::PropertyFloat", "ThermalConductivity", "Thermal", "熱伝導率"
                    )
                obj.Thickness = thickness_val
                obj.Density = density_val
                obj.SpecificHeat = specific_heat_val
                obj.ThermalConductivity = conductivity_val
        freecad_utils.apply_active_side_visibility(meshes)
        doc.recompute()
        scope_label = "モデル全体" if base_obj is None else getattr(base_obj, "Label", getattr(base_obj, "Name", "選択オブジェクト"))
        FreeCAD.Console.PrintMessage(f"{scope_label} の輻射モデルに含まれる {len(meshes)} 個の面プロパティを一括設定しました。\n")
        # ダイアログ閉鎖後に3Dビューの色を更新
        QtCore.QTimer.singleShot(0, self._core.visualize_active_side)
        self.accept()


class MaterialEditorDialog(QtGui.QDialog):
    """
    マテリアルライブラリ編集ダイアログ。
    読み書きは `materials` モジュール経由で行う。
    """

    def __init__(self):
        super(MaterialEditorDialog, self).__init__()

        self.setWindowTitle("マテリアルライブラリ編集")
        self.setMinimumWidth(720)

        self._selected_optical_name = None
        self._selected_physical_name = None

        root = QtGui.QVBoxLayout(self)

        # ==== 熱光学特性 ====
        optical_group = QtGui.QGroupBox("熱光学特性")
        optical_outer = QtGui.QHBoxLayout(optical_group)

        self.optical_list = QtGui.QListWidget()
        self.optical_list.setSelectionMode(QtGui.QAbstractItemView.SingleSelection)
        optical_outer.addWidget(self.optical_list, 2)

        optical_right = QtGui.QWidget()
        optical_right_layout = QtGui.QVBoxLayout(optical_right)
        optical_form = QtGui.QFormLayout()

        self.optical_name = QtGui.QLineEdit()
        optical_form.addRow("名前:", self.optical_name)

        self.optical_abs = QtGui.QDoubleSpinBox()
        self.optical_abs.setDecimals(6)
        self.optical_abs.setRange(0.0, 1.0)
        self.optical_abs.setSingleStep(0.01)
        optical_form.addRow("太陽光吸収率 [-]:", self.optical_abs)

        self.optical_eps = QtGui.QDoubleSpinBox()
        self.optical_eps.setDecimals(6)
        self.optical_eps.setRange(0.0, 1.0)
        self.optical_eps.setSingleStep(0.01)
        optical_form.addRow("赤外放射率 [-]:", self.optical_eps)

        self.optical_trans = QtGui.QDoubleSpinBox()
        self.optical_trans.setDecimals(6)
        self.optical_trans.setRange(0.0, 1.0)
        self.optical_trans.setSingleStep(0.01)
        optical_form.addRow("透過率 [-]:", self.optical_trans)

        optical_right_layout.addLayout(optical_form)

        optical_btns = QtGui.QHBoxLayout()
        self.optical_new_btn = QtGui.QPushButton("新規")
        self.optical_apply_btn = QtGui.QPushButton("適用")
        self.optical_delete_btn = QtGui.QPushButton("削除")
        optical_btns.addWidget(self.optical_new_btn)
        optical_btns.addWidget(self.optical_apply_btn)
        optical_btns.addWidget(self.optical_delete_btn)
        optical_right_layout.addLayout(optical_btns)
        optical_right_layout.addStretch(1)

        optical_outer.addWidget(optical_right, 3)
        root.addWidget(optical_group)

        # ==== 熱物性 ====
        physical_group = QtGui.QGroupBox("熱物性")
        physical_outer = QtGui.QHBoxLayout(physical_group)

        self.physical_list = QtGui.QListWidget()
        self.physical_list.setSelectionMode(QtGui.QAbstractItemView.SingleSelection)
        physical_outer.addWidget(self.physical_list, 2)

        physical_right = QtGui.QWidget()
        physical_right_layout = QtGui.QVBoxLayout(physical_right)
        physical_form = QtGui.QFormLayout()

        self.physical_name = QtGui.QLineEdit()
        physical_form.addRow("名前:", self.physical_name)

        self.physical_thickness = QtGui.QDoubleSpinBox()
        self.physical_thickness.setDecimals(9)
        self.physical_thickness.setRange(0.0, 1e3)
        self.physical_thickness.setSingleStep(0.001)
        physical_form.addRow("厚み [m]:", self.physical_thickness)

        self.physical_density = QtGui.QDoubleSpinBox()
        self.physical_density.setDecimals(3)
        self.physical_density.setRange(0.0, 1e9)
        self.physical_density.setSingleStep(10.0)
        physical_form.addRow("密度 [kg/m3]:", self.physical_density)

        self.physical_cp = QtGui.QDoubleSpinBox()
        self.physical_cp.setDecimals(3)
        self.physical_cp.setRange(0.0, 1e9)
        self.physical_cp.setSingleStep(10.0)
        physical_form.addRow("比熱 [J/kgK]:", self.physical_cp)

        self.physical_k = QtGui.QDoubleSpinBox()
        self.physical_k.setDecimals(6)
        self.physical_k.setRange(0.0, 1e9)
        self.physical_k.setSingleStep(1.0)
        physical_form.addRow("熱伝導率 [W/mK]:", self.physical_k)

        physical_right_layout.addLayout(physical_form)

        physical_btns = QtGui.QHBoxLayout()
        self.physical_new_btn = QtGui.QPushButton("新規")
        self.physical_apply_btn = QtGui.QPushButton("適用")
        self.physical_delete_btn = QtGui.QPushButton("削除")
        physical_btns.addWidget(self.physical_new_btn)
        physical_btns.addWidget(self.physical_apply_btn)
        physical_btns.addWidget(self.physical_delete_btn)
        physical_right_layout.addLayout(physical_btns)
        physical_right_layout.addStretch(1)

        physical_outer.addWidget(physical_right, 3)
        root.addWidget(physical_group)

        # OK / Cancel
        self.button_box = QtGui.QDialogButtonBox(
            QtGui.QDialogButtonBox.Ok | QtGui.QDialogButtonBox.Cancel
        )
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        root.addWidget(self.button_box)

        # signals
        self.optical_list.currentItemChanged.connect(self._on_optical_selected)
        self.physical_list.currentItemChanged.connect(self._on_physical_selected)

        self.optical_new_btn.clicked.connect(self._on_optical_new)
        self.optical_apply_btn.clicked.connect(self._on_optical_apply)
        self.optical_delete_btn.clicked.connect(self._on_optical_delete)

        self.physical_new_btn.clicked.connect(self._on_physical_new)
        self.physical_apply_btn.clicked.connect(self._on_physical_apply)
        self.physical_delete_btn.clicked.connect(self._on_physical_delete)

        self._reload_lists(select_defaults=True)

    def _message(self, title, text, icon=QtGui.QMessageBox.Information):
        msg = QtGui.QMessageBox(self)
        msg.setIcon(icon)
        msg.setWindowTitle(title)
        msg.setText(text)
        msg.exec_()

    def _confirm(self, title, text):
        return (
            QtGui.QMessageBox.question(
                self,
                title,
                text,
                QtGui.QMessageBox.Yes | QtGui.QMessageBox.No,
                QtGui.QMessageBox.No,
            )
            == QtGui.QMessageBox.Yes
        )

    def _reload_lists(self, select_defaults=False):
        self.optical_list.blockSignals(True)
        self.physical_list.blockSignals(True)
        try:
            self.optical_list.clear()
            for name in materials.list_optical_names():
                self.optical_list.addItem(name)

            self.physical_list.clear()
            for name in materials.list_physical_names():
                self.physical_list.addItem(name)
        finally:
            self.optical_list.blockSignals(False)
            self.physical_list.blockSignals(False)

        if select_defaults:
            if self.optical_list.count() > 0:
                self.optical_list.setCurrentRow(0)
            else:
                self._on_optical_new()
            if self.physical_list.count() > 0:
                self.physical_list.setCurrentRow(0)
            else:
                self._on_physical_new()

    # ==== optical handlers ====
    def _on_optical_selected(self, current, previous):
        if current is None:
            self._selected_optical_name = None
            return
        name = current.text()
        self._selected_optical_name = name
        data = materials.get_optical(name) or {}
        self.optical_name.setText(name)
        self.optical_abs.setValue(float(data.get("solar_absorptivity", 0.0)))
        self.optical_eps.setValue(float(data.get("infrared_emissivity", 0.0)))
        self.optical_trans.setValue(float(data.get("transmittance", 0.0)))

    def _on_optical_new(self):
        self._selected_optical_name = None
        self.optical_list.clearSelection()
        self.optical_name.setText("")
        self.optical_abs.setValue(0.0)
        self.optical_eps.setValue(0.0)
        self.optical_trans.setValue(0.0)
        self.optical_name.setFocus()

    def _on_optical_apply(self):
        name = self.optical_name.text().strip()
        if not name:
            self._message("入力エラー", "名前を入力してください。", QtGui.QMessageBox.Warning)
            return

        abs_val = float(self.optical_abs.value())
        eps_val = float(self.optical_eps.value())
        trans_val = max(0.0, min(1.0, float(self.optical_trans.value())))

        try:
            materials.upsert_optical(name, abs_val, eps_val, trans_val)
            if self._selected_optical_name and self._selected_optical_name != name:
                materials.delete_optical(self._selected_optical_name)
            self._reload_lists(select_defaults=False)
            matches = self.optical_list.findItems(name, QtCore.Qt.MatchExactly)
            if matches:
                self.optical_list.setCurrentItem(matches[0])
            self._message("保存", "熱光学特性を保存しました。")
        except Exception as e:
            self._message("保存エラー", f"保存に失敗しました: {e}", QtGui.QMessageBox.Critical)

    def _on_optical_delete(self):
        name = self.optical_name.text().strip()
        if not name:
            self._message("削除", "削除する名前を選択してください。", QtGui.QMessageBox.Warning)
            return
        if not self._confirm("削除確認", f"'{name}' を削除しますか？"):
            return
        try:
            materials.delete_optical(name)
            self._reload_lists(select_defaults=True)
            self._message("削除", "削除しました。")
        except Exception as e:
            self._message("削除エラー", f"削除に失敗しました: {e}", QtGui.QMessageBox.Critical)

    # ==== physical handlers ====
    def _on_physical_selected(self, current, previous):
        if current is None:
            self._selected_physical_name = None
            return
        name = current.text()
        self._selected_physical_name = name
        data = materials.get_physical(name) or {}
        self.physical_name.setText(name)
        self.physical_thickness.setValue(float(data.get("thickness", 0.0)))
        self.physical_density.setValue(float(data.get("density", 0.0)))
        self.physical_cp.setValue(float(data.get("specific_heat", 0.0)))
        self.physical_k.setValue(float(data.get("thermal_conductivity", 0.0)))

    def _on_physical_new(self):
        self._selected_physical_name = None
        self.physical_list.clearSelection()
        self.physical_name.setText("")
        self.physical_thickness.setValue(0.0)
        self.physical_density.setValue(0.0)
        self.physical_cp.setValue(0.0)
        self.physical_k.setValue(0.0)
        self.physical_name.setFocus()

    def _on_physical_apply(self):
        name = self.physical_name.text().strip()
        if not name:
            self._message("入力エラー", "名前を入力してください。", QtGui.QMessageBox.Warning)
            return

        thickness = float(self.physical_thickness.value())
        density = float(self.physical_density.value())
        cp = float(self.physical_cp.value())
        k = float(self.physical_k.value())

        try:
            materials.upsert_physical(name, thickness, density, cp, k)
            if self._selected_physical_name and self._selected_physical_name != name:
                materials.delete_physical(self._selected_physical_name)
            self._reload_lists(select_defaults=False)
            matches = self.physical_list.findItems(name, QtCore.Qt.MatchExactly)
            if matches:
                self.physical_list.setCurrentItem(matches[0])
            self._message("保存", "熱物性を保存しました。")
        except Exception as e:
            self._message("保存エラー", f"保存に失敗しました: {e}", QtGui.QMessageBox.Critical)

    def _on_physical_delete(self):
        name = self.physical_name.text().strip()
        if not name:
            self._message("削除", "削除する名前を選択してください。", QtGui.QMessageBox.Warning)
            return
        if not self._confirm("削除確認", f"'{name}' を削除しますか？"):
            return
        try:
            materials.delete_physical(name)
            self._reload_lists(select_defaults=True)
            self._message("削除", "削除しました。")
        except Exception as e:
            self._message("削除エラー", f"削除に失敗しました: {e}", QtGui.QMessageBox.Critical)


class PrepareModelDialog(QtGui.QDialog):
    """
    モデル準備実行時にメッシュ細分化パラメータを指定するダイアログ。
    """

    def __init__(self, parent=None):
        super(PrepareModelDialog, self).__init__(parent)
        self.setWindowTitle("モデルを準備")
        layout = QtGui.QFormLayout(self)
        info = QtGui.QLabel("オブジェクトのみ選択時は全面を変換します。面をサブ選択している場合は選択した面のみ変換されます。")
        info.setWordWrap(True)
        layout.addRow(info)
        self.linear_deflection = QtGui.QDoubleSpinBox()
        self.linear_deflection.setDecimals(4)
        self.linear_deflection.setRange(0.0001, 100.0)
        self.linear_deflection.setValue(0.1)
        self.linear_deflection.setSuffix(" mm")
        layout.addRow("LinearDeflection (許容偏差):", self.linear_deflection)
        self.angular_deflection = QtGui.QDoubleSpinBox()
        self.angular_deflection.setDecimals(2)
        self.angular_deflection.setRange(0.1, 180.0)
        self.angular_deflection.setValue(28.5)
        self.angular_deflection.setSuffix(" deg")
        layout.addRow("AngularDeflection (角度許容):", self.angular_deflection)
        # ソリッドあたり1ノードにまとめるオプション
        self.check_one_node_per_solid = QtGui.QCheckBox("ソリッドあたり1ノードにまとめる")
        self.check_one_node_per_solid.setChecked(False)
        layout.addRow("", self.check_one_node_per_solid)
        self.button_box = QtGui.QDialogButtonBox(
            QtGui.QDialogButtonBox.Ok | QtGui.QDialogButtonBox.Cancel
        )
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addRow(self.button_box)

    def get_values(self):
        # 既存APIとの互換のため、将来拡張時もタプル順序を維持する
        return (
            self.linear_deflection.value(),
            self.angular_deflection.value(),
            self.check_one_node_per_solid.isChecked(),
        )


class DefeaturingDialog(QtGui.QDialog):
    """
    形状の簡略化（穴・フィレット削除）のパラメータを指定するダイアログ。
    削除する穴の最大直径 [mm] とフィレットの最大 R [mm] を入力する。
    """

    def __init__(self, parent=None):
        super(DefeaturingDialog, self).__init__(parent)
        self.setWindowTitle("形状の簡略化（穴・フィレット削除）")
        layout = QtGui.QFormLayout(self)
        info = QtGui.QLabel("選択したオブジェクトから、指定以下の穴とフィレットを削除した新しい形状を作成します。")
        info.setWordWrap(True)
        layout.addRow(info)
        self.hole_max_diameter = QtGui.QDoubleSpinBox()
        self.hole_max_diameter.setDecimals(2)
        self.hole_max_diameter.setRange(0.01, 1000.0)
        self.hole_max_diameter.setValue(6.5)
        self.hole_max_diameter.setSuffix(" mm")
        layout.addRow("削除する穴の最大直径:", self.hole_max_diameter)
        self.fillet_max_radius = QtGui.QDoubleSpinBox()
        self.fillet_max_radius.setDecimals(2)
        self.fillet_max_radius.setRange(0.0, 1000.0)
        self.fillet_max_radius.setValue(4.0)
        self.fillet_max_radius.setSuffix(" mm")
        layout.addRow("削除するフィレットの最大 R:", self.fillet_max_radius)
        self.button_box = QtGui.QDialogButtonBox(
            QtGui.QDialogButtonBox.Ok | QtGui.QDialogButtonBox.Cancel
        )
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addRow(self.button_box)

    def get_values(self):
        """(hole_max_diameter_mm, fillet_max_radius_mm) を返す"""
        return (self.hole_max_diameter.value(), self.fillet_max_radius.value())


class DisplayOptionsDialog(QtGui.QDialog):
    """
    表示モードを排他的に選択するダイアログ。
    アクティブ面・吸収率・放射率・透過率・デフォルトのいずれか一つを選ぶ。
    伝熱・輻射コンダクタンスの表示/非表示、面番号・ノード番号ラベルの表示/非表示も切り替え可能。
    ラベルの文字サイズとオフセット距離は「表示・伝導パラメータ設定」で変更できます。
    """
    def __init__(self, parent=None):
        super(DisplayOptionsDialog, self).__init__(parent)
        self.setWindowTitle("表示設定")
        layout = QtGui.QVBoxLayout(self)
        self._btn_group = QtGui.QButtonGroup(self)
        self._btn_group.setExclusive(True)
        btn_active = QtGui.QPushButton("アクティブ面")
        btn_abs = QtGui.QPushButton("吸収率")
        btn_emis = QtGui.QPushButton("放射率")
        btn_trans = QtGui.QPushButton("透過率")
        btn_default = QtGui.QPushButton("デフォルト")
        for btn in (btn_active, btn_abs, btn_emis, btn_trans, btn_default):
            btn.setCheckable(True)
            self._btn_group.addButton(btn)
        btn_default.setChecked(True)
        layout.addWidget(QtGui.QLabel("表示モード（いずれか一つ）:"))
        layout.addWidget(btn_active)
        layout.addWidget(btn_abs)
        layout.addWidget(btn_emis)
        layout.addWidget(btn_trans)
        layout.addWidget(btn_default)
        btn_active.clicked.connect(self._on_active)
        btn_abs.clicked.connect(self._on_absorptivity)
        btn_emis.clicked.connect(self._on_emissivity)
        btn_trans.clicked.connect(self._on_transmittance)
        btn_default.clicked.connect(self._on_default)
        # ノードの表示・非表示
        layout.addSpacing(8)
        self._check_nodes = QtGui.QCheckBox("ノードを表示")
        self._check_nodes.setChecked(True)
        self._check_nodes.toggled.connect(self._on_node_toggled)
        layout.addWidget(self._check_nodes)
        # コンダクタンスの表示・非表示
        layout.addSpacing(4)
        layout.addWidget(QtGui.QLabel("コンダクタンス:"))
        self._check_conduction = QtGui.QCheckBox("伝熱コンダクタンスを表示")
        self._check_conduction.setChecked(True)
        self._check_conduction.toggled.connect(self._on_conduction_toggled)
        layout.addWidget(self._check_conduction)
        self._check_radiation = QtGui.QCheckBox("輻射コンダクタンスを表示")
        self._check_radiation.setChecked(True)
        self._check_radiation.toggled.connect(self._on_radiation_toggled)
        layout.addWidget(self._check_radiation)
        # 番号ラベルの表示・非表示
        layout.addSpacing(8)
        layout.addWidget(QtGui.QLabel("番号ラベル:"))
        self._check_surface_numbers = QtGui.QCheckBox("面番号を表示")
        self._check_surface_numbers.setChecked(False)
        self._check_surface_numbers.toggled.connect(self._on_surface_numbers_toggled)
        layout.addWidget(self._check_surface_numbers)
        self._check_node_numbers = QtGui.QCheckBox("ノード番号を表示")
        self._check_node_numbers.setChecked(False)
        self._check_node_numbers.toggled.connect(self._on_node_numbers_toggled)
        layout.addWidget(self._check_node_numbers)
        hint = QtGui.QLabel("文字サイズ・オフセット距離は「表示・伝導パラメータ設定」で変更できます。")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray; font-size: 10px;")
        layout.addWidget(hint)
        self.button_box = QtGui.QDialogButtonBox(QtGui.QDialogButtonBox.Close)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

    def showEvent(self, event):
        """ダイアログ表示時に現在の表示状態を反映する。"""
        super(DisplayOptionsDialog, self).showEvent(event)
        from ThermalAnalysis.modeling import core
        vis_nodes, has_nodes = core.get_node_visibility()
        self._check_nodes.setChecked(vis_nodes)
        self._check_nodes.setEnabled(has_nodes)
        vis_cond, has_cond = core.get_conduction_conductance_visibility()
        vis_rad, has_rad = core.get_radiation_conductance_visibility()
        self._check_conduction.setChecked(vis_cond)
        self._check_radiation.setChecked(vis_rad)
        self._check_conduction.setEnabled(has_cond)
        self._check_radiation.setEnabled(has_rad)
        # 番号ラベルグループの現在の Visibility を反映
        import FreeCAD as _FC
        doc = _FC.ActiveDocument
        if doc and _FC.GuiUp:
            surf_group = doc.getObject("RA_SurfaceNumberLabels")
            node_group = doc.getObject("RA_NodeNumberLabels")
            surf_vis = bool(surf_group and hasattr(surf_group, "ViewObject")
                            and getattr(surf_group.ViewObject, "Visibility", False))
            node_vis = bool(node_group and hasattr(node_group, "ViewObject")
                            and getattr(node_group.ViewObject, "Visibility", False))
            self._check_surface_numbers.blockSignals(True)
            self._check_surface_numbers.setChecked(surf_vis)
            self._check_surface_numbers.blockSignals(False)
            self._check_node_numbers.blockSignals(True)
            self._check_node_numbers.setChecked(node_vis)
            self._check_node_numbers.blockSignals(False)

    def _on_node_toggled(self, checked):
        from ThermalAnalysis.modeling import core
        core.set_node_visibility(checked)

    def _on_conduction_toggled(self, checked):
        from ThermalAnalysis.modeling import core
        core.set_conduction_conductance_visibility(checked)

    def _on_radiation_toggled(self, checked):
        from ThermalAnalysis.modeling import core
        core.set_radiation_conductance_visibility(checked)

    def _on_surface_numbers_toggled(self, checked):
        from ThermalAnalysis.modeling import core
        core.run_show_surface_numbers(checked)

    def _on_node_numbers_toggled(self, checked):
        from ThermalAnalysis.modeling import core
        core.run_show_node_numbers(checked)

    def _on_active(self):
        from ThermalAnalysis.modeling import core
        core.visualize_active_side()

    def _on_absorptivity(self):
        from ThermalAnalysis.modeling import core
        core.visualize_property_contour("SolarAbsorptivity", "太陽光吸収率")

    def _on_emissivity(self):
        from ThermalAnalysis.modeling import core
        core.visualize_property_contour("InfraredEmissivity", "赤外放射率")

    def _on_transmittance(self):
        from ThermalAnalysis.modeling import core
        core.visualize_property_contour("Transmittance", "透過率")

    def _on_default(self):
        from ThermalAnalysis.modeling import core
        core.restore_default_display()


class DisplayParametersSettingsDialog(QtGui.QDialog):
    """
    ノード表示・コンダクタンス線・伝導コンダクタンスのペア選定パラメータを設定するダイアログ。
    設定は FreeCAD のユーザー設定 (Mod/ThermalAnalysis) に保存され、次回以降の計算・表示に反映される。
    """
    _PREFS = "User parameter:Base/App/Preferences/Mod/ThermalAnalysis"

    def __init__(self, parent=None):
        super(DisplayParametersSettingsDialog, self).__init__(parent)
        self.setWindowTitle("表示・伝導パラメータ設定")
        layout = QtGui.QVBoxLayout(self)

        # --- ノード表示 ---
        gb_node = QtGui.QGroupBox("ノード表示")
        form_node = QtGui.QFormLayout(gb_node)
        self.spin_node_point_size_default = QtGui.QSpinBox()
        self.spin_node_point_size_default.setRange(1, 50)
        self.spin_node_point_size_default.setSuffix(" px")
        form_node.addRow("デフォルト PointSize（共有・面ノード）:", self.spin_node_point_size_default)
        self.spin_node_point_size_sub = QtGui.QSpinBox()
        self.spin_node_point_size_sub.setRange(1, 50)
        self.spin_node_point_size_sub.setSuffix(" px")
        form_node.addRow("PointSize（分割サブノード）:", self.spin_node_point_size_sub)
        self.spin_node_sphere_fraction_face = QtGui.QDoubleSpinBox()
        self.spin_node_sphere_fraction_face.setRange(0.01, 0.50)
        self.spin_node_sphere_fraction_face.setDecimals(3)
        self.spin_node_sphere_fraction_face.setSingleStep(0.01)
        form_node.addRow("ノード球サイズ（面基準 100%時、面対角線の割合）:", self.spin_node_sphere_fraction_face)
        self.spin_node_sphere_fraction_global = QtGui.QDoubleSpinBox()
        self.spin_node_sphere_fraction_global.setRange(0.005, 0.20)
        self.spin_node_sphere_fraction_global.setDecimals(3)
        self.spin_node_sphere_fraction_global.setSingleStep(0.005)
        form_node.addRow("ノード球サイズ（全体基準 100%時、全体対角線の割合）:", self.spin_node_sphere_fraction_global)
        self.spin_node_radius_min = QtGui.QDoubleSpinBox()
        self.spin_node_radius_min.setRange(0.1, 100.0)
        self.spin_node_radius_min.setDecimals(2)
        self.spin_node_radius_min.setSuffix(" mm")
        form_node.addRow("球半径の最小値:", self.spin_node_radius_min)
        self.spin_node_radius_max = QtGui.QDoubleSpinBox()
        self.spin_node_radius_max.setRange(1.0, 2000.0)
        self.spin_node_radius_max.setDecimals(1)
        self.spin_node_radius_max.setSuffix(" mm")
        form_node.addRow("球半径の最大値:", self.spin_node_radius_max)
        self.spin_node_point_size_divisor = QtGui.QDoubleSpinBox()
        self.spin_node_point_size_divisor.setRange(0.5, 5.0)
        self.spin_node_point_size_divisor.setDecimals(2)
        form_node.addRow("表示設定でノードサイズ適用時の PointSize 係数 (半径/此値):", self.spin_node_point_size_divisor)
        layout.addWidget(gb_node)

        # --- コンダクタンス線表示 ---
        gb_line = QtGui.QGroupBox("コンダクタンス線表示")
        form_line = QtGui.QFormLayout(gb_line)
        self.spin_conductance_line_width = QtGui.QDoubleSpinBox()
        self.spin_conductance_line_width.setRange(0.5, 10.0)
        self.spin_conductance_line_width.setDecimals(1)
        self.spin_conductance_line_width.setSuffix(" px")
        form_line.addRow("線の太さ:", self.spin_conductance_line_width)
        form_line.addRow(QtGui.QLabel("伝熱コンダクタンスの色 (R, G, B):"))
        h_conduction = QtGui.QHBoxLayout()
        self.spin_conduction_r = QtGui.QDoubleSpinBox()
        self.spin_conduction_r.setRange(0.0, 1.0)
        self.spin_conduction_r.setDecimals(2)
        self.spin_conduction_g = QtGui.QDoubleSpinBox()
        self.spin_conduction_g.setRange(0.0, 1.0)
        self.spin_conduction_g.setDecimals(2)
        self.spin_conduction_b = QtGui.QDoubleSpinBox()
        self.spin_conduction_b.setRange(0.0, 1.0)
        self.spin_conduction_b.setDecimals(2)
        h_conduction.addWidget(self.spin_conduction_r)
        h_conduction.addWidget(self.spin_conduction_g)
        h_conduction.addWidget(self.spin_conduction_b)
        form_line.addRow(h_conduction)
        form_line.addRow(QtGui.QLabel("輻射コンダクタンスの色 (R, G, B):"))
        h_radiation = QtGui.QHBoxLayout()
        self.spin_radiation_r = QtGui.QDoubleSpinBox()
        self.spin_radiation_r.setRange(0.0, 1.0)
        self.spin_radiation_r.setDecimals(2)
        self.spin_radiation_g = QtGui.QDoubleSpinBox()
        self.spin_radiation_g.setRange(0.0, 1.0)
        self.spin_radiation_g.setDecimals(2)
        self.spin_radiation_b = QtGui.QDoubleSpinBox()
        self.spin_radiation_b.setRange(0.0, 1.0)
        self.spin_radiation_b.setDecimals(2)
        h_radiation.addWidget(self.spin_radiation_r)
        h_radiation.addWidget(self.spin_radiation_g)
        h_radiation.addWidget(self.spin_radiation_b)
        form_line.addRow(h_radiation)
        layout.addWidget(gb_line)

        # --- 伝導コンダクタンス（ペア選定） ---
        gb_cond = QtGui.QGroupBox("伝導コンダクタンス（異なる面同士）")
        form_cond = QtGui.QFormLayout(gb_cond)
        self.spin_edge_node_tolerance = QtGui.QDoubleSpinBox()
        self.spin_edge_node_tolerance.setRange(0.5, 50.0)
        self.spin_edge_node_tolerance.setDecimals(1)
        self.spin_edge_node_tolerance.setSuffix(" mm")
        self.spin_edge_node_tolerance.setToolTip("共有エッジからこの距離以内のノードを「稜線上」とみなし、ペアにして伝熱コンダクタンスを作成します。")
        form_cond.addRow("稜線付近ノードの許容距離:", self.spin_edge_node_tolerance)
        layout.addWidget(gb_cond)

        # --- 番号ラベル ---
        gb_label = QtGui.QGroupBox("番号ラベル（面番号 / ノード番号）")
        form_label = QtGui.QFormLayout(gb_label)
        self.spin_label_scale_percent = QtGui.QSpinBox()
        self.spin_label_scale_percent.setRange(10, 500)
        self.spin_label_scale_percent.setSuffix(" %")
        self.spin_label_scale_percent.setToolTip(
            "ラベルの文字サイズ倍率。100% で面の対角線サイズの約 20% を基準サイズとします。"
        )
        form_label.addRow("文字サイズ:", self.spin_label_scale_percent)
        self.spin_label_offset_mm = QtGui.QDoubleSpinBox()
        self.spin_label_offset_mm.setRange(0.0, 200.0)
        self.spin_label_offset_mm.setDecimals(1)
        self.spin_label_offset_mm.setSuffix(" mm")
        self.spin_label_offset_mm.setToolTip(
            "面/ノードの法線方向への追加オフセット距離。\n"
            "0 mm: ノード球の縁にラベルを配置（デフォルト）。\n"
            "値を増やすとラベルが面から離れます。"
        )
        form_label.addRow("法線方向オフセット:", self.spin_label_offset_mm)
        layout.addWidget(gb_label)

        self.button_box = QtGui.QDialogButtonBox(
            QtGui.QDialogButtonBox.Ok | QtGui.QDialogButtonBox.Apply | QtGui.QDialogButtonBox.Cancel
        )
        self.button_box.accepted.connect(self._save_and_accept)
        self.button_box.button(QtGui.QDialogButtonBox.Apply).clicked.connect(self._apply)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

        self._load_prefs()

    def _prefs(self):
        return FreeCAD.ParamGet(self._PREFS)

    def _load_prefs(self):
        p = self._prefs()
        self.spin_node_point_size_default.setValue(p.GetInt("NodePointSizeDefault", 14))
        self.spin_node_point_size_sub.setValue(p.GetInt("NodePointSizeSub", 10))
        self.spin_node_sphere_fraction_face.setValue(p.GetFloat("NodeSphereFractionFace", 0.12))
        self.spin_node_sphere_fraction_global.setValue(p.GetFloat("NodeSphereFractionGlobal", 0.03))
        self.spin_node_radius_min.setValue(p.GetFloat("NodeSphereRadiusMinMm", 0.5))
        self.spin_node_radius_max.setValue(p.GetFloat("NodeSphereRadiusMaxMm", 500.0))
        self.spin_node_point_size_divisor.setValue(p.GetFloat("NodePointSizeDivisor", 1.2))
        self.spin_conductance_line_width.setValue(p.GetFloat("ConductanceLineWidth", 2.5))
        self.spin_conduction_r.setValue(p.GetFloat("ConductionLineColorR", 0.2))
        self.spin_conduction_g.setValue(p.GetFloat("ConductionLineColorG", 0.5))
        self.spin_conduction_b.setValue(p.GetFloat("ConductionLineColorB", 1.0))
        self.spin_radiation_r.setValue(p.GetFloat("RadiationLineColorR", 1.0))
        self.spin_radiation_g.setValue(p.GetFloat("RadiationLineColorG", 0.35))
        self.spin_radiation_b.setValue(p.GetFloat("RadiationLineColorB", 0.0))
        self.spin_edge_node_tolerance.setValue(p.GetFloat("EdgeNodeToleranceMm", 5.0))
        self.spin_label_scale_percent.setValue(p.GetInt("LabelScalePercent", 100))
        self.spin_label_offset_mm.setValue(p.GetFloat("LabelOffsetMm", 0.0))

    def _save_prefs(self):
        p = self._prefs()
        p.SetInt("NodePointSizeDefault", self.spin_node_point_size_default.value())
        p.SetInt("NodePointSizeSub", self.spin_node_point_size_sub.value())
        p.SetFloat("NodeSphereFractionFace", self.spin_node_sphere_fraction_face.value())
        p.SetFloat("NodeSphereFractionGlobal", self.spin_node_sphere_fraction_global.value())
        p.SetFloat("NodeSphereRadiusMinMm", self.spin_node_radius_min.value())
        p.SetFloat("NodeSphereRadiusMaxMm", self.spin_node_radius_max.value())
        p.SetFloat("NodePointSizeDivisor", self.spin_node_point_size_divisor.value())
        p.SetFloat("ConductanceLineWidth", self.spin_conductance_line_width.value())
        p.SetFloat("ConductionLineColorR", self.spin_conduction_r.value())
        p.SetFloat("ConductionLineColorG", self.spin_conduction_g.value())
        p.SetFloat("ConductionLineColorB", self.spin_conduction_b.value())
        p.SetFloat("RadiationLineColorR", self.spin_radiation_r.value())
        p.SetFloat("RadiationLineColorG", self.spin_radiation_g.value())
        p.SetFloat("RadiationLineColorB", self.spin_radiation_b.value())
        p.SetFloat("EdgeNodeToleranceMm", self.spin_edge_node_tolerance.value())
        p.SetInt("LabelScalePercent", self.spin_label_scale_percent.value())
        p.SetFloat("LabelOffsetMm", self.spin_label_offset_mm.value())

    def _apply(self):
        self._save_prefs()
        FreeCAD.Console.PrintMessage("表示・伝導パラメータを保存しました。新規作成するノード・リンクに反映されます。既存の伝熱/輻射コンダクタンスは再計算で反映されます。\n")

    def _save_and_accept(self):
        self._save_prefs()
        self.accept()


class RadiationParamsDialog(QtGui.QDialog):
    """
    輻射コンダクタンス計算のパラメータ設定。
    1パッチあたりのレイ数でビューファクターの精度を変更できる。
    """
    def __init__(self, parent=None):
        super(RadiationParamsDialog, self).__init__(parent)
        self.setWindowTitle("輻射計算パラメータ")
        layout = QtGui.QFormLayout(self)
        self.spin_rays_per_patch = QtGui.QSpinBox()
        self.spin_rays_per_patch.setRange(100, 500000)
        self.spin_rays_per_patch.setValue(2000)
        self.spin_rays_per_patch.setSuffix(" 本")
        self.spin_rays_per_patch.setToolTip("各パッチから発射するレイ数。多いほど精度が上がりますが計算時間が増えます。")
        layout.addRow("1パッチあたりのレイ数:", self.spin_rays_per_patch)
        self.button_box = QtGui.QDialogButtonBox(
            QtGui.QDialogButtonBox.Ok | QtGui.QDialogButtonBox.Cancel
        )
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addRow(self.button_box)

    def get_rays_per_patch(self):
        return self.spin_rays_per_patch.value()


class ThermalModelExportDialog(QtGui.QDialog):
    """
    Thermal Model Export: HEADER OPTIONS DATA / HEADER CONTROL DATA を定義し、.inp を出力する。
    """
    def __init__(self, parent=None):
        super(ThermalModelExportDialog, self).__init__(parent)
        self.setWindowTitle("Thermal Model Export")
        layout = QtGui.QFormLayout(self)

        # HEADER OPTIONS DATA
        group_opt = QtGui.QGroupBox("HEADER OPTIONS DATA")
        opt_layout = QtGui.QFormLayout(group_opt)
        self.check_output_dq = QtGui.QCheckBox("各ノードの熱流出入量 (OUTPUT.DQ) を出力")
        self.check_output_dq.setChecked(False)
        opt_layout.addRow("", self.check_output_dq)
        self.check_output_graph = QtGui.QCheckBox("温度推移グラフ (OUTPUT.GRAPH) を描画・保存")
        self.check_output_graph.setChecked(False)
        opt_layout.addRow("", self.check_output_graph)
        layout.addRow(group_opt)

        # HEADER CONTROL DATA
        group_ctrl = QtGui.QGroupBox("HEADER CONTROL DATA")
        ctrl_layout = QtGui.QFormLayout(group_ctrl)
        self.le_timestart = QtGui.QLineEdit("0")
        ctrl_layout.addRow("TIMESTART [秒]:", self.le_timestart)
        self.le_timend = QtGui.QLineEdit("3600")
        ctrl_layout.addRow("TIMEND [秒]:", self.le_timend)
        self.le_dt = QtGui.QLineEdit("60")
        ctrl_layout.addRow("DT [秒]:", self.le_dt)
        self.le_time_step = QtGui.QLineEdit("1")
        ctrl_layout.addRow("TIME_STEP [秒]:", self.le_time_step)
        self.le_stefan_boltzmann = QtGui.QLineEdit("5.67e-8")
        ctrl_layout.addRow("STEFAN_BOLTZMANN:", self.le_stefan_boltzmann)
        self.combo_analysis = QtGui.QComboBox()
        self.combo_analysis.addItems(["STEADY", "STEADY_THEN_TRANSIENT", "TRANSIENT"])
        ctrl_layout.addRow("ANALYSIS:", self.combo_analysis)
        self.combo_steady_solver = QtGui.QComboBox()
        self.combo_steady_solver.addItems(["PICARD", "CNFRW"])
        ctrl_layout.addRow("STEADY_SOLVER:", self.combo_steady_solver)
        self.combo_transient_method = QtGui.QComboBox()
        self.combo_transient_method.addItems(["EXPLICIT", "CRANK_NICOLSON", "BACKWARD"])
        ctrl_layout.addRow("TRANSIENT_METHOD:", self.combo_transient_method)
        self.le_save_final = QtGui.QLineEdit("TRUE")
        self.le_save_final.setPlaceholderText("TRUE またはファイルパス")
        ctrl_layout.addRow("SAVE_FINAL_TEMPERATURE:", self.le_save_final)
        self.le_initial_temp_file = QtGui.QLineEdit("")
        self.le_initial_temp_file.setPlaceholderText("過渡解析の初期温度CSV（任意）")
        ctrl_layout.addRow("INITIAL_TEMPERATURE_FILE:", self.le_initial_temp_file)
        layout.addRow(group_ctrl)

        # ノード初期温度（NODE DATA 用）
        self.spin_initial_temperature = QtGui.QDoubleSpinBox()
        self.spin_initial_temperature.setRange(-273.15, 10000)
        self.spin_initial_temperature.setValue(20.0)
        self.spin_initial_temperature.setSuffix(" ℃")
        layout.addRow("ノード初期温度 [℃]:", self.spin_initial_temperature)

        self.button_box = QtGui.QDialogButtonBox(
            QtGui.QDialogButtonBox.Ok | QtGui.QDialogButtonBox.Cancel
        )
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addRow(self.button_box)

    def get_options_data(self):
        return {
            "OUTPUT.DQ": "TRUE" if self.check_output_dq.isChecked() else "FALSE",
            "OUTPUT.GRAPH": "TRUE" if self.check_output_graph.isChecked() else "FALSE",
        }

    def get_control_data(self):
        d = {
            "TIMESTART": self.le_timestart.text().strip() or "0",
            "TIMEND": self.le_timend.text().strip() or "3600",
            "DT": self.le_dt.text().strip() or "60",
            "TIME_STEP": self.le_time_step.text().strip() or "1",
            "STEFAN_BOLTZMANN": self.le_stefan_boltzmann.text().strip() or "5.67e-8",
            "ANALYSIS": self.combo_analysis.currentText(),
            "STEADY_SOLVER": self.combo_steady_solver.currentText(),
            "TRANSIENT_METHOD": self.combo_transient_method.currentText(),
            "SAVE_FINAL_TEMPERATURE": self.le_save_final.text().strip() or "TRUE",
        }
        if self.le_initial_temp_file.text().strip():
            d["INITIAL_TEMPERATURE_FILE"] = self.le_initial_temp_file.text().strip()
        return d

    def get_initial_temperature(self):
        return self.spin_initial_temperature.value()


class PostProcessingDialog(QtGui.QDialog):
    """
    熱解析 .out ファイルを読み込み、ノード温度をコンター表示する。
    過渡解析の複数時刻の切替と、温度表示範囲（最小・最大）の指定に対応。
    """
    def __init__(self, parent=None):
        super(PostProcessingDialog, self).__init__(parent)
        self.setWindowTitle("Post Processing - 温度結果表示")
        self._time_data = []  # list of (time_value, node_temperatures dict)
        layout = QtGui.QFormLayout(self)

        # .out ファイル
        file_layout = QtGui.QHBoxLayout()
        self.le_file = QtGui.QLineEdit()
        self.le_file.setPlaceholderText("熱解析 .out ファイルのパス")
        file_layout.addWidget(self.le_file)
        self.btn_browse = QtGui.QPushButton("参照...")
        self.btn_browse.clicked.connect(self._on_browse)
        file_layout.addWidget(self.btn_browse)
        layout.addRow(".out ファイル:", file_layout)

        self.btn_load = QtGui.QPushButton("読み込み")
        self.btn_load.clicked.connect(self._on_load)
        layout.addRow("", self.btn_load)

        # 時刻
        self.combo_time = QtGui.QComboBox()
        self.combo_time.setEnabled(False)
        self.combo_time.currentIndexChanged.connect(self._on_time_changed)
        layout.addRow("時刻:", self.combo_time)

        # 温度範囲
        range_layout = QtGui.QHBoxLayout()
        self.spin_t_min = QtGui.QDoubleSpinBox()
        self.spin_t_min.setRange(-273.15, 10000)
        self.spin_t_min.setValue(0.0)
        self.spin_t_min.setSuffix(" ℃")
        range_layout.addWidget(self.spin_t_min)
        range_layout.addWidget(QtGui.QLabel("～"))
        self.spin_t_max = QtGui.QDoubleSpinBox()
        self.spin_t_max.setRange(-273.15, 10000)
        self.spin_t_max.setValue(100.0)
        self.spin_t_max.setSuffix(" ℃")
        range_layout.addWidget(self.spin_t_max)
        layout.addRow("温度範囲:", range_layout)

        self.check_auto_range = QtGui.QCheckBox("データから自動（選択時刻の min/max を使用）")
        self.check_auto_range.setChecked(True)
        layout.addRow("", self.check_auto_range)

        self.btn_apply = QtGui.QPushButton("表示を更新")
        self.btn_apply.clicked.connect(self._on_apply)
        self.btn_apply.setEnabled(False)
        layout.addRow("", self.btn_apply)

        self.button_box = QtGui.QDialogButtonBox(QtGui.QDialogButtonBox.Close)
        self.button_box.rejected.connect(self.reject)
        layout.addRow(self.button_box)

    def _on_browse(self):
        path, _ = QtGui.QFileDialog.getOpenFileName(
            self, "熱解析 .out を選択", "", "Out files (*.out);;All (*.*)"
        )
        if path:
            self.le_file.setText(path)

    def _on_load(self):
        from ThermalAnalysis.modeling import core
        path = self.le_file.text().strip()
        if not path:
            QtGui.QMessageBox.warning(self, "Post Processing", ".out ファイルを指定してください。")
            return
        try:
            self._time_data = core.parse_thermal_out(path)
        except Exception as e:
            QtGui.QMessageBox.critical(self, "Post Processing", "読み込みに失敗しました:\n{}".format(e))
            return
        if not self._time_data:
            QtGui.QMessageBox.warning(self, "Post Processing", "有効な時刻データがありません。")
            return
        self.combo_time.clear()
        for time_val, node_temps in self._time_data:
            self.combo_time.addItem("Time = {}".format(time_val), (time_val, node_temps))
        self.combo_time.setEnabled(True)
        self.btn_apply.setEnabled(True)
        self._on_time_changed()
        QtGui.QMessageBox.information(self, "Post Processing", "{} 件の時刻を読み込みました。".format(len(self._time_data)))

    def _on_time_changed(self):
        if not self._time_data or self.combo_time.currentIndex() < 0:
            return
        _, node_temps = self._time_data[self.combo_time.currentIndex()]
        if not node_temps:
            return
        vals = [v for v in node_temps.values()]
        t_min, t_max = min(vals), max(vals)
        if self.check_auto_range.isChecked():
            self.spin_t_min.setValue(t_min)
            self.spin_t_max.setValue(t_max)

    def _on_apply(self):
        if not self._time_data or self.combo_time.currentIndex() < 0:
            return
        from ThermalAnalysis.modeling import core
        _, node_temps = self._time_data[self.combo_time.currentIndex()]
        t_min = self.spin_t_min.value()
        t_max = self.spin_t_max.value()
        if self.check_auto_range.isChecked():
            if node_temps:
                vals = list(node_temps.values())
                t_min, t_max = min(vals), max(vals)
        core.visualize_temperature_contour(node_temps, t_min, t_max)


class SubdivideSurfaceDialog(QtGui.QDialog):
    """
    選択した FaceGroup をグリッド分割するダイアログ。
    """

    def __init__(self, parent=None):
        super(SubdivideSurfaceDialog, self).__init__(parent)
        self.setWindowTitle("サーフェースを分割")
        layout = QtGui.QFormLayout(self)
        self.spin_u = QtGui.QSpinBox()
        self.spin_u.setRange(1, 100)
        self.spin_u.setValue(2)
        layout.addRow("U方向の分割数:", self.spin_u)
        self.spin_v = QtGui.QSpinBox()
        self.spin_v.setRange(1, 100)
        self.spin_v.setValue(2)
        layout.addRow("V方向の分割数:", self.spin_v)
        self.check_merge_node = QtGui.QCheckBox("サブを1ノードにまとめる")
        self.check_merge_node.setChecked(False)
        layout.addRow("", self.check_merge_node)
        self.spin_surface_start = QtGui.QSpinBox()
        self.spin_surface_start.setRange(-1000000, 1000000)
        self.spin_surface_start.setSpecialValueText("自動（FaceGroupの番号×1000 + k）")
        self.spin_surface_start.setValue(-999999)
        layout.addRow("サーフェース番号の開始値（任意）:", self.spin_surface_start)
        self.button_box = QtGui.QDialogButtonBox(
            QtGui.QDialogButtonBox.Ok | QtGui.QDialogButtonBox.Cancel
        )
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addRow(self.button_box)

    def get_values(self):
        start = self.spin_surface_start.value()
        if start <= -999999:
            start = None
        return (
            self.spin_u.value(),
            self.spin_v.value(),
            self.check_merge_node.isChecked(),
            start,
        )
