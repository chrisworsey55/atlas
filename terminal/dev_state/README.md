# Terminal Dev State

This directory is for explicit read-only Azure snapshots used during local development.

Refresh it from the repo root with:

```bash
bash terminal/scripts/refresh_azure_snapshot.sh
```

Run locally against the snapshot with:

```bash
ATLAS_STATE_ROOT=terminal/dev_state/azure_snapshot uvicorn terminal.app:app --host 127.0.0.1 --port 8010
```

