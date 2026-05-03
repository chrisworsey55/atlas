# ATLAS Terminal

Bloomberg-style operator terminal for ATLAS. Production data is Azure state; local repo state is development-only.

## Phase Status

- Phase 3 layout grid is installed.
- Wiring, command execution, deploy config, and full visual treatment land in later phase commits.

## Add a Panel

1. Add an endpoint under `terminal/app.py` or a source module under `terminal/sources/`.
2. Add a panel slot in `terminal/templates/terminal.html` using the 12-column grid.
3. Add refresh/render logic in `terminal/static/terminal.js`.

