#!/usr/bin/env bash
# Nightly backup of ~/.robin to ~/Library/Mobile Documents/com~apple~CloudDocs/Robin_Backups/
# Keeps last 7 backups. Scheduled via LaunchAgent.

set -euo pipefail

ROBIN_HOME="${ROBIN_HOME:-$HOME/.robin}"
BACKUP_ROOT="$HOME/Library/Mobile Documents/com~apple~CloudDocs/Robin_Backups"
DATE=$(date +%Y%m%d_%H%M%S)
DEST="$BACKUP_ROOT/$DATE"
KEEP=7

mkdir -p "$BACKUP_ROOT"

# Exclude active SQLite WAL files and large model caches
rsync -a --exclude='*.wal' --exclude='*.shm' --exclude='*.pyc' \
  --exclude='__pycache__/' \
  "$ROBIN_HOME/" "$DEST/"

echo "[$(date -Iseconds)] backup created: $DEST" >> "$ROBIN_HOME/logs/backup.log"

# Prune old backups
mapfile -d '' OLD < <(find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d -print0 | sort -z)
TOTAL=${#OLD[@]}
if (( TOTAL > KEEP )); then
  REMOVE=$(( TOTAL - KEEP ))
  for (( i=0; i<REMOVE; i++ )); do
    rm -rf "${OLD[$i]}"
    echo "[$(date -Iseconds)] pruned: ${OLD[$i]}" >> "$ROBIN_HOME/logs/backup.log"
  done
fi
