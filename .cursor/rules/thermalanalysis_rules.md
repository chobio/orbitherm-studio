# ThermalAnalysis Cursor Rules

This repository is a FreeCAD 1.0.1 workbench for spacecraft thermal analysis.

## Project purpose
The workbench is used to:
- build thermal mathematical models from FreeCAD geometry
- compute orbital thermal environment inputs
- export solver input files for an external SINDA-like solver
- visualize analysis-related data and results inside FreeCAD

## Current architecture
The repository is organized into the following layers:

- `InitGui.py`
  - FreeCAD entry point
  - workbench registration
  - toolbar/menu definitions
  - compatibility layer still exists in some places

- `gui/`
  - FreeCAD command classes
  - Qt dialogs and task panels
  - user interaction entry points

- `modeling/`
  - geometry extraction
  - thermal model preparation
  - material and property handling
  - conductance and radiation-related calculations
  - some legacy mixed code still exists in `modeling/core.py`

- `orbit_heat/`
  - orbit calculations
  - attitude handling
  - orbital heat input generation
  - orbit visualization

- `post/`
  - post-processing and visualization public interface
  - currently still wraps some display/helper functions that physically remain in `modeling/core.py`

- `bridge/`
  - interface layer between modeling/orbit_heat and external solver/export flows
  - export wrappers
  - orbit/model bridge logic

- `solver/`
  - external solver area
  - do not refactor unless explicitly requested

## Architectural rules
1. Keep responsibilities separated by layer.
2. Do not place new GUI logic in `modeling/`, `orbit_heat/`, or `bridge/`.
3. Do not place numerical model-building logic in `gui/`.
4. Do not place display/UI code in `bridge/`.
5. Prefer `bridge/` for file export orchestration and cross-layer adapters.
6. Treat `post/` as the canonical public location for post-processing logic, even if some legacy implementation still remains in `modeling/core.py`.
7. Avoid direct coupling between `modeling/` and `orbit_heat/` where possible; use `bridge/` for translation/connection logic.
8. Do not modify external solver behavior unless explicitly asked.

## Legacy compatibility rules
This codebase is under gradual refactoring using a wrapper-first strategy.

Therefore:
- prefer wrappers/shims over big rewrites
- preserve backward compatibility when possible
- do not move large groups of functions across files unless explicitly requested
- do not remove shim modules unless explicitly requested
- keep old import paths working when feasible

Known compatibility shims include patterns like:
- wrapper re-exports from `post/__init__.py`
- shim modules in `orbit_heat/`
- shim modules that forward GUI definitions to `gui/`

## Special note for modeling/core.py
`modeling/core.py` is currently a temporary compatibility integration module.

It may contain:
- private utilities
- model building logic
- display/visualization helpers
- thermal property handling
- conductance/radiation calculations
- solver file export helpers

Rules for `modeling/core.py`:
- do not aggressively split it unless explicitly asked
- prefer section-based internal cleanup first
- do not change behavior during organizational refactors
- new display-related code should preferably go to `post/`
- new export orchestration code should preferably go to `bridge/`
- new pure calculation logic should preferably go to dedicated modules instead of expanding `core.py`

## Refactoring rules
When asked to refactor:
- prefer minimal-diff changes
- preserve behavior
- preserve function names unless explicitly asked
- preserve call signatures unless explicitly asked
- avoid changing imports broadly unless necessary
- explain which layer is being modified:
  - gui
  - modeling
  - orbit_heat
  - post
  - bridge

## Coding style
- Use small focused functions when adding new code
- Prefer explicit names over clever shortcuts
- Use comments to clarify legacy vs canonical locations
- Add docstrings to public functions/classes when practical
- Avoid circular imports
- Prefer compatibility-safe edits over idealized rewrites

## Import guidance
- `gui/` may import from lower layers when needed
- `bridge/` may import from `modeling/` and `orbit_heat/`
- avoid making `modeling/` depend on `gui/`
- avoid making `orbit_heat/` depend on `gui/`
- avoid direct `modeling/` <-> `orbit_heat/` coupling unless clearly necessary
- prefer stable public entry points over reaching into unrelated internals

## When generating new code
Before writing code, determine which layer owns the responsibility.

Examples:
- FreeCAD command/button/dialog/task panel -> `gui/`
- geometry extraction / node building / material assignment -> `modeling/`
- orbital environment / heat input / attitude -> `orbit_heat/`
- result display / visualization wrappers -> `post/`
- export adapters / solver file orchestration / layer translation -> `bridge/`

## What not to do
- Do not perform broad architectural rewrites without explicit request
- Do not move the external solver into the Mod structure
- Do not convert wrapper-first refactoring into a full physical migration unless explicitly requested
- Do not add new mixed UI logic into `modeling/core.py`
- Do not silently break compatibility shims