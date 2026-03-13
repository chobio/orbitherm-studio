import json
import os

from PySide import QtCore, QtGui


def _presets_path():
    gui_dir = os.path.dirname(os.path.abspath(__file__))
    mod_dir = os.path.dirname(gui_dir)
    return os.path.join(mod_dir, "orbit_heat", "orbit_tle_presets.json")


def load_tle_presets():
    path = _presets_path()
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_tle_presets(presets):
    path = _presets_path()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(presets, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False


class OrbitEnvironmentDialog(QtGui.QDialog):
    """Orbit & environment input dialog with tabs."""

    def __init__(self, parent=None):
        super(OrbitEnvironmentDialog, self).__init__(parent)
        self.setWindowTitle("Orbit & Environment")
        self.resize(480, 360)

        main_layout = QtGui.QVBoxLayout(self)

        self.tabs = QtGui.QTabWidget(self)
        main_layout.addWidget(self.tabs)

        # Orbit tab
        self.orbit_tab = QtGui.QWidget()
        orbit_layout = QtGui.QFormLayout(self.orbit_tab)

        mode_layout = QtGui.QHBoxLayout()
        self.rb_tle = QtGui.QRadioButton("TLE")
        self.rb_kepler = QtGui.QRadioButton("Kepler Elements")
        self.rb_tle.setChecked(True)
        mode_layout.addWidget(self.rb_tle)
        mode_layout.addWidget(self.rb_kepler)
        mode_layout.addStretch(1)
        orbit_layout.addRow("Input mode:", mode_layout)

        # TLE preset selection
        self._tle_presets = load_tle_presets()
        self.combo_preset = QtGui.QComboBox()
        self.combo_preset.setEditable(False)
        for p in self._tle_presets:
            self.combo_preset.addItem(p["name"], p)
        self.combo_preset.addItem("Custom", None)
        self.combo_preset.currentIndexChanged.connect(self._on_preset_changed)
        preset_row = QtGui.QHBoxLayout()
        preset_row.addWidget(self.combo_preset)
        self.btn_save_preset = QtGui.QPushButton("Save as preset...")
        self.btn_save_preset.clicked.connect(self._save_current_as_preset)
        preset_row.addWidget(self.btn_save_preset)
        preset_row.addStretch(1)
        orbit_layout.addRow("TLE preset:", preset_row)

        # TLE inputs
        self.le_tle_line1 = QtGui.QLineEdit()
        self.le_tle_line2 = QtGui.QLineEdit()
        orbit_layout.addRow("TLE Line 1:", self.le_tle_line1)
        orbit_layout.addRow("TLE Line 2:", self.le_tle_line2)

        # 軌道基準日（いつからの軌道とするか。TLE の epoch に近い日付だと精度が高い）
        self.date_epoch = QtGui.QDateEdit()
        self.date_epoch.setCalendarPopup(True)
        self.date_epoch.setDate(QtCore.QDate(2024, 1, 1))
        self.date_epoch.setDisplayFormat("yyyy-MM-dd")
        self.date_epoch.setToolTip("軌道・太陽方向の計算基準日 (UTC 0:00)。この日付の 0 時からの経過秒数で時刻を取ります。")
        orbit_layout.addRow("軌道基準日 (UTC):", self.date_epoch)

        # Kepler elements
        self.le_a_km = QtGui.QDoubleSpinBox()
        self.le_a_km.setRange(1.0, 100000.0)
        self.le_a_km.setDecimals(3)
        self.le_a_km.setSuffix(" km")
        self.le_a_km.setValue(6771.0)  # 地球半径+400km（典型的なLEO）。0のままだと周期0で軌道が描画されない
        self.le_ecc = QtGui.QDoubleSpinBox()
        self.le_ecc.setRange(0.0, 0.99)
        self.le_ecc.setDecimals(6)
        self.le_ecc.setValue(0.0)
        self.le_inc_deg = QtGui.QDoubleSpinBox()
        self.le_inc_deg.setRange(0.0, 180.0)
        self.le_inc_deg.setDecimals(4)
        self.le_inc_deg.setValue(51.6)
        self.le_raan_deg = QtGui.QDoubleSpinBox()
        self.le_raan_deg.setRange(0.0, 360.0)
        self.le_raan_deg.setDecimals(4)
        self.le_raan_deg.setValue(0.0)
        self.le_argp_deg = QtGui.QDoubleSpinBox()
        self.le_argp_deg.setRange(0.0, 360.0)
        self.le_argp_deg.setDecimals(4)
        self.le_argp_deg.setValue(0.0)
        self.le_m_deg = QtGui.QDoubleSpinBox()
        self.le_m_deg.setRange(0.0, 360.0)
        self.le_m_deg.setDecimals(4)
        self.le_m_deg.setValue(0.0)

        orbit_layout.addRow("a (semi-major axis):", self.le_a_km)
        orbit_layout.addRow("e (eccentricity):", self.le_ecc)
        orbit_layout.addRow("i (deg):", self.le_inc_deg)
        orbit_layout.addRow("RAAN (deg):", self.le_raan_deg)
        orbit_layout.addRow("ω (deg):", self.le_argp_deg)
        orbit_layout.addRow("M0 (deg):", self.le_m_deg)

        self.spin_periods = QtGui.QSpinBox()
        self.spin_periods.setRange(1, 1000)
        self.spin_periods.setValue(1)
        orbit_layout.addRow("Number of periods:", self.spin_periods)

        self.spin_divisions = QtGui.QSpinBox()
        self.spin_divisions.setRange(4, 240)
        self.spin_divisions.setValue(24)
        orbit_layout.addRow("Divisions per period:", self.spin_divisions)

        # Attitude (for 3D visualization)
        attitude_layout = QtGui.QHBoxLayout()
        self.rb_nadir = QtGui.QRadioButton("Nadir (Earth-pointing)")
        self.rb_sun = QtGui.QRadioButton("Sun-pointing")
        self.rb_nadir.setChecked(True)
        attitude_layout.addWidget(self.rb_nadir)
        attitude_layout.addWidget(self.rb_sun)
        attitude_layout.addStretch(1)
        orbit_layout.addRow("Attitude (visualization):", attitude_layout)

        self.tabs.addTab(self.orbit_tab, "Orbit")

        # Environment tab
        self.env_tab = QtGui.QWidget()
        env_layout = QtGui.QFormLayout(self.env_tab)

        self.spin_solar_constant = QtGui.QDoubleSpinBox()
        self.spin_solar_constant.setRange(0.0, 5000.0)
        self.spin_solar_constant.setDecimals(2)
        self.spin_solar_constant.setValue(1358.0)
        self.spin_solar_constant.setSuffix(" W/m2")

        self.spin_albedo = QtGui.QDoubleSpinBox()
        self.spin_albedo.setRange(0.0, 1.0)
        self.spin_albedo.setDecimals(3)
        self.spin_albedo.setValue(0.3)

        self.spin_earth_ir = QtGui.QDoubleSpinBox()
        self.spin_earth_ir.setRange(0.0, 1000.0)
        self.spin_earth_ir.setDecimals(2)
        self.spin_earth_ir.setValue(237.0)
        self.spin_earth_ir.setSuffix(" W/m2")

        env_layout.addRow("Solar constant:", self.spin_solar_constant)
        env_layout.addRow("Albedo:", self.spin_albedo)
        env_layout.addRow("Earth IR:", self.spin_earth_ir)

        self.tabs.addTab(self.env_tab, "Environment")

        # Display tab (orbit visualization scale)
        self.display_tab = QtGui.QWidget()
        display_layout = QtGui.QFormLayout(self.display_tab)
        self.spin_orbit_display_scale = QtGui.QDoubleSpinBox()
        self.spin_orbit_display_scale.setRange(0.25, 5.0)
        self.spin_orbit_display_scale.setSingleStep(0.25)
        self.spin_orbit_display_scale.setDecimals(2)
        self.spin_orbit_display_scale.setValue(1.0)
        self.spin_orbit_display_scale.setSuffix(" x")
        self.spin_orbit_display_scale.setToolTip("1 = 実際の軌道高度のまま表示。0.5 = 半分の距離で表示、2 = 2倍の距離で表示。")
        display_layout.addRow("軌道表示倍率 (実際の高度の何倍で表示):", self.spin_orbit_display_scale)
        self.spin_shadow_length_km = QtGui.QDoubleSpinBox()
        self.spin_shadow_length_km.setRange(5000.0, 500000.0)
        self.spin_shadow_length_km.setSingleStep(5000.0)
        self.spin_shadow_length_km.setDecimals(0)
        self.spin_shadow_length_km.setValue(10000.0)
        self.spin_shadow_length_km.setSuffix(" km")
        self.spin_shadow_length_km.setToolTip("地球影（日陰）の円筒表示の長さ。実際の影はほぼ無限に伸びるため、見やすさ用の表示長です。")
        display_layout.addRow("日陰（地球影）の表示長:", self.spin_shadow_length_km)
        self.tabs.addTab(self.display_tab, "表示")

        # Footer buttons
        self.button_box = QtGui.QDialogButtonBox(
            QtGui.QDialogButtonBox.Ok | QtGui.QDialogButtonBox.Cancel
        )
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        main_layout.addWidget(self.button_box)

        # connections
        self.rb_tle.toggled.connect(self._update_mode_enabled)
        self._update_mode_enabled()
        # Apply first preset as default if available
        if self._tle_presets:
            self.combo_preset.setCurrentIndex(0)
            self._on_preset_changed(0)

    def _on_preset_changed(self, index):
        data = self.combo_preset.itemData(index)
        if data and isinstance(data, dict):
            self.le_tle_line1.setText(data.get("line1", ""))
            self.le_tle_line2.setText(data.get("line2", ""))

    def _save_current_as_preset(self):
        name, ok = QtGui.QInputDialog.getText(self, "Save TLE preset", "Preset name:")
        if not ok or not name.strip():
            return
        line1 = self.le_tle_line1.text().strip()
        line2 = self.le_tle_line2.text().strip()
        if not line1 or not line2:
            QtGui.QMessageBox.warning(self, "TLE preset", "TLE Line 1 and Line 2 must be non-empty.")
            return
        self._tle_presets.append({"name": name.strip(), "line1": line1, "line2": line2})
        if not save_tle_presets(self._tle_presets):
            QtGui.QMessageBox.warning(self, "TLE preset", "Failed to save preset file.")
            self._tle_presets.pop()
            return
        self.combo_preset.blockSignals(True)
        self.combo_preset.clear()
        for p in self._tle_presets:
            self.combo_preset.addItem(p["name"], p)
        self.combo_preset.addItem("Custom", None)
        self.combo_preset.blockSignals(False)
        self.combo_preset.setCurrentIndex(len(self._tle_presets) - 1)
        QtGui.QMessageBox.information(self, "TLE preset", "Preset saved.")

    def _update_mode_enabled(self):
        use_tle = self.rb_tle.isChecked()
        for w in (
            self.combo_preset,
            self.btn_save_preset,
            self.le_tle_line1,
            self.le_tle_line2,
            self.date_epoch,
        ):
            w.setEnabled(use_tle)
        for w in (
            self.le_a_km,
            self.le_ecc,
            self.le_inc_deg,
            self.le_raan_deg,
            self.le_argp_deg,
            self.le_m_deg,
            self.date_epoch,
        ):
            w.setEnabled(not use_tle)

    def get_parameters(self):
        """Return parameters as a plain dict."""
        mode = "tle" if self.rb_tle.isChecked() else "kepler"
        attitude_mode = "nadir" if self.rb_nadir.isChecked() else "sun"
        qdate = self.date_epoch.date()
        params = {
            "mode": mode,
            "epoch_year": int(qdate.year()),
            "epoch_month": int(qdate.month()),
            "epoch_day": int(qdate.day()),
            "periods": int(self.spin_periods.value()),
            "divisions_per_period": int(self.spin_divisions.value()),
            "attitude_mode": attitude_mode,
            "orbit_display_scale": float(self.spin_orbit_display_scale.value()),
            "shadow_length_km": float(self.spin_shadow_length_km.value()),
            "solar_constant": float(self.spin_solar_constant.value()),
            "albedo": float(self.spin_albedo.value()),
            "earth_ir": float(self.spin_earth_ir.value()),
        }
        if mode == "tle":
            params.update(
                {
                    "tle_line1": self.le_tle_line1.text().strip(),
                    "tle_line2": self.le_tle_line2.text().strip(),
                }
            )
        else:
            params.update(
                {
                    "a_km": float(self.le_a_km.value()),
                    "ecc": float(self.le_ecc.value()),
                    "inc_deg": float(self.le_inc_deg.value()),
                    "raan_deg": float(self.le_raan_deg.value()),
                    "argp_deg": float(self.le_argp_deg.value()),
                    "m_deg": float(self.le_m_deg.value()),
                }
            )
        return params
