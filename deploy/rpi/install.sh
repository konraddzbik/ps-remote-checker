#!/bin/bash
# Installs the PS Remote Checker home helper as a systemd service (Raspberry Pi OS / Debian / Ubuntu).
# Usage:  sudo ./install.sh [PAIRING-CODE]      (or put the code in pairing-code.txt next to this script)
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
CODE="${1:-$(cat "$DIR/pairing-code.txt" 2>/dev/null || true)}"
CODE="$(echo "$CODE" | tr -d '[:space:]')"

if [ "$(id -u)" -ne 0 ]; then echo "Run with sudo: sudo $0 $CODE"; exit 1; fi
if [ -z "$CODE" ]; then echo "Usage: sudo $0 PAIRING-CODE"; exit 1; fi
if [ ! -d "$DIR/ps_remote_checker" ]; then echo "ps_remote_checker/ folder must be next to this script"; exit 1; fi
command -v python3 >/dev/null || { apt-get update && apt-get install -y python3; }

# Validate the code with the checker itself.
(cd "$DIR" && python3 -c "from ps_remote_checker import relay; relay.normalize_code('$CODE')") \
  || { echo "Invalid pairing code: $CODE"; exit 1; }

install -d /opt/ps-remote-checker
rm -rf /opt/ps-remote-checker/ps_remote_checker
cp -r "$DIR/ps_remote_checker" /opt/ps-remote-checker/
id psrc >/dev/null 2>&1 || useradd --system --no-create-home --shell /usr/sbin/nologin psrc

cat > /etc/systemd/system/ps-remote-helper.service <<UNIT
[Unit]
Description=PS Remote Checker home helper (live Remote Play connection test)
After=network-online.target
Wants=network-online.target

[Service]
User=psrc
WorkingDirectory=/opt/ps-remote-checker
Environment=PYTHONDONTWRITEBYTECODE=1
ExecStart=/usr/bin/env python3 -u -m ps_remote_checker helper --code $CODE
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable --now ps-remote-helper
sleep 2
systemctl --no-pager --lines=8 status ps-remote-helper || true
echo
echo "✔ Home helper installed and running with pairing code $CODE"
echo "  Live log:   journalctl -u ps-remote-helper -f"
echo "  Uninstall:  sudo systemctl disable --now ps-remote-helper && sudo rm /etc/systemd/system/ps-remote-helper.service"
