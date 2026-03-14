# -*- coding: utf-8 -*-
"""
Orbitherm Studio — Bridge サブパッケージ (ThermalAnalysis.bridge)。
輻射モデルと軌道熱ソルバー間の接続コード、および外部ソルバーとのファイル交換関数をここに集約する。
Orbitherm Solver へのファイル出力エントリポイント。
"""

from orbitherm_studio.bridge.orbit_heat_bridge import get_surfaces_for_orbit_heat
from orbitherm_studio.bridge.exporter import (
    export_thermal_model_inp,
    export_nodes_and_conductance_dat,
    export_radiation_dat,
    export_heat_array_csv,
    export_face_heat_csv,
)

__all__ = [
    "get_surfaces_for_orbit_heat",
    "export_thermal_model_inp",
    "export_nodes_and_conductance_dat",
    "export_radiation_dat",
    "export_heat_array_csv",
    "export_face_heat_csv",
]
