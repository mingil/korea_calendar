#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

if [ "$1" = "--cli" ]; then
    python3 main.py --cli
else
    python3 main.py --host "${KOREA_CAL_HOST:-0.0.0.0}" --port "${KOREA_CAL_PORT:-8500}"
fi
