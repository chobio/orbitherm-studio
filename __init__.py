# Orbitherm Studio — FreeCAD-based thermal modeling workbench
# Package root: orbitherm_studio (formerly ThermalAnalysis)

import sys as _sys

# ---------------------------------------------------------------------------
# Bidirectional import alias shim
#
# Legacy (dir = ThermalAnalysis):
#   This module loads as 'ThermalAnalysis'.
#   We register 'orbitherm_studio' pointing here so that
#   "from orbitherm_studio.xxx import" works immediately.
#
# Current (dir = orbitherm-studio):
#   InitGui.py が importlib で本モジュールを 'orbitherm_studio' として手動登録する。
#   __name__ == 'orbitherm_studio' になるので、ThermalAnalysis 後方互換エイリアスを登録。
# ---------------------------------------------------------------------------
_self = _sys.modules[__name__]

if __name__ == 'ThermalAnalysis':
    # Pre-rename: forward alias  ThermalAnalysis → orbitherm_studio
    _sys.modules.setdefault('orbitherm_studio', _self)
elif __name__ == 'orbitherm_studio':
    # Post-rename: backward alias  orbitherm_studio → ThermalAnalysis
    _sys.modules.setdefault('ThermalAnalysis', _self)

del _self, _sys
