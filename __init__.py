# Orbitherm Studio — FreeCAD-based thermal modeling workbench
# Package root: orbitherm_studio (formerly ThermalAnalysis)

import sys as _sys

# ---------------------------------------------------------------------------
# Bidirectional import alias shim
#
# Pre-rename  (dir = ThermalAnalysis):
#   This module loads as 'ThermalAnalysis'.
#   We register 'orbitherm_studio' pointing here so that
#   "from orbitherm_studio.xxx import" works immediately.
#
# Post-rename (dir = orbitherm_studio):
#   This module loads as 'orbitherm_studio'.
#   We register 'ThermalAnalysis' pointing here so that
#   any old user macro using "from orbitherm_studio.xxx import" still works.
# ---------------------------------------------------------------------------
_self = _sys.modules[__name__]

if __name__ == 'ThermalAnalysis':
    # Pre-rename: forward alias  ThermalAnalysis → orbitherm_studio
    _sys.modules.setdefault('orbitherm_studio', _self)
elif __name__ == 'orbitherm_studio':
    # Post-rename: backward alias  orbitherm_studio → ThermalAnalysis
    _sys.modules.setdefault('ThermalAnalysis', _self)

del _self, _sys
