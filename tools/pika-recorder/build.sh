#!/usr/bin/env bash
set -euo pipefail
here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# Build atomically; existing runnable binary remains intact if compilation fails.
output=$(mktemp "$here/.capture-build.XXXXXX")
trap 'rm -f -- "$output"' EXIT
/usr/bin/cc -std=gnu11 -O2 -Wall -Wextra -Werror -o "$output" "$here/capture.c"
chmod 755 "$output"
mv -- "$output" "$here/capture"
cd -- "$here"
/usr/bin/python3 -m unittest discover -v -p 'test_*.py'
