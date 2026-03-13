# -*- coding: utf-8 -*-
"""軌道コマ送りダイアログ。各計算点での衛星位置・向きを確認する。"""

from __future__ import annotations

import FreeCAD
from PySide import QtCore, QtGui

from ThermalAnalysis.orbit_heat import orbit_core, orbit_visualization


class OrbitStepDialog(QtGui.QDialog):
    """軌道の各計算点をコマ送りで表示するダイアログ。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("軌道コマ送り")
        self._state = None
        self._frame_index = 0
        self._setup_ui()
        self._load_state()

    def _setup_ui(self):
        layout = QtGui.QVBoxLayout(self)
        # 情報表示
        self._info_label = QtGui.QLabel("データがありません。先に「軌道計算と描画」を実行してください。")
        self._info_label.setWordWrap(True)
        layout.addWidget(self._info_label)
        # フレーム番号・時刻・日陰
        self._frame_label = QtGui.QLabel("")
        layout.addWidget(self._frame_label)
        # スライダー
        self._slider = QtGui.QSlider(QtCore.Qt.Horizontal)
        self._slider.setMinimum(0)
        self._slider.setMaximum(0)
        self._slider.valueChanged.connect(self._on_slider_changed)
        layout.addWidget(self._slider)
        # 前へ・次へ
        btn_layout = QtGui.QHBoxLayout()
        self._prev_btn = QtGui.QPushButton("前へ")
        self._prev_btn.clicked.connect(self._go_prev)
        self._next_btn = QtGui.QPushButton("次へ")
        self._next_btn.clicked.connect(self._go_next)
        btn_layout.addWidget(self._prev_btn)
        btn_layout.addWidget(self._next_btn)
        layout.addLayout(btn_layout)
        # 閉じる
        close_btn = QtGui.QPushButton("閉じる")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

    def _load_state(self):
        self._state = orbit_core.get_last_orbit_state()
        if not self._state:
            self._info_label.setText("データがありません。先に「軌道計算と描画」を実行してください。")
            self._frame_label.setText("")
            self._slider.setMaximum(0)
            self._prev_btn.setEnabled(False)
            self._next_btn.setEnabled(False)
            return
        times, _, _, _, _ = self._state
        n = len(times)
        self._info_label.setText("フレームを変更すると 3D ビューの衛星と太陽ベクトルが更新されます。")
        self._slider.setMaximum(max(0, n - 1))
        self._slider.setValue(0)
        self._frame_index = 0
        self._prev_btn.setEnabled(n > 1)
        self._next_btn.setEnabled(n > 1)
        self._update_frame_display()

    def _update_frame_display(self):
        if not self._state:
            return
        times, _, _, _, heat_array = self._state
        n = len(times)
        if n == 0:
            return
        idx = self._frame_index
        t_sec = float(times[idx])
        in_eclipse = False
        if heat_array is not None and idx < len(heat_array):
            row = heat_array[idx]
            if len(row) > 0 and float(row[0]) < 1.0:  # q_solar がほぼ 0
                in_eclipse = True
        eclipse_text = "日陰" if in_eclipse else "日照"
        self._frame_label.setText(
            "フレーム {} / {}   t = {:.1f} s   {}".format(idx + 1, n, t_sec, eclipse_text)
        )
        doc = FreeCAD.ActiveDocument
        if doc:
            orbit_visualization.update_scene_frame(doc, idx)

    def _on_slider_changed(self, value):
        self._frame_index = int(value)
        self._update_frame_display()

    def _go_prev(self):
        if not self._state:
            return
        n = len(self._state[0])
        self._frame_index = max(0, self._frame_index - 1)
        self._slider.setValue(self._frame_index)
        self._update_frame_display()

    def _go_next(self):
        if not self._state:
            return
        n = len(self._state[0])
        self._frame_index = min(n - 1, self._frame_index + 1)
        self._slider.setValue(self._frame_index)
        self._update_frame_display()
