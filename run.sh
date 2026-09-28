#!/usr/bin/env bash
# macOS / Linux wrapper for run.py.
#
# Some systems ship only `python3`, some only `python`. This picks whichever
# exists and is version 3.11 or newer, rather than failing on the name.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

for candidate in python3 python python3.13 python3.12 python3.11; do
  if command -v "$candidate" >/dev/null 2>&1; then
    if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
      exec "$candidate" "$here/run.py" "$@"
    fi
  fi
done

cat >&2 <<'MSG'

  No Python 3.11 or newer was found on PATH.

  macOS:   brew install python@3.12
  Debian:  sudo apt install python3.12 python3.12-venv
  or download from https://www.python.org/downloads/

  Then run:  ./run.sh setup

MSG
exit 1
