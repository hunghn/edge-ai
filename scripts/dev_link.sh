#!/usr/bin/env bash
# Development link between a server running in WSL2 and the Nano.
#
#   scripts/dev_link.sh up        # install + start everything, end to end
#   scripts/dev_link.sh status    # what is running, on both machines
#   scripts/dev_link.sh logs      # follow the server log
#   scripts/dev_link.sh down      # stop everything (nothing is uninstalled)
#   scripts/dev_link.sh check     # run one sync cycle on the Nano and report
#
# WSL2 is behind NAT, so the Nano cannot dial in. Instead the dev machine opens an SSH
# reverse tunnel: port 8000 on the Nano is forwarded to the server listening on
# 127.0.0.1:8000 in WSL. Three systemd *user* services keep it alive:
#
#   dev machine : edgeface-server (uvicorn), edgeface-tunnel (ssh -R, Restart=always)
#   Nano        : edgeface-sync (the real sync process, talking to 127.0.0.1:8000)
#
# This is for development and demos. A clinic deployment puts the server on a real PC in
# the LAN with HTTPS — see server/README.md.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
NANO_HOST="${EDGEFACE_NANO_HOST:-nano}"
DEVICE_ID="${EDGEFACE_DEVICE_ID:-kiosk-01}"
PORT="${EDGEFACE_PORT:-8000}"
PYTHON="${EDGEFACE_PYTHON:-$REPO/.venv/bin/python}"
NANO_REPO="${EDGEFACE_NANO_REPO:-\$HOME/edge-ai}"

LOCAL_UNITS="$HOME/.config/systemd/user"
LOCAL_ENV_DIR="$HOME/.config/edgeface"
LOCAL_STATE="$HOME/.local/share/edgeface"

say() { printf '\033[1m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[33m warn:\033[0m %s\n' "$*"; }

require_nano() {
  ssh -o BatchMode=yes -o ConnectTimeout=8 "$NANO_HOST" true 2>/dev/null && return 0
  echo "cannot reach '$NANO_HOST' over SSH with key auth." >&2
  echo "add a Host entry to ~/.ssh/config and copy your key with ssh-copy-id first." >&2
  exit 1
}

write_local_units() {
  mkdir -p "$LOCAL_UNITS" "$LOCAL_ENV_DIR" "$LOCAL_STATE"

  if [ ! -f "$LOCAL_ENV_DIR/server.env" ]; then
    # A per-install secret: without it every restart logs the admin out.
    secret="$("$PYTHON" -c 'import secrets;print(secrets.token_hex(32))')"
    cat > "$LOCAL_ENV_DIR/server.env" <<EOF
EDGEFACE_DB=sqlite:///$LOCAL_STATE/server.db
EDGEFACE_SECRET=$secret
EDGEFACE_BUNDLES=$LOCAL_STATE/bundles
EDGEFACE_BUNDLE_KEY=$LOCAL_STATE/bundle.key
PYTHONPATH=$REPO
EOF
    chmod 600 "$LOCAL_ENV_DIR/server.env"
    say "wrote $LOCAL_ENV_DIR/server.env"
  fi

  cat > "$LOCAL_UNITS/edgeface-server.service" <<EOF
[Unit]
Description=edgeface server (development, WSL)
After=network.target

[Service]
Type=simple
WorkingDirectory=$REPO
EnvironmentFile=$LOCAL_ENV_DIR/server.env
# Bound to localhost on purpose: the Nano reaches it through the SSH tunnel, so the
# port is never exposed to the LAN by accident.
ExecStart=$PYTHON -m uvicorn server.app:app --host 127.0.0.1 --port $PORT --log-level info
Restart=always
RestartSec=3

[Install]
WantedBy=default.target
EOF

  cat > "$LOCAL_UNITS/edgeface-tunnel.service" <<EOF
[Unit]
Description=edgeface reverse tunnel to $NANO_HOST
After=edgeface-server.service
Requires=edgeface-server.service

[Service]
Type=simple
# -N: no remote command, just forwarding. ExitOnForwardFailure makes the unit fail fast
# when port $PORT is already taken on the Nano, instead of pretending to work.
ExecStart=/usr/bin/ssh -N -T \\
  -o BatchMode=yes -o ExitOnForwardFailure=yes \\
  -o ServerAliveInterval=20 -o ServerAliveCountMax=3 \\
  -R $PORT:127.0.0.1:$PORT $NANO_HOST
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
EOF
  systemctl --user daemon-reload
  say "installed user units: edgeface-server, edgeface-tunnel"
}

ensure_device_token() {
  # Reuse the token we already handed the Nano; only mint a new one when there is none.
  local existing
  existing="$(ssh "$NANO_HOST" "grep -s '^EDGEFACE_TOKEN=' \$HOME/.config/edgeface/sync.env | cut -d= -f2-" || true)"
  if [ -n "$existing" ]; then
    say "device '$DEVICE_ID' already has a token on the Nano"
    return 0
  fi
  local token
  token="$(set -a; . "$LOCAL_ENV_DIR/server.env"; set +a; cd "$REPO" && \
    "$PYTHON" -m server.cli create-device --id "$DEVICE_ID" --name "Nano dev kiosk" \
    | awk '/^token/ {print $NF}')"
  if [ -z "$token" ]; then
    echo "could not create the device token" >&2
    exit 1
  fi
  ssh "$NANO_HOST" "mkdir -p \$HOME/.config/edgeface && \
    printf 'EDGEFACE_SERVER=http://127.0.0.1:$PORT\nEDGEFACE_DEVICE_ID=$DEVICE_ID\nEDGEFACE_TOKEN=%s\n' '$token' \
    > \$HOME/.config/edgeface/sync.env && chmod 600 \$HOME/.config/edgeface/sync.env"
  say "created device '$DEVICE_ID'; token stored on the Nano (mode 600), not printed here"
}

write_nano_unit() {
  ssh "$NANO_HOST" "mkdir -p \$HOME/.config/systemd/user \$HOME/var && \
cat > \$HOME/.config/systemd/user/edgeface-sync.service <<UNIT
[Unit]
Description=edgeface sync (development, via the SSH reverse tunnel)
After=network.target

[Service]
Type=simple
WorkingDirectory=$NANO_REPO
Environment=PYTHONPATH=$NANO_REPO/src
EnvironmentFile=%h/.config/edgeface/sync.env
ExecStart=/usr/bin/python3 -m edgeface.sync --config %h/sync_nano.yaml
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
UNIT
[ -f \$HOME/sync_nano.yaml ] || cat > \$HOME/sync_nano.yaml <<CFG
# Development config for the sync process. The engine has its own config.
backend: trt
models: {dir: models/engines}
storage: {db_path: \$HOME/var/edge.db, evidence_dir: \$HOME/var/evidence}
capture: {source: file, path: \$HOME/sample.mp4}
sync: {server_url: 'http://127.0.0.1:$PORT', bundles_dir: \$HOME/var/bundles}
CFG
systemctl --user daemon-reload"
  say "installed edgeface-sync on $NANO_HOST"
}

cmd_up() {
  require_nano
  write_local_units
  systemctl --user enable --now edgeface-server.service
  sleep 2
  systemctl --user enable --now edgeface-tunnel.service
  sleep 2
  ensure_device_token
  write_nano_unit
  ssh "$NANO_HOST" "systemctl --user enable --now edgeface-sync.service" || \
    warn "could not start edgeface-sync on the Nano; see 'scripts/dev_link.sh status'"
  echo
  cmd_status
  echo
  say "admin UI: http://127.0.0.1:$PORT/admin/  (create a login with:"
  echo "    set -a; . $LOCAL_ENV_DIR/server.env; set +a; $PYTHON -m server.cli create-admin --username admin)"
  warn "user services stop when your session ends unless lingering is enabled:"
  echo "    sudo loginctl enable-linger \$USER          # on this machine"
  echo "    ssh $NANO_HOST 'sudo loginctl enable-linger \$USER'"
}

cmd_down() {
  systemctl --user disable --now edgeface-tunnel.service 2>/dev/null || true
  systemctl --user disable --now edgeface-server.service 2>/dev/null || true
  ssh -o BatchMode=yes "$NANO_HOST" "systemctl --user disable --now edgeface-sync.service" \
    2>/dev/null || true
  say "stopped (units stay installed; 'up' starts them again)"
}

cmd_status() {
  say "dev machine"
  for unit in edgeface-server edgeface-tunnel; do
    # is-active prints the state and exits non-zero when it is not active, so the
    # output is the answer; a fallback echo would print it twice.
    printf '  %-18s %s\n' "$unit" "$(systemctl --user is-active $unit.service 2>/dev/null)"
  done
  if "$PYTHON" - <<PY 2>/dev/null
import urllib.request, sys
try:
    urllib.request.urlopen("http://127.0.0.1:$PORT/healthz", timeout=3)
except Exception:
    sys.exit(1)
PY
  then printf '  %-18s reachable on 127.0.0.1:%s\n' "server" "$PORT"
  else printf '  %-18s NOT reachable on 127.0.0.1:%s\n' "server" "$PORT"; fi

  say "$NANO_HOST"
  ssh -o BatchMode=yes -o ConnectTimeout=8 "$NANO_HOST" "
    printf '  %-18s %s\n' edgeface-sync \"\$(systemctl --user is-active edgeface-sync.service 2>/dev/null || echo inactive)\"
    python3 -c \"
import urllib.request
try:
    urllib.request.urlopen('http://127.0.0.1:$PORT/healthz', timeout=3)
    print('  %-18s tunnel OK (server answers on the Nano)' % 'link')
except Exception as exc:
    print('  %-18s tunnel DOWN: %s' % ('link', exc))\"" 2>/dev/null || \
    warn "could not query $NANO_HOST"
}

cmd_logs() {
  journalctl --user -u edgeface-server -u edgeface-tunnel -f
}

cmd_check() {
  require_nano
  say "one sync cycle on $NANO_HOST"
  ssh "$NANO_HOST" "set -a; . \$HOME/.config/edgeface/sync.env; set +a; \
    cd $NANO_REPO && python3 -m edgeface.sync --config \$HOME/sync_nano.yaml --once 2>&1 | tail -3"
}

case "${1:-}" in
  up) cmd_up ;;
  down) cmd_down ;;
  status) cmd_status ;;
  logs) cmd_logs ;;
  check) cmd_check ;;
  *) sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
