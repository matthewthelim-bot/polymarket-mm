#!/bin/bash
# setup_server.sh — run once on a fresh Ubuntu 24.04 server
# Usage: bash setup_server.sh
set -e

REPO_URL="$1"   # pass your GitHub repo URL as first argument
APP_DIR="/opt/polymarket-mm"
SERVICE_USER="polymarket"

echo "=== Polymarket Collector Server Setup ==="
echo

if [ -z "$REPO_URL" ]; then
    echo "Usage: bash setup_server.sh https://github.com/YOUR_USERNAME/polymarket-mm.git"
    exit 1
fi

# 1. System packages
echo "[1/6] Installing system packages..."
apt-get update -qq
apt-get install -y python3 python3-pip python3-venv git > /dev/null

# 2. Create dedicated non-root user
echo "[2/6] Creating service user '$SERVICE_USER'..."
if ! id "$SERVICE_USER" &>/dev/null; then
    useradd -r -m -d /home/$SERVICE_USER -s /bin/bash $SERVICE_USER
fi

# 3. Clone repo
echo "[3/6] Cloning repo to $APP_DIR..."
if [ -d "$APP_DIR" ]; then
    echo "  Directory exists — pulling latest..."
    git -C "$APP_DIR" pull
else
    git clone "$REPO_URL" "$APP_DIR"
fi
chown -R $SERVICE_USER:$SERVICE_USER "$APP_DIR"

# 4. Python venv + deps
echo "[4/6] Installing Python dependencies..."
sudo -u $SERVICE_USER python3 -m venv "$APP_DIR/venv"
sudo -u $SERVICE_USER "$APP_DIR/venv/bin/pip" install -q --upgrade pip
sudo -u $SERVICE_USER "$APP_DIR/venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"

# 5. Data directory
echo "[5/6] Creating data directory..."
mkdir -p "$APP_DIR/data/live"
chown -R $SERVICE_USER:$SERVICE_USER "$APP_DIR/data"

# 6. systemd service
echo "[6/6] Installing systemd service..."
cat > /etc/systemd/system/polymarket-collector.service << 'SERVICE'
[Unit]
Description=Polymarket Book Collector
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=polymarket
WorkingDirectory=/opt/polymarket-mm
EnvironmentFile=/opt/polymarket-mm/.env
ExecStart=/opt/polymarket-mm/venv/bin/python scripts/collect_books.py \
    --out /opt/polymarket-mm/data/live \
    --min-volume 20000 \
    --stats-interval 300
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=polymarket-collector

[Install]
WantedBy=multi-user.target
SERVICE

systemctl daemon-reload
systemctl enable polymarket-collector

echo
echo "=== Setup complete ==="
echo
echo "Next step: copy your .env file to the server:"
echo "  scp .env ubuntu@<server-ip>:/opt/polymarket-mm/.env"
echo "  sudo chown polymarket:polymarket /opt/polymarket-mm/.env"
echo "  sudo chmod 600 /opt/polymarket-mm/.env"
echo
echo "Then start the collector:"
echo "  sudo systemctl start polymarket-collector"
echo "  sudo journalctl -u polymarket-collector -f"
echo
