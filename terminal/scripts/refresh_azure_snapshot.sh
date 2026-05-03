#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DEST="$ROOT/terminal/dev_state/azure_snapshot"
HOST="${ATLAS_AZURE_HOST:-azureuser@51.104.239.35}"
SRC="${ATLAS_AZURE_ATLAS_ROOT:-/home/azureuser/atlas}"

mkdir -p "$DEST"
mkdir -p \
  "$DEST/data/state" \
  "$DEST/SHANNON/queue" \
  "$DEST/SHANNON/memos" \
  "$DEST/simons" \
  "$DEST/data/backtest/results" \
  "$DEST/darwin_v2/lineage/scorecards"

rsync -av "$HOST:$SRC/data/state/" "$DEST/data/state/"
rsync -av "$HOST:$SRC/SHANNON/queue/" "$DEST/SHANNON/queue/"
rsync -av "$HOST:$SRC/SHANNON/memos/" "$DEST/SHANNON/memos/"
rsync -av "$HOST:$SRC/simons/" "$DEST/simons/"
rsync -av "$HOST:$SRC/data/backtest/results/" "$DEST/data/backtest/results/"
rsync -av "$HOST:$SRC/darwin_v2/lineage/scorecards/" "$DEST/darwin_v2/lineage/scorecards/"

python3 - "$DEST" "$HOST" "$SRC" <<'PY'
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

dest = Path(sys.argv[1])
files = []
for path in dest.rglob("*"):
    if path.is_file() and path.name != "snapshot_manifest.json":
        files.append({"path": str(path.relative_to(dest)), "mtime": path.stat().st_mtime})

(dest / "snapshot_manifest.json").write_text(
    json.dumps(
        {
            "source_host": sys.argv[2],
            "source_path": sys.argv[3],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "files": files,
        },
        indent=2,
    )
)
PY

echo "snapshot refreshed at $DEST"
