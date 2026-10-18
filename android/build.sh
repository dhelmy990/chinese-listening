#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p wheels
if [[ ! -f wheels/aiohttp-3.14.5-py3-none-any.whl ]]; then
    AIOHTTP_NO_EXTENSIONS=1 python3 -m pip wheel --no-deps --no-binary=aiohttp \
        aiohttp==3.14.5 --wheel-dir wheels
fi
if [[ $# -eq 0 ]]; then set -- assembleDebug; fi
exec ./gradlew "$@"
