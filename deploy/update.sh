#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────
#  Validator Pro — pull latest code and restart service
#  Run as root: bash update.sh
# ─────────────────────────────────────────────────────────────────
set -euo pipefail

APP_DIR="/opt/validator-pro"
SERVICE_NAME="validator-pro"
APP_USER="validatorpro"

echo "Pulling latest code..."
git -C "$APP_DIR" pull

echo "Updating dependencies..."
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt" -q

echo "Restarting service..."
systemctl restart "$SERVICE_NAME"
systemctl status  "$SERVICE_NAME" --no-pager

echo ""
echo "Done. Live at http://$(curl -s ifconfig.me 2>/dev/null || echo '<server-ip>')"
