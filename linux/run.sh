#!/usr/bin/env bash
# Bili23 - run from source (Linux)
cd "$(dirname "${BASH_SOURCE[0]}")"

if [ -x "venv/bin/python" ]; then
    exec venv/bin/python main.py "$@"
else
    exec python3 main.py "$@"
fi
