#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DEST="$ROOT/terminal/dev_state/azure_snapshot"
HOST="${ATLAS_AZURE_HOST:-azureuser@51.104.239.35}"
SRC="${ATLAS_AZURE_ATLAS_ROOT:-/home/azureuser/atlas}"
KALSHI_SRC="${ATLAS_AZURE_KALSHI_ROOT:-/home/azureuser/atlas-predict}"

mkdir -p "$DEST"
mkdir -p \
  "$DEST/state" \
  "$DEST/data/state" \
  "$DEST/SHANNON/queue" \
  "$DEST/SHANNON/memos" \
  "$DEST/simons" \
  "$DEST/data/backtest/results" \
  "$DEST/darwin_v2/lineage/scorecards" \
  "$DEST/atlas-predict/paper_trades" \
  "$DEST/atlas-predict/live"

sync_optional() {
  local remote="$1"
  local local_dest="$2"
  if rsync -av "$remote" "$local_dest"; then
    return 0
  fi
  echo "WARN: optional snapshot path unavailable: $remote" >&2
}

sync_optional "$HOST:$SRC/state/" "$DEST/state/"
sync_optional "$HOST:$SRC/data/state/" "$DEST/data/state/"
sync_optional "$HOST:$SRC/SHANNON/queue/" "$DEST/SHANNON/queue/"
sync_optional "$HOST:$SRC/SHANNON/memos/" "$DEST/SHANNON/memos/"
sync_optional "$HOST:$SRC/simons/" "$DEST/simons/"
sync_optional "$HOST:$SRC/data/backtest/results/" "$DEST/data/backtest/results/"
sync_optional "$HOST:$SRC/darwin_v2/lineage/scorecards/" "$DEST/darwin_v2/lineage/scorecards/"
sync_optional "$HOST:$KALSHI_SRC/paper_trades/" "$DEST/atlas-predict/paper_trades/"
sync_optional "$HOST:$KALSHI_SRC/live/" "$DEST/atlas-predict/live/"
if ssh "$HOST" crontab -l > "$DEST/crontab.txt"; then
  echo "captured Azure crontab"
else
  echo "WARN: Azure crontab unavailable" >&2
fi

python3 - "$DEST" "$HOST" "$SRC" "$KALSHI_SRC" <<'PY'
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
            "kalshi_source_path": sys.argv[4],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "files": files,
        },
        indent=2,
    )
)
PY

echo "snapshot refreshed at $DEST"
