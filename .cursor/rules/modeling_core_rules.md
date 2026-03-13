# modeling/core.py specific rules

This file is a temporary compatibility integration module during gradual refactoring.

## Purpose
Keep the file stable while improving readability and reducing future risk.

## Allowed changes
- add section headers
- add comments
- add docstrings
- improve internal readability
- make minimal safe organizational edits

## Disallowed changes unless explicitly requested
- moving large numbers of functions to other files
- renaming public functions
- changing call signatures
- changing behavior
- broad import rewrites
- deleting compatibility code

## Section intent
Typical sections inside `modeling/core.py` may include:
- private utilities
- model building
- display / visualization helpers
- thermal property and material handling
- conductance and radiation calculation
- solver file export

## Forward-looking guidance
- new display-related logic should prefer `post/`
- new export orchestration should prefer `bridge/`
- new pure calculations should prefer dedicated modeling modules
- use `core.py` as a compatibility hub, not as the default destination for all new code