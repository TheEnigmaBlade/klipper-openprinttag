#!/usr/bin/env bash

set -e

OPT_NAME="klipper-openprinttag"
OPT_DIR=$(readlink -f "$(dirname "$0")")
OPT_VENV="$OPT_DIR"/.venv

create_venv() {
  if [ ! -f "$VENV/bin/activate" ]; then
    echo "Creating python virtual environment..."
    virtualenv -p python3 --system-site-packages "$OPT_VENV"
  fi
}

install_deps() {
  echo "Installing python dependencies..."
  "$OPT_VENV"/bin/pip3 install "${OPT_DIR}" && "$OPT_VENV"/bin/pip3 uninstall -y klipper-openprinttag
}

create_service() {
  echo "Creating service..."

  sudo /bin/sh -c "cat > /etc/systemd/system/${OPT_NAME}.service" <<EOF
[Unit]
Description=$OPT_NAME
After=network-online.target moonraker.service

[Install]
WantedBy=multi-user.target

[Service]
Type=simple
User=${CURRENT_USER}
WorkingDirectory=$OPT_DIR
ExecStart=$OPT_VENV/bin/python3 -m klipper_openprinttag.app
Restart=always
RestartSec=5
EOF

  sudo systemctl enable $OPT_NAME
  sudo systemctl daemon-reload
}

#

sudo systemctl stop "${OPT_NAME}" 2>/dev/null || true

create_venv
install_deps
create_service

sudo systemctl restart $OPT_NAME
