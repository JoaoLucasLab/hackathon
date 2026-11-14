#!/usr/bin/env bash
# Uploads the working tree to the WSL server and (re)starts the stack there.
# Images are built ON THE SERVER, so a Mac (arm64) can deploy to WSL (amd64).
#
#   deploy/wsl/push.sh user@server            # default dir ~/course-planner
#   deploy/wsl/push.sh user@server /srv/app
#
# The server's deploy/wsl/.env is never uploaded or deleted. Create it once on
# the server from deploy/wsl/.env.example.
set -euo pipefail

TARGET="${1:?usage: $0 user@server [remote_dir]}"
REMOTE_DIR="${2:-course-planner}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

rsync -az --delete \
  --exclude '.git/' --exclude '.venv/' --exclude 'node_modules/' --exclude 'dist/' \
  --exclude '__pycache__/' --exclude '.pytest_cache/' --exclude '.mypy_cache/' \
  --exclude '.ruff_cache/' --exclude '*.egg-info/' --exclude '.DS_Store' \
  --exclude '.env' --exclude 'scripts/out/' --exclude 'snapshots/' \
  "$ROOT/" "$TARGET:$REMOTE_DIR/"

# shellcheck disable=SC2029  # REMOTE_DIR is meant to expand locally.
ssh "$TARGET" "cd '$REMOTE_DIR' && test -f deploy/wsl/.env \
  || { echo 'Missing deploy/wsl/.env on the server: copy deploy/wsl/.env.example and fill it in.' >&2; exit 1; } \
  && docker compose -f deploy/wsl/compose.yaml --env-file deploy/wsl/.env up -d --build \
  && docker compose -f deploy/wsl/compose.yaml --env-file deploy/wsl/.env ps"
