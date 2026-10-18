#!/usr/bin/env bash
# Demo setup from scratch, with Docker only (README "Run with Docker").
#
#   scripts/demo.sh setup                  # DB + data + models + API + UI; data from checkpoints/demo.dump if present
#   scripts/demo.sh setup --ingest         # data from a full ingest instead (crawl → embed → extract → judge, ~20 min)
#   scripts/demo.sh setup --snapshot F     # data from checkpoints/F
#   scripts/demo.sh dump [F]               # snapshot the running stack's DB to checkpoints/F (default demo.dump)
#
# Needs Docker with Compose 2.24+, and a .env with KEERA_API_KEY (copied from .env.example on the first run).
# Works for the dev stack and for the packaged one (COMPOSE_FILE=...:docker-compose.handoff.yml in .env, docs/HANDOFF.md).
# checkpoints/ is git-ignored: a dump holds the crawled page texts and the uploaded case texts. Pass it on
# directly, never through git (the repository is public). Ports: DB_PORT, API_PORT, UI_PORT as in compose.
set -euo pipefail
cd "$(dirname "$0")/.."

SNAPSHOT_DIR=checkpoints
compose() { docker compose "$@"; }
step() { printf '\n==> %s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

check_prereqs() {
  command -v docker >/dev/null || die "Docker is not installed"
  docker compose version >/dev/null 2>&1 || die "Docker Compose v2 is needed (docker compose ...)"
  docker info >/dev/null 2>&1 || die "Docker is not running"
  if [[ ! -f .env ]]; then
    cp .env.example .env
    die "created .env from .env.example: set KEERA_API_KEY in it, then run this again"
  fi
  # The key's value is never printed
  grep -qE '^KEERA_API_KEY=[^[:space:]#]+' .env || die "KEERA_API_KEY is empty in .env (search, chat and cases call Apertus)"
}

restore_snapshot() {
  local file=$1
  [[ -f "$SNAPSHOT_DIR/$file" ]] || die "$SNAPSHOT_DIR/$file not found"
  step "Restoring $SNAPSHOT_DIR/$file (replaces every table of the stack's database)"
  DEMO_SNAPSHOT="$file" compose run --rm restore
  # A snapshot can be older than the code: init-db adds the newer tables and columns (idempotent)
  compose run --rm app uv run navigator init-db
}

setup() {
  local mode=auto snapshot=demo.dump
  while [[ $# -gt 0 ]]; do
    case $1 in
      --ingest) mode=ingest ;;
      --snapshot) mode=snapshot; snapshot=${2:?--snapshot needs a file name in $SNAPSHOT_DIR/}; shift ;;
      *) die "unknown option $1" ;;
    esac
    shift
  done
  if [[ $mode == auto ]]; then
    if [[ -f "$SNAPSHOT_DIR/$snapshot" ]]; then mode=snapshot; else mode=ingest; fi
  fi

  check_prereqs
  step "Building the images (app ~2 GB with CPU-only torch; cached after the first run)"
  compose build
  step "Starting Postgres"
  compose up -d --wait db

  if [[ $mode == snapshot ]]; then
    restore_snapshot "$snapshot"
  else
    step "Full ingest: init-db → crawl → embed → extract → resolve → judge (~20 min for 100 pages, mostly Apertus)"
    compose run --rm app uv run navigator ingest
  fi

  step "Downloading the models into the hf_cache volume (bge-m3 and the case reranker, ~4.5 GB; once)"
  compose run --rm app uv run navigator warm

  step "Starting the stack (healthy once the API has loaded bge-m3, ~1 min)"
  compose up -d --wait
  compose run --rm app uv run navigator stats

  local ui="http://localhost:${UI_PORT:-5173}" api="http://localhost:${API_PORT:-8000}/docs"
  if grep -qE '^COMPOSE_FILE=.*handoff' .env; then
    ui="http://localhost:${UI_PORT:-8080}" api="not published (packaged stack, docs/HANDOFF.md)"
  fi
  cat <<EOF

Demo ready ($mode).
  UI:       $ui
  API docs: $api
  Example business models to upload: docs/examples/*-business-model.pdf
Stop with: docker compose stop        (data and models stay in the pgdata and hf_cache volumes)
EOF
}

dump() {
  local file=${1:-demo.dump}
  check_prereqs
  mkdir -p "$SNAPSHOT_DIR"
  if [[ -f "$SNAPSHOT_DIR/$file" ]]; then
    local backup="$SNAPSHOT_DIR/${file%.dump}-$(date +%Y%m%d-%H%M%S).dump"
    mv "$SNAPSHOT_DIR/$file" "$backup"
    echo "previous snapshot kept as $backup"
  fi
  step "Dumping the stack's database to $SNAPSHOT_DIR/$file (read-only on the database)"
  compose exec -T db pg_dump -Fc --no-owner -U navigator navigator > "$SNAPSHOT_DIR/$file.tmp"
  mv "$SNAPSHOT_DIR/$file.tmp" "$SNAPSHOT_DIR/$file"
  ls -lh "$SNAPSHOT_DIR/$file"
  echo "It holds the cases, chats and feedback too: empty the board first if the demo should start clean."
}

case ${1:-} in
  setup) shift; setup "$@" ;;
  dump) shift; dump "$@" ;;
  *) sed -n '2,12p' "$0"; exit 1 ;;
esac
