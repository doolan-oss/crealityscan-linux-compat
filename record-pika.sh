#!/usr/bin/env bash
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# A clean native process environment; no Wine, proprietary SDK, GPU or preload.
unset LD_PRELOAD LD_LIBRARY_PATH PYTHONPATH PYTHONHOME
exec /usr/bin/python -I "$root/tools/pika-recorder/entry.py" "$@"
