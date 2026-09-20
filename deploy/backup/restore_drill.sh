#!/usr/bin/env bash
# Monthly restore drill: restore the latest backup into a scratch database and
# check it is usable. Never touches the production database. Exits non-zero on
# any failure, so it can run from cron/CI and alert.
#
#   SCRATCH_URL=postgresql://postgres:pass@host:5432/postgres deploy/backup/restore_drill.sh
set -euo pipefail

: "${SCRATCH_URL:?SCRATCH_URL (a server where a scratch database may be created) is required}"
SCRATCH_URL="${SCRATCH_URL/postgresql+asyncpg:/postgresql:}"
DB="deno_restore_drill_$(date -u +%Y%m%d%H%M%S)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"; psql "$SCRATCH_URL" -qc "DROP DATABASE IF EXISTS $DB" >/dev/null 2>&1 || true' EXIT

if [[ -n "${RESTIC_REPOSITORY:-}" ]]; then
  SNAP="$(restic snapshots --tag deno-db --latest 1 --json | python3 -c 'import sys,json; print(json.load(sys.stdin)[-1]["short_id"])')"
  FILE="$(restic ls "$SNAP" --json | python3 -c 'import sys,json;[print(o["path"]) for o in map(json.loads, sys.stdin) if o.get("path","").endswith(".dump")]' | head -1)"
  restic dump "$SNAP" "$FILE" > "$WORK/latest.dump"
else
  LATEST="$(ls -1t "${BACKUP_DIR:-./backups}"/deno-*.dump | head -1)"
  cp "$LATEST" "$WORK/latest.dump"
fi

psql -v ON_ERROR_STOP=1 "$SCRATCH_URL" -qc "CREATE DATABASE $DB"
TARGET="${SCRATCH_URL%/*}/$DB"

# Same prerequisites a Supabase project provides: pgvector and auth.uid() (used by RLS policies).
psql -v ON_ERROR_STOP=1 "$TARGET" -q <<'SQL'
CREATE EXTENSION IF NOT EXISTS vector;
CREATE SCHEMA IF NOT EXISTS auth;
CREATE OR REPLACE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql STABLE AS
  $fn$ SELECT nullif(current_setting('request.jwt.claims', true)::jsonb ->> 'sub', '')::uuid $fn$;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN CREATE ROLE anon NOLOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN CREATE ROLE authenticated NOLOGIN; END IF;
END $$;
SQL

# The scratch DB already has a public schema; skip that one TOC entry and fail on anything else.
pg_restore --list "$WORK/latest.dump" | grep -v ' SCHEMA - public ' > "$WORK/toc.list"
pg_restore --no-owner --no-privileges --exit-on-error --use-list="$WORK/toc.list" --dbname="$TARGET" "$WORK/latest.dump"

psql -v ON_ERROR_STOP=1 "$TARGET" -tA <<'SQL'
SELECT 'alembic_version=' || version_num FROM alembic_version;
SELECT 'communities=' || count(*) FROM communities;
SELECT 'projects=' || count(*) FROM projects;
SELECT 'chunks_hnsw_index=' || count(*) FROM pg_indexes WHERE indexname = 'ix_chunks_embedding_hnsw';
SQL
HNSW="$(psql "$TARGET" -tAc "SELECT count(*) FROM pg_indexes WHERE indexname = 'ix_chunks_embedding_hnsw'")"
[[ "$HNSW" == "1" ]] || { echo "restore drill FAILED: vector index missing" >&2; exit 1; }
echo "restore drill ok ($DB dropped on exit)"
