# -*- coding: utf-8 -*-
"""
ThermalAnalysis bridge サブパッケージ。
輻射モデルと軌道熱ソルバー間の接続コード、および外部ソルバーとのファイル交換関数をここに集約する。
"""

from ThermalAnalysis.bridge.orbit_heat_bridge import get_surfaces_for_orbit_heat
from ThermalAnalysis.bridge.exporter import (
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
