#!/usr/bin/env bash
# Run this right before recording the demo. Starts the webhook app, the UI,
# and a fresh Cloudflare quick tunnel, then prints the URL you need to paste
# into the Razorpay Dashboard (Settings -> Webhooks -> edit the webhook URL)
# before doing anything that expects a real webhook to arrive.
#
# Quick tunnels are ephemeral by design (see SPEC.md) - this script exists
# so restarting one is a single command instead of five manual steps.

set -e
cd "$(dirname "$0")/.."
source .venv/Scripts/activate

echo "Stopping any previous webhook/UI/tunnel processes on 8787/8000..."
for port in 8787 8000; do
  pid=$(netstat -ano 2>/dev/null | grep ":$port " | grep LISTENING | awk '{print $NF}' | head -1)
  if [ -n "$pid" ]; then
    taskkill //F //PID "$pid" > /dev/null 2>&1 || true
  fi
done
pkill -f "cloudflared.exe" > /dev/null 2>&1 || true
sleep 1

echo "Starting webhook app on :8787..."
python -m uvicorn runtime.webhook_app:app --host 0.0.0.0 --port 8787 > recon/webhook_app.log 2>&1 &

echo "Starting UI app on :8000..."
python -m uvicorn runtime.ui_app:app --host 127.0.0.1 --port 8000 > recon/ui_app.log 2>&1 &

sleep 2

echo "Starting fresh Cloudflare quick tunnel..."
"/c/Program Files (x86)/cloudflared/cloudflared.exe" tunnel --url http://localhost:8787 > recon/cf_tunnel.log 2>&1 &

TUNNEL_URL=""
for i in 1 2 3 4 5 6 7 8; do
  sleep 1.5
  TUNNEL_URL=$(grep -o 'https://[a-zA-Z0-9-]*\.trycloudflare\.com' recon/cf_tunnel.log | head -1)
  if [ -n "$TUNNEL_URL" ]; then break; fi
done

echo ""
echo "=================================================================="
echo "UI:      http://127.0.0.1:8000"
echo "Tunnel:  ${TUNNEL_URL:-not found yet, check recon/cf_tunnel.log}"
echo ""
echo "ACTION REQUIRED before recording anything that needs a real webhook:"
echo "  Razorpay Dashboard -> Settings -> Webhooks -> edit the webhook"
echo "  -> set Webhook URL to: ${TUNNEL_URL}/webhook"
echo "  -> Save"
echo "=================================================================="
