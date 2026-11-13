#!/bin/bash

# Load PATH and env vars (uv, etc.)
source /etc/profile.d/midsphere.sh

# Set display
export DISPLAY=${DISPLAY:-:0}

# CDP port for browser-use agent connection (fixed)
CHROME_CDP_PORT=9222

# Start Xvfb
Xvfb $DISPLAY -ac -screen 0 1024x768x24 -nolisten tcp &
sleep 2

# Start XFCE session
startxfce4 &
sleep 5

# Start VNC server
x11vnc -bg -display $DISPLAY -forever -wait 50 -shared -rfbport 5900 -nopw \
    -noxdamage -noxfixes -nowf -noscr -ping 1 -repeat -speeds lan &
sleep 2

nohup code-server > /tmp/code-server.log 2>&1 &

# Start noVNC server
cd /opt/noVNC/utils && ./novnc_proxy --vnc localhost:5900 --listen 6080 --web /opt/noVNC --heartbeat 30 &
sleep 2

# Start Google Chrome with CDP enabled for browser-use agent
# This allows browser-use to connect to an existing Chrome instance
# Use a dedicated profile directory to avoid lock conflicts
rm -rf /tmp/chrome-cdp-profile
mkdir -p /tmp/chrome-cdp-profile

# Wait for display to be ready
until xdpyinfo -display $DISPLAY >/dev/null 2>&1; do
    echo "Waiting for display $DISPLAY..."
    sleep 1
done

google-chrome-stable \
    --remote-debugging-port=$CHROME_CDP_PORT \
    --remote-debugging-address=0.0.0.0 \
    --no-sandbox \
    --disable-dev-shm-usage \
    --disable-gpu \
    --no-first-run \
    --no-default-browser-check \
    --disable-background-networking \
    --disable-sync \
    --disable-translate \
    --metrics-recording-only \
    --safebrowsing-disable-auto-update \
    --disable-features=TranslateUI \
    --user-data-dir=/tmp/chrome-cdp-profile \
    --start-maximized \
    --display=$DISPLAY \
    about:blank \
    &

# Wait for Chrome CDP to be ready
echo "Waiting for Chrome CDP to start..."
for i in $(seq 1 30); do
    if curl -s http://localhost:$CHROME_CDP_PORT/json/version >/dev/null 2>&1; then
        echo "Chrome CDP ready!"
        break
    fi
    sleep 1
done

echo "Chrome CDP available at http://localhost:$CHROME_CDP_PORT"
curl -s http://localhost:$CHROME_CDP_PORT/json/version | head -5

# Start agent server (only if vault credentials are available)
# Django migrations for sandbox-owned tables run automatically in __main__.py
# after vault secrets are loaded (needed for DATABASE_URL).
if [ -n "$VAULT_ADDR" ] && [ -n "$VAULT_TOKEN" ]; then
    cd /opt/.midsphere && nohup uv run python -m agent_server --port 8000 > /tmp/agent_server.log 2>&1 &
    echo "Agent server starting on port 8000"
else
    echo "Skipping agent server: VAULT_ADDR and VAULT_TOKEN not set"
fi