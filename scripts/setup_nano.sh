#!/usr/bin/env bash
# Prepare a Jetson Nano 4GB (JetPack 4.6.x, Python 3.6) to run edgeface.
# Idempotent: safe to re-run. Each step can be skipped with a flag.
#
#   sudo scripts/setup_nano.sh [--skip-apt] [--skip-pip] [--skip-pycuda]
#                              [--skip-swap] [--skip-power] [--swap-gb N]
set -euo pipefail

SKIP_APT=0; SKIP_PIP=0; SKIP_PYCUDA=0; SKIP_SWAP=0; SKIP_POWER=0; SWAP_GB=4
while [ $# -gt 0 ]; do
  case "$1" in
    --skip-apt) SKIP_APT=1 ;;
    --skip-pip) SKIP_PIP=1 ;;
    --skip-pycuda) SKIP_PYCUDA=1 ;;
    --skip-swap) SKIP_SWAP=1 ;;
    --skip-power) SKIP_POWER=1 ;;
    --swap-gb) shift; SWAP_GB="$1" ;;
    *) echo "unknown flag: $1" >&2; exit 2 ;;
  esac
  shift
done

if [ "$(id -u)" -ne 0 ]; then echo "run with sudo" >&2; exit 1; fi
TARGET_USER="${SUDO_USER:-$(logname 2>/dev/null || echo root)}"
echo "== edgeface setup (user: $TARGET_USER)"

if [ "$SKIP_APT" -eq 0 ]; then
  echo "== apt packages"
  apt-get update
  apt-get install -y --no-install-recommends \
    python3-pip python3-dev python3-numpy python3-yaml python3-pyqt5 \
    build-essential sqlite3 tmux rsync v4l-utils
fi

if [ "$SKIP_PIP" -eq 0 ]; then
  echo "== pip packages (user $TARGET_USER, last releases supporting Python 3.6)"
  sudo -u "$TARGET_USER" python3 -m pip install --user --upgrade "pip<22" "setuptools<60"
  sudo -u "$TARGET_USER" python3 -m pip install --user "pytest<7.1" "requests==2.27.1"
fi

if [ "$SKIP_PYCUDA" -eq 0 ]; then
  echo "== pycuda (builds from source, ~15 min)"
  if sudo -u "$TARGET_USER" python3 -c "import pycuda.driver" 2>/dev/null; then
    echo "pycuda already installed"
  else
    export PATH=/usr/local/cuda/bin:$PATH
    export CPATH=/usr/local/cuda/include:${CPATH:-}
    export LIBRARY_PATH=/usr/local/cuda/lib64:${LIBRARY_PATH:-}
    # --no-build-isolation is required: with isolation pip tries to build numpy 1.12.1
    # from source for the build env, which fails on Ubuntu 18.04 (xlocale.h is gone).
    # Without it, pycuda builds against the system numpy 1.13.3.
    sudo -u "$TARGET_USER" \
      PATH="$PATH" CPATH="$CPATH" LIBRARY_PATH="$LIBRARY_PATH" \
      python3 -m pip install --user wheel
    sudo -u "$TARGET_USER" \
      PATH="$PATH" CPATH="$CPATH" LIBRARY_PATH="$LIBRARY_PATH" \
      python3 -m pip install --user --no-build-isolation "pycuda==2021.1"
  fi
fi

if [ "$SKIP_SWAP" -eq 0 ]; then
  echo "== swap (${SWAP_GB}G, needed while trtexec builds engines)"
  SWAPFILE=/var/swapfile
  if swapon --show=NAME | grep -qx "$SWAPFILE"; then
    echo "$SWAPFILE already active"
  else
    fallocate -l "${SWAP_GB}G" "$SWAPFILE" || dd if=/dev/zero of="$SWAPFILE" bs=1M count=$((SWAP_GB*1024))
    chmod 600 "$SWAPFILE"; mkswap "$SWAPFILE"; swapon "$SWAPFILE"
    grep -q "^$SWAPFILE" /etc/fstab || echo "$SWAPFILE none swap sw 0 0" >> /etc/fstab
  fi
fi

if [ "$SKIP_POWER" -eq 0 ]; then
  echo "== power mode MAXN (10W) + max clocks"
  echo "   NOTE: needs the 5V/4A barrel jack with jumper J48; micro-USB will throttle."
  nvpmodel -m 0 || true
  jetson_clocks || true
  nvpmodel -q || true
fi

echo "== runtime directories"
install -d -o "$TARGET_USER" -g "$TARGET_USER" -m 750 /var/lib/edgeface /var/lib/edgeface/evidence
# Owned by the service user: the engine writes the kiosk preview here (publisher.py).
install -d -o "$TARGET_USER" -g "$TARGET_USER" -m 755 /dev/shm/edgeface || true

echo "== versions"
python3 - <<'PY'
import importlib
for mod, attr in [("tensorrt", "__version__"), ("numpy", "__version__"),
                  ("cv2", "__version__"), ("yaml", "__version__"),
                  ("pycuda", "VERSION_TEXT"), ("sqlite3", "sqlite_version")]:
    try:
        m = importlib.import_module(mod)
        print("  {:10s} {}".format(mod, getattr(m, attr, "?")))
    except Exception as exc:
        print("  {:10s} MISSING ({})".format(mod, exc))
PY
echo "== done. Next: scripts/build_engines.sh"
