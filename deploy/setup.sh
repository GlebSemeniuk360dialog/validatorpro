#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────
#  Validator Pro — one-shot VPS setup script
#  Tested on Ubuntu 22.04 / Debian 12
#  Run as root (or with sudo): bash setup.sh
# ─────────────────────────────────────────────────────────────────
set -euo pipefail

APP_DIR="/opt/validator-pro"
SERVICE_NAME="validator-pro"
APP_USER="validatorpro"
PORT=8502

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║   Validator Pro — server setup           ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# ── 1. System packages ───────────────────────────────────────────
echo "[1/6] Installing system packages..."
apt-get update -qq
apt-get install -y -qq python3 python3-pip python3-venv git nginx curl

# ── 2. App user ──────────────────────────────────────────────────
echo "[2/6] Creating app user '$APP_USER'..."
id "$APP_USER" &>/dev/null || useradd --system --shell /bin/bash --create-home "$APP_USER"

# ── 3. Clone / pull repo ─────────────────────────────────────────
echo "[3/6] Cloning repo into $APP_DIR..."
if [ -d "$APP_DIR/.git" ]; then
  echo "  → Repo already exists, pulling latest..."
  git -C "$APP_DIR" pull
else
  git clone https://gitverse.ru/360dialog/360dialog.git "$APP_DIR"
fi
chown -R "$APP_USER":"$APP_USER" "$APP_DIR"

# ── 4. Python venv + deps ────────────────────────────────────────
echo "[4/6] Setting up Python virtualenv and installing dependencies..."
sudo -u "$APP_USER" python3 -m venv "$APP_DIR/.venv"
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install --upgrade pip -q
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt" -q

# ── 5. .env check ────────────────────────────────────────────────
echo "[5/6] Checking for .env..."
if [ ! -f "$APP_DIR/.env" ]; then
  cp "$APP_DIR/.env.example" "$APP_DIR/.env"
  chown "$APP_USER":"$APP_USER" "$APP_DIR/.env"
  chmod 600 "$APP_DIR/.env"
  echo ""
  echo "  ⚠  .env created from template."
  echo "     Edit $APP_DIR/.env and fill in your tokens, then run:"
  echo "     systemctl start $SERVICE_NAME"
  echo ""
fi

# ── 6. systemd service ───────────────────────────────────────────
echo "[6/6] Installing systemd service..."
cp "$(dirname "$0")/validator-pro.service" /etc/systemd/system/
# Patch the service file with the real app dir (in case it differs)
sed -i "s|/opt/validator-pro|$APP_DIR|g" /etc/systemd/system/validator-pro.service
sed -i "s|validatorpro|$APP_USER|g"       /etc/systemd/system/validator-pro.service

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"

# ── nginx ────────────────────────────────────────────────────────
echo ""
echo "Configuring nginx..."
cp "$(dirname "$0")/nginx.conf" /etc/nginx/sites-available/validator-pro
ln -sf /etc/nginx/sites-available/validator-pro /etc/nginx/sites-enabled/validator-pro
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  Setup complete!                                             ║"
echo "║                                                              ║"
echo "║  Next steps:                                                 ║"
echo "║  1. Edit /opt/validator-pro/.env  (fill in your tokens)     ║"
echo "║  2. systemctl start validator-pro                            ║"
echo "║  3. Open http://<your-server-ip> in a browser               ║"
echo "║                                                              ║"
echo "║  Useful commands:                                            ║"
echo "║    systemctl status validator-pro   ← is it running?        ║"
echo "║    journalctl -u validator-pro -f   ← live logs             ║"
echo "║    systemctl restart validator-pro  ← restart after changes ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
