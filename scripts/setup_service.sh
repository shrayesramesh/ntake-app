#!/bin/bash

# Exit immediately if any command fails
set -e

# Get the absolute path of the project root
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CURRENT_USER="$(whoami)"
PROJECT_NAME="${PWD##*/}"
SERVICE_NAME="uvicorn-${PROJECT_NAME}"

echo "==================================================="
echo "Setting up stack for: ${PROJECT_NAME}"
echo "==================================================="

# 1. Setup Uvicorn Systemd Service
echo "[1/3] Configuring Uvicorn systemd service..."
sudo tee /etc/systemd/system/${SERVICE_NAME}.service > /dev/null << EOF
[Unit]
Description=Uvicorn ASGI Application (${SERVICE_NAME})
After=network.target

[Service]
User=${CURRENT_USER}
WorkingDirectory=${PROJECT_DIR}
ExecStart=${PROJECT_DIR}/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 2
Restart=always

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
# Removed reset-failed so it won't complain on a fresh install
sudo systemctl enable --now ${SERVICE_NAME}.service

# 2. Check/Setup Tailscale Connection
echo "[2/3] Checking Tailscale connection..."
if ! sudo tailscale status &>/dev/null; then
    echo "Tailscale is not logged in. Running 'sudo tailscale up'..."
    sudo tailscale up
else
    echo "Tailscale is already active."
fi

# 3. Configure Tailscale Serve (Background Proxy)
echo "[3/3] Configuring Tailscale Serve proxy for port 8000..."
sudo tailscale serve --bg 8000

echo "==================================================="
echo "Setup Complete!"
echo "Uvicorn Service : sudo systemctl status ${SERVICE_NAME}"
echo "Tailscale Serve : sudo tailscale serve status"
echo "==================================================="