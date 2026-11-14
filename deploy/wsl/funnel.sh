#!/usr/bin/env bash
# Publishes the running compose stack with Tailscale. Run on the WSL server,
# where `tailscale` is installed and logged in.
#
#   deploy/wsl/funnel.sh up      # web on Funnel :443, db on the tailnet only
#   deploy/wsl/funnel.sh up api  # also the backend directly on Funnel :8443
#   deploy/wsl/funnel.sh status
#   deploy/wsl/funnel.sh down    # removes every serve/funnel rule on this machine
#
# Funnel only allows public ports 443, 8443 and 10000.
# The database is NEVER put on Funnel (public internet): it uses `tailscale serve`,
# which only devices in your tailnet can reach.
set -euo pipefail

WEB_PORT="${WEB_HOST_PORT:-8080}"
API_PORT="${API_HOST_PORT:-8000}"
DB_PORT="${DB_HOST_PORT:-5433}"
TS="${TAILSCALE:-tailscale}"   # e.g. TAILSCALE="sudo tailscale"

case "${1:-}" in
  up)
    $TS funnel --bg --https=443 "http://127.0.0.1:${WEB_PORT}"
    if [[ "${2:-}" == "api" ]]; then
      $TS funnel --bg --https=8443 "http://127.0.0.1:${API_PORT}"
    fi
    $TS serve --bg --tcp=5432 "tcp://127.0.0.1:${DB_PORT}"
    $TS funnel status
    ;;
  status)
    $TS funnel status
    ;;
  down)
    $TS serve reset
    echo "All Tailscale serve and funnel rules removed."
    ;;
  *)
    echo "usage: $0 up [api] | status | down" >&2
    exit 2
    ;;
esac
