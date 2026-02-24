#!/bin/bash
set -e

export SCREEN_WIDTH=${SCREEN_WIDTH:-1024}
export SCREEN_HEIGHT=${SCREEN_HEIGHT:-768}
export SCREEN_DEPTH=${SCREEN_DEPTH:-24}

exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf
