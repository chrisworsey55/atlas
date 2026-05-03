# ATLAS Terminal

Bloomberg-style operator terminal for ATLAS. Production data is Azure state; local repo state is development-only.

## Phase Status

- Phase 3 layout grid is installed.
- Phase 4 visual spec is installed.
- Phase 5 command bar is installed.
- Phase 6 source wiring is installed for F1, F2, F7, F3, F8, F4, and F6. F5 JANUS intentionally ships as `NOT_WIRED`.
- Deploy config lands in the final phase commit.

## Add a Panel

1. Add a read-only adapter in `terminal/sources/core.py` that returns the standard envelope: `status`, `as_of`, `source`, `data`, and freshness fields.
2. Register the route in `ROUTES` in `terminal/app.py`.
3. Add a panel slot in `terminal/templates/terminal.html` using the 12-column grid.
4. Add the panel id and route to `panels` in `terminal/static/terminal.js`, then add a renderer branch if the generic JSON renderer is not sufficient.

## Refresh Local Snapshot

Production on Azure is canonical. Local state is development-only unless you explicitly refresh a snapshot.

```bash
bash terminal/scripts/refresh_azure_snapshot.sh
```

Run the terminal against the snapshot:

```bash
ATLAS_STATE_ROOT=terminal/dev_state/azure_snapshot uvicorn terminal.app:app --host 127.0.0.1 --port 8010
```

During local development the header shows snapshot age next to the health dot. On Azure deployment the snapshot indicator is hidden because the service reads live production state.

## Deploy to Azure

Deployment is documented in Phase 7 and should be run manually after review.

## NOT_WIRED Panels

- F5 JANUS regime: fix by producing `/home/azureuser/atlas/data/state/janus_daily.json` in production.
- F5 JANUS weights: fix by producing a production JANUS output or reweighting file and adding it to `terminal/sources/core.py`.
- F5 JANUS last reweighting: fix by producing production JANUS history/log state and adding it to `terminal/sources/core.py`.
- F6 Ablations: fix by writing ablation result files under `/home/azureuser/atlas/data/backtest/results/` with `ablation` in the filename.
- F8 News/geopolitical output may show `NOT_WIRED` until `data/state/news_briefs.json` exists in production.
