#!/bin/sh
set -eu
# Legacy mutable-main reexec was removed by R11. Exercise its replacement contract.
cd "$(dirname "$0")/.."
exec python -m pytest -q tests/remediation/r11/test_deployment.py
