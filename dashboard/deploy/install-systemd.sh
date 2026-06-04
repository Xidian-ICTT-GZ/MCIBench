#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_FILE="/etc/systemd/system/mcibench.service"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run with root privileges: sudo bash scripts/install-systemd.sh"
  exit 1
fi

sed "s#__APP_DIR__#$APP_DIR#g" "$APP_DIR/systemd/mcibench.service" > "$SERVICE_FILE"
systemctl daemon-reload
systemctl enable mcibench
systemctl restart mcibench
systemctl status mcibench --no-pager
