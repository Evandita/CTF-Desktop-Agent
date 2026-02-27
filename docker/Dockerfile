FROM kalilinux/kali-rolling

ENV DEBIAN_FRONTEND=noninteractive \
    DISPLAY=:1 \
    VNC_PORT=5900 \
    NOVNC_PORT=6080 \
    API_PORT=8888 \
    SCREEN_WIDTH=1024 \
    SCREEN_HEIGHT=768 \
    SCREEN_DEPTH=24

# System + Desktop + Security Tools
# Clear stale lists first (kali-rolling image ships with empty/stale lists)
RUN rm -rf /var/lib/apt/lists/* \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
    xfce4 xfce4-terminal dbus-x11 \
    tigervnc-standalone-server tigervnc-common novnc websockify \
    xdotool scrot imagemagick xclip xsel \
    supervisor curl wget git python3 python3-pip python3-venv \
    net-tools procps htop tmux vim nano \
    nmap gobuster dirb nikto whatweb \
    john hashcat \
    binwalk foremost steghide exiftool \
    python3-pwntools gdb gdbserver \
    radare2 \
    tshark tcpdump \
    sqlmap \
    netcat-traditional socat \
    hydra medusa \
    aircrack-ng \
    ltrace strace \
    file hexedit xxd \
    zip unzip p7zip-full \
    openvpn \
    firefox-esr \
    build-essential gcc g++ make \
    python3-dev libffi-dev libssl-dev \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# GDB enhancements: pwndbg
RUN git clone https://github.com/pwndbg/pwndbg /opt/pwndbg \
    && cd /opt/pwndbg && ./setup.sh

# Container API
COPY container_api/ /opt/container_api/
RUN python3 -m venv /opt/container_api/venv \
    && /opt/container_api/venv/bin/pip install --no-cache-dir \
       -r /opt/container_api/requirements.txt

# Visible terminal helper script
COPY scripts/ctf-exec.sh /usr/local/bin/ctf-exec
RUN chmod +x /usr/local/bin/ctf-exec
RUN mkdir -p /tmp/ctf-exec && chmod 1777 /tmp/ctf-exec

# Tmux config (mouse scroll + scrollback buffer)
COPY tmux.conf /etc/tmux.conf

# Supervisor + Entrypoint
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Create non-root user for the desktop session
RUN useradd -m -s /bin/bash ctfuser \
    && echo "ctfuser:ctfuser" | chpasswd \
    && mkdir -p /home/ctfuser/Desktop /home/ctfuser/challenges \
    && chown -R ctfuser:ctfuser /home/ctfuser

EXPOSE ${VNC_PORT} ${NOVNC_PORT} ${API_PORT}

ENTRYPOINT ["/entrypoint.sh"]
