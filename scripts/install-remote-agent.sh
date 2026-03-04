#!/usr/bin/env bash
# install-remote-agent.sh
#
# Lightweight installer for deploying the CTF Desktop Agent API on any Linux
# machine (physical, VM, cloud instance). This installs only the container_api
# service — the same FastAPI app that runs inside Docker — so the host-side
# CTF agent can connect to it over the network.
#
# Usage:
#   ./install-remote-agent.sh [--user USERNAME] [--port PORT] [--display DISPLAY]
#
# After installation:
#   sudo systemctl start ctf-agent-api
#   sudo systemctl status ctf-agent-api
#
# Connect from the host machine:
#   ctf-agent interactive --no-container --api-url http://<remote-ip>:8888
#   # Or via web UI with CTF_REMOTE_API_URL=http://<remote-ip>:8888 make web

set -euo pipefail

# ---------- defaults ----------
INSTALL_DIR="/opt/ctf-agent-api"
SERVICE_USER=""
API_PORT=8888
DISPLAY_NUM=":0"
SCREEN_WIDTH=1024
SCREEN_HEIGHT=768
SCREEN_DEPTH=24

# ---------- parse args ----------
while [[ $# -gt 0 ]]; do
    case $1 in
        --user)    SERVICE_USER="$2"; shift 2 ;;
        --port)    API_PORT="$2"; shift 2 ;;
        --display) DISPLAY_NUM="$2"; shift 2 ;;
        --width)   SCREEN_WIDTH="$2"; shift 2 ;;
        --height)  SCREEN_HEIGHT="$2"; shift 2 ;;
        --help|-h)
            echo "Usage: $0 [--user USERNAME] [--port PORT] [--display DISPLAY]"
            echo ""
            echo "Options:"
            echo "  --user USERNAME    System user to run the service as (default: current user)"
            echo "  --port PORT        API port (default: 8888)"
            echo "  --display DISPLAY  X11 display (default: :0 — use :1 for headless Xvfb)"
            echo "  --width WIDTH      Screen width for Xvfb (default: 1024)"
            echo "  --height HEIGHT    Screen height for Xvfb (default: 768)"
            exit 0
            ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

if [[ -z "$SERVICE_USER" ]]; then
    SERVICE_USER="$(whoami)"
fi

# ---------- detect script location & source files ----------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CONTAINER_API_SRC="$REPO_ROOT/docker/container_api"

if [[ ! -d "$CONTAINER_API_SRC" ]]; then
    echo "ERROR: Cannot find docker/container_api/ relative to this script."
    echo "       Run this script from the CTF-Desktop-Agent repository."
    exit 1
fi

echo "========================================"
echo " CTF Desktop Agent — Remote API Installer"
echo "========================================"
echo "Install dir : $INSTALL_DIR"
echo "Service user: $SERVICE_USER"
echo "API port    : $API_PORT"
echo "Display     : $DISPLAY_NUM"
echo "Screen      : ${SCREEN_WIDTH}x${SCREEN_HEIGHT}x${SCREEN_DEPTH}"
echo ""

# ---------- check for root ----------
if [[ $EUID -ne 0 ]]; then
    echo "This script requires root. Re-running with sudo..."
    exec sudo "$0" --user "$SERVICE_USER" --port "$API_PORT" --display "$DISPLAY_NUM" \
        --width "$SCREEN_WIDTH" --height "$SCREEN_HEIGHT"
fi

# ---------- install system dependencies ----------
echo "[1/5] Installing system dependencies..."

if command -v apt-get &>/dev/null; then
    apt-get update -qq
    apt-get install -y -qq \
        python3 python3-venv python3-pip \
        xdotool scrot imagemagick xclip tmux xterm \
        xvfb \
        libavformat-dev libavcodec-dev libavdevice-dev libavutil-dev \
        libswscale-dev libswresample-dev pkg-config \
        2>&1 | tail -1
elif command -v dnf &>/dev/null; then
    dnf install -y -q \
        python3 python3-pip \
        xdotool scrot ImageMagick xclip tmux xterm \
        xorg-x11-server-Xvfb \
        ffmpeg-free-devel pkg-config
elif command -v pacman &>/dev/null; then
    pacman -Sy --noconfirm \
        python python-pip \
        xdotool scrot imagemagick xclip tmux xterm \
        xorg-server-xvfb \
        ffmpeg pkg-config
else
    echo "WARNING: Unsupported package manager. Install these manually:"
    echo "  python3, xdotool, scrot, imagemagick, xclip, tmux, xterm, xvfb, ffmpeg dev libs"
fi

# ---------- copy API files ----------
echo "[2/5] Copying container API files to $INSTALL_DIR..."

mkdir -p "$INSTALL_DIR"
cp -r "$CONTAINER_API_SRC/"* "$INSTALL_DIR/"
chown -R "$SERVICE_USER":"$SERVICE_USER" "$INSTALL_DIR"

# ---------- create virtual environment ----------
echo "[3/5] Creating Python virtual environment..."

sudo -u "$SERVICE_USER" python3 -m venv "$INSTALL_DIR/venv"
sudo -u "$SERVICE_USER" "$INSTALL_DIR/venv/bin/pip" install --quiet --upgrade pip
sudo -u "$SERVICE_USER" "$INSTALL_DIR/venv/bin/pip" install --quiet -r "$INSTALL_DIR/requirements.txt"

# ---------- create systemd service ----------
echo "[4/5] Creating systemd service..."

cat > /etc/systemd/system/ctf-agent-api.service <<EOF
[Unit]
Description=CTF Desktop Agent API
After=network.target

[Service]
Type=simple
User=$SERVICE_USER
WorkingDirectory=$INSTALL_DIR
Environment=DISPLAY=$DISPLAY_NUM
Environment=SCREEN_WIDTH=$SCREEN_WIDTH
Environment=SCREEN_HEIGHT=$SCREEN_HEIGHT
Environment=SCREEN_DEPTH=$SCREEN_DEPTH
Environment=API_PORT=$API_PORT
ExecStart=$INSTALL_DIR/venv/bin/uvicorn server:app --host 0.0.0.0 --port $API_PORT
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Optional: Xvfb service (for headless machines without a display)
cat > /etc/systemd/system/ctf-agent-xvfb.service <<EOF
[Unit]
Description=Xvfb Virtual Framebuffer for CTF Agent
Before=ctf-agent-api.service

[Service]
Type=simple
ExecStart=/usr/bin/Xvfb $DISPLAY_NUM -screen 0 ${SCREEN_WIDTH}x${SCREEN_HEIGHT}x${SCREEN_DEPTH}
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload

# ---------- create helper script ----------
echo "[5/5] Creating helper scripts..."

cat > "$INSTALL_DIR/start.sh" <<'SCRIPT'
#!/usr/bin/env bash
# Quick start without systemd (for testing)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/venv/bin/activate"
export DISPLAY="${DISPLAY:-:0}"
export SCREEN_WIDTH="${SCREEN_WIDTH:-1024}"
export SCREEN_HEIGHT="${SCREEN_HEIGHT:-768}"
export API_PORT="${API_PORT:-8888}"
exec uvicorn server:app --host 0.0.0.0 --port "$API_PORT"
SCRIPT
chmod +x "$INSTALL_DIR/start.sh"

# ---------- done ----------
echo ""
echo "========================================"
echo " Installation complete!"
echo "========================================"
echo ""
echo "For headless machines (no physical display):"
echo "  sudo systemctl enable --now ctf-agent-xvfb"
echo "  sudo systemctl enable --now ctf-agent-api"
echo ""
echo "For machines with an existing display ($DISPLAY_NUM):"
echo "  sudo systemctl enable --now ctf-agent-api"
echo ""
echo "Quick test (no systemd):"
echo "  cd $INSTALL_DIR && ./start.sh"
echo ""
echo "Verify:"
echo "  curl http://localhost:$API_PORT/health/"
echo ""
echo "Connect from CTF agent:"
echo "  ctf-agent interactive --no-container --api-url http://$(hostname -I | awk '{print $1}'):$API_PORT"
echo ""
