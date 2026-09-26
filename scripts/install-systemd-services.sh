#!/bin/sh
set -eu

if [ "$(id -u)" -ne 0 ]; then
    echo "Run this installer with sudo." >&2
    exit 1
fi

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
unit_source="$project_dir/deploy/systemd"
unit_target=/etc/systemd/system

install -d -m 0755 /etc/vogelvrij
install -m 0644 \
    "$unit_source/vogelvrij-collector@.service" \
    "$unit_target/vogelvrij-collector@.service"
install -m 0644 \
    "$unit_source/vogelvrij-web@.service" \
    "$unit_target/vogelvrij-web@.service"

systemctl daemon-reload

echo "Installed Vogelvrij systemd templates."
echo "Provision /etc/vogelvrij/test.env or prod.env, then enable the matching @ instance."
