#!/bin/sh
cd "$(dirname "$0")/app" || exit 1

if [ ! -x ".venv/bin/python" ]; then
  echo "First-time setup. This may take a minute..."
  python3 install.py || exit 1
fi

exec ".venv/bin/python" app.py "$@"
