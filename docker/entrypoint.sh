#!/bin/bash
set -e

export SCREEN_WIDTH=${SCREEN_WIDTH:-1024}
export SCREEN_HEIGHT=${SCREEN_HEIGHT:-768}
export SCREEN_DEPTH=${SCREEN_DEPTH:-24}

# Ensure ctfuser home directory has correct structure when using a fresh volume
if [ ! -d /home/ctfuser/Desktop ]; then
    mkdir -p /home/ctfuser/Desktop /home/ctfuser/challenges
fi
chown -R ctfuser:ctfuser /home/ctfuser

# Auto-restore extra packages from persistent volume
if [ -f /home/ctfuser/.extra-packages ]; then
    echo "[entrypoint] Restoring extra packages from .extra-packages..."
    apt-get update -qq
    xargs -a /home/ctfuser/.extra-packages apt-get install -y -qq 2>/dev/null || true
    echo "[entrypoint] Extra packages restored."
fi

exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf
