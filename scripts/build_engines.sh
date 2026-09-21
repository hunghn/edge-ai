#!/usr/bin/env bash
# Build TensorRT FP16 engines from models/onnx/*.onnx ON THE JETSON NANO.
# Engines are device- and TensorRT-version-specific and must never be committed.
#
#   scripts/build_engines.sh [--models "det_500m w600k_mbf"] [--workspace 1024]
#                            [--force] [--verbose]
#
# Building all five engines takes roughly 30-60 min on a Nano and is memory hungry:
# close the desktop session or add swap if trtexec gets killed.
#
# For every engine a sidecar <name>.engine.json records the source ONNX sha256, the
# TensorRT version and the build arguments, so stale engines can be detected later
# (scripts/verify_models.py).
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
ONNX_DIR="$REPO/models/onnx"
ENGINE_DIR="$REPO/models/engines"
LOG_DIR="$REPO/logs"
TRTEXEC="${TRTEXEC:-/usr/src/tensorrt/bin/trtexec}"
WORKSPACE=1024
FORCE=0
VERBOSE=0
MODELS="det_500m 2d106det w600k_mbf minifasnet_v2_2.7 minifasnet_v1se_4.0"

while [ $# -gt 0 ]; do
  case "$1" in
    --models) shift; MODELS="$1" ;;
    --workspace) shift; WORKSPACE="$1" ;;
    --force) FORCE=1 ;;
    --verbose) VERBOSE=1 ;;   # full tactic log; slower and much larger logs
    *) echo "unknown flag: $1" >&2; exit 2 ;;
  esac
  shift
done

[ -x "$TRTEXEC" ] || { echo "trtexec not found at $TRTEXEC (set TRTEXEC=...)" >&2; exit 1; }
mkdir -p "$ENGINE_DIR" "$LOG_DIR"

TRT_VERSION="$(python3 -c 'import tensorrt; print(tensorrt.__version__)' 2>/dev/null || echo unknown)"
echo "TensorRT $TRT_VERSION · workspace ${WORKSPACE}MB · FP16"

for name in $MODELS; do
  onnx="$ONNX_DIR/$name.onnx"
  engine="$ENGINE_DIR/$name.engine"
  log="$LOG_DIR/build_$name.log"
  [ -f "$onnx" ] || { echo "SKIP $name: $onnx missing"; continue; }
  if [ -f "$engine" ] && [ "$FORCE" -eq 0 ]; then
    echo "SKIP $name: engine exists (use --force to rebuild)"
    continue
  fi
  sha="$(sha256sum "$onnx" | cut -d' ' -f1)"
  echo -n "BUILD $name ... "
  VERBOSE_FLAG=""
  [ "$VERBOSE" -eq 1 ] && VERBOSE_FLAG="--verbose"
  if "$TRTEXEC" --onnx="$onnx" --fp16 --workspace="$WORKSPACE" \
       --saveEngine="$engine" $VERBOSE_FLAG > "$log" 2>&1; then
    python3 - "$engine.json" "$name" "$sha" "$TRT_VERSION" "$WORKSPACE" <<'PY'
import json, sys, time
path, name, sha, trt_version, workspace = sys.argv[1:6]
json.dump({"model": name, "onnx_sha256": sha, "tensorrt": trt_version,
           "precision": "fp16", "workspace_mb": int(workspace),
           "built_at": time.time()}, open(path, "w"), indent=2)
PY
    # trtexec prints its own latency summary; keep the mean as a first data point.
    echo "OK  $(grep -m1 'mean =' "$log" | sed 's/^.*mean = //' || true)"
  else
    echo "FAILED — see $log"
    tail -5 "$log" | sed 's/^/    /'
  fi
done
echo "Engines in $ENGINE_DIR (gitignored). Next: python3 scripts/bench_model.py --all"
