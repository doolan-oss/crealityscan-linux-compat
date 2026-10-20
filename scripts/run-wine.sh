#!/usr/bin/env bash
set -euo pipefail
helpers=()
cleanup() {
  local status=$?
  trap - EXIT
  "$CREALITY_RUNNER/bin/wineserver" -k || true
  "$CREALITY_RUNNER/bin/wineserver" -w || true
  for pid in "${helpers[@]}"; do kill -TERM "$pid" 2>/dev/null || true; done
  for pid in "${helpers[@]}"; do wait "$pid" || status=3; done
  exit "$status"
}
trap cleanup EXIT
cd -- "$CREALITY_WORKDIR"
# Fail instead of silently running without a requested x64 helper.
/usr/bin/python3 - <<'PY_CHECK'
import ctypes, os
for path in filter(None, os.environ.get('LD_PRELOAD', '').split(':')):
    ctypes.CDLL(path, mode=os.RTLD_NOLOAD)
    print('Verified x64 process preload:', path, flush=True)
PY_CHECK
if [[ ${PIKA_CAMERA_BACKEND:-disabled} == v4l2 ]]; then
  /usr/bin/python3 "$CREALITY_SOURCE/src/usb-bridge/control-helper.py" "$PIKA_NODE_0" "$PIKA_NODE_1" > "$PIKA_CAPTURE_OUTPUT/controls.log" 2>&1 &
  helpers+=("$!")
  "$CREALITY_SOURCE/build/sdk-frame-helper" "$PIKA_NODE_0" "$PIKA_NODE_1" > "$PIKA_CAPTURE_OUTPUT/frames.log" 2>&1 &
  helpers+=("$!")
  for name in controls frames; do
    for ((i=0;i<50;i++)); do grep -q '^READY' "$PIKA_CAPTURE_OUTPUT/$name.log" && break; sleep .1; done
    grep -q '^READY' "$PIKA_CAPTURE_OUTPUT/$name.log"
  done
fi
if [[ ${CREALITY_SECONDS:-0} != 0 ]]; then
  timeout --kill-after=5s "$CREALITY_SECONDS" "$CREALITY_RUNNER/bin/wine" "$@"
else
  "$CREALITY_RUNNER/bin/wine" "$@"
fi
