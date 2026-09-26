#!/bin/sh
LIBRARY_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
export PYTHONDONTWRITEBYTECODE=1
export PYTHONUTF8=1
# Some ZIP extractors do not preserve executable permission.
if [ "$(uname -m)" = x86_64 ] && [ -f "$LIBRARY_DIR/runtime/linux-x64/bin/python3" ] && [ ! -x "$LIBRARY_DIR/runtime/linux-x64/bin/python3" ]; then
    chmod u+x "$LIBRARY_DIR/runtime/linux-x64/bin/python3" 2>/dev/null || true
fi
if [ "$(uname -m)" = x86_64 ] && [ -x "$LIBRARY_DIR/runtime/linux-x64/bin/python3" ]; then
    exec "$LIBRARY_DIR/runtime/linux-x64/bin/python3" "$LIBRARY_DIR/app/library.py" "$@"
fi
if command -v python3 >/dev/null 2>&1; then
    exec python3 "$LIBRARY_DIR/app/library.py" "$@"
fi
printf '%s\n' 'Python 3.9+ is required. Install Python and try again.'
exit 1
