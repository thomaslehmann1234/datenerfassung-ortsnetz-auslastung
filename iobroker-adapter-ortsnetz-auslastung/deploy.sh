#!/usr/bin/env bash
# Installs/updates the adapter in an ioBroker that runs in a Docker container on another host.
#
#   ./deploy.sh            test, pack, copy, install, upload, restart instances
#
# Targets come from deploy.env (not in version control), template: deploy.env.example
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
[[ -f "$HERE/deploy.env" ]] && source "$HERE/deploy.env"
HOST="${HOST:?Please set HOST in deploy.env, e.g. HOST=user@iobroker-host}"
HOST_SRC="${HOST_SRC:?Please set HOST_SRC in deploy.env (folder that appears in the container as CONTAINER_SRC)}"
CONTAINER_SRC="${CONTAINER_SRC:-/opt/iobroker/adapter-src}"
IOB_CONTAINER="${IOB_CONTAINER:-iobroker}"

cd "$HERE"
npm test --silent >/dev/null
rm -f iobroker.ortsnetz-auslastung-*.tgz
TGZ="$(npm pack --silent)"
echo "▶ $TGZ → $HOST"
scp -q "$TGZ" "$HOST:/tmp/"
# one SSH connection for all steps
ssh "$HOST" "set -e
  sudo cp /tmp/$TGZ $HOST_SRC/
  sudo docker exec $IOB_CONTAINER bash -lc 'cd /opt/iobroker && npm install $CONTAINER_SRC/$TGZ --omit=dev --no-audit --no-fund 2>&1 | tail -1'
  sudo docker exec $IOB_CONTAINER iobroker upload ortsnetz-auslastung 2>&1 | tail -1
  sudo docker exec $IOB_CONTAINER bash -lc 'iobroker list instances 2>/dev/null | grep -q \"ortsnetz-auslastung\\.\" || iobroker add ortsnetz-auslastung --enabled false'
  sudo docker exec $IOB_CONTAINER bash -lc 'for i in \$(iobroker list instances 2>/dev/null | grep -o \"ortsnetz-auslastung\\.[0-9]*\" | sort -u); do iobroker restart \$i; done' 2>&1 | tail -2"
rm -f "$TGZ"
echo "  ✔ adapter installed, files uploaded, instances restarted"
