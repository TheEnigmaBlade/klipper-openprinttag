#!/usr/bin/env bash

set -eo pipefail

OPT_NAME="klipper-openprinttag"

OPT_DIR=$(readlink -f "$(dirname "$0")")
OPT_UV_DIR="$OPT_DIR"/.uv
OPT_UV="$OPT_UV_DIR"/uv
OPT_VENV="$OPT_DIR"/.venv

PRINTER_CONFIG_DIR="$HOME/printer_data/config"
MOONRAKER_CONFIG_FILE="$PRINTER_CONFIG_DIR/moonraker.conf"

install_uv() {
  # Check if uv is already available, otherwise install a local copy
  if command -v uv >/dev/null 2>&1; then
    OPT_UV=$(command -v uv)
  elif [ ! -x "$OPT_UV" ]; then
    local confirm
    echo "'uv' will be installed locally in $OPT_UV_DIR by downloading and executing the installer script:"
    echo
    echo "  https://astral.sh/uv/install.sh"
    echo
    echo "If you wish to install uv yourself, see: https://docs.astral.sh/uv/getting-started/installation/"
    echo
    if ! read -r -p "Download and execute the uv installer? [Y/n] " confirm ||
        [[ -n "$confirm" && ! "$confirm" =~ ^[Yy]([Ee][Ss])?$ ]]; then
      echo
      echo "Install cancelled"
      exit 1
    fi

    echo
    echo "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | UV_UNMANAGED_INSTALL="$OPT_UV_DIR" sh
  fi
}

create_venv() {
  if [ ! -f "$OPT_VENV/bin/activate" ]; then
    echo "Creating python virtual environment..."
    "$OPT_UV" venv --python '>=3.10' "$OPT_VENV"
  fi
}

install_deps() {
  echo "Installing python dependencies..."
  "$OPT_UV" sync --project "$OPT_DIR" --frozen --no-dev --no-install-project
}

create_service() {
  echo "Creating service..."

  sudo /bin/sh -c "cat > /etc/systemd/system/$OPT_NAME.service" <<EOF
[Unit]
Description=${OPT_NAME}
After=network-online.target moonraker.service

[Install]
WantedBy=multi-user.target

[Service]
Type=simple
User=${CURRENT_USER}
WorkingDirectory=${OPT_DIR}
ExecStart=${OPT_VENV}/bin/python3 -m klipper_openprinttag.app
Restart=always
RestartSec=5
EOF

  sudo systemctl enable $OPT_NAME
  sudo systemctl daemon-reload
}

setup_moonraker_update() {
  echo "Configuring Moonraker update..."
  if [ ! -w "$MOONRAKER_CONFIG_FILE" ]; then
    return 1
  fi

  cat >> "$MOONRAKER_CONFIG_FILE" <<EOF
[update_manager ${OPT_NAME}]
type: git_repo
channel: stable
path: ${OPT_DIR}
origin: https://github.com/TheEnigmaBlade/klipper-openprinttag
virtualenv: ${OPT_DIR}/.venv/bin/python
requirements: pyproject.toml
install_script: install.sh
managed_services:
  ${OPT_NAME}
EOF
}

#

install_uv

sudo systemctl stop "$OPT_NAME" 2>/dev/null || true

create_venv
install_deps
create_service
setup_moonraker_update

sudo systemctl restart $OPT_NAME
