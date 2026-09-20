#!/usr/bin/env bash
# Nightly logical backup of the Deno database (docs/08 Phase 2).
#
#   DATABASE_URL=postgresql://user:pass@host:5432/postgres deploy/backup/backup.sh
#
# With RESTIC_REPOSITORY set (e.g. s3:https://<endpoint>/deno-backups) the dump is
# streamed into restic (encrypted, deduplicated) and pruned to 30 daily + 12
# monthly snapshots. Without it, the dump is written to BACKUP_DIR (default ./backups).
# Supabase also keeps its own daily backups; this is the provider-independent copy.
set -euo pipefail

: "${DATABASE_URL:?DATABASE_URL is required (plain postgresql:// URL, not +asyncpg)}"
PG_URL="${DATABASE_URL/postgresql+asyncpg:/postgresql:}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
# Only our schema; Supabase-managed schemas (auth, storage, ...) are backed up by Supabase.
DUMP_ARGS=(--format=custom --no-owner --no-privileges --schema=public --dbname="$PG_URL")

if [[ -n "${RESTIC_REPOSITORY:-}" ]]; then
  : "${RESTIC_PASSWORD:?RESTIC_PASSWORD is required with RESTIC_REPOSITORY}"
  pg_dump "${DUMP_ARGS[@]}" | restic backup --stdin --stdin-filename "deno-${STAMP}.dump" --tag deno-db
  restic forget --tag deno-db --keep-daily 30 --keep-monthly 12 --prune
  echo "backup ok: restic snapshot deno-${STAMP}.dump"
else
  BACKUP_DIR="${BACKUP_DIR:-./backups}"
  mkdir -p "$BACKUP_DIR"
  pg_dump "${DUMP_ARGS[@]}" --file="$BACKUP_DIR/deno-${STAMP}.dump"
  find "$BACKUP_DIR" -name 'deno-*.dump' -mtime +30 -delete
  echo "backup ok: $BACKUP_DIR/deno-${STAMP}.dump"
fi
