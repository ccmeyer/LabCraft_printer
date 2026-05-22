#!/usr/bin/env bash
set -euo pipefail

printf 'WARNING: post_clone.sh is a legacy virtualenv helper. For Raspberry Pi 5 / Bookworm setup, follow README.md instead.\n'
printf 'This script creates .venv from requirements.txt, while the current Pi flow uses venv plus requirements-pi.lock.\n'

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

echo "=== Python venv ==="
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip

echo "=== Install requirements ==="
pip install -r requirements.txt

echo "=== Verify key tools ==="
which dfu-util || { echo "dfu-util missing"; exit 1; }
python -c "import PySide6, sys; print('PySide6', PySide6.__version__)"
python -c "import gpiod, sys; print('gpiod module OK')"

echo "=== Done. Run the app with: ==="
echo "source .venv/bin/activate && python FreeRTOS-interface/App.py"
