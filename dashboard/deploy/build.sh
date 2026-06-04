#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR/server"

CGO_ENABLED=1 go build -trimpath -ldflags="-s -w" -o "$APP_DIR/mcibench-server" ./cmd/server
chmod +x "$APP_DIR/mcibench-server"

echo "Built $APP_DIR/mcibench-server"
