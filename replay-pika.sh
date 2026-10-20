#!/usr/bin/env bash
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
unset LD_PRELOAD LD_LIBRARY_PATH PYTHONPATH PYTHONHOME
exec /usr/bin/python -I "$root/tools/pika-recorder/replay-entry.py" "$@"
