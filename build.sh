#!/bin/bash
# Build script for Render.com deployment
# Installs Python packages + Playwright browser

set -e

echo "=== Installing Python dependencies ==="
pip install -r requirements.txt

echo "=== Installing Playwright Chromium browser ==="
python -m playwright install chromium

echo "=== Installing Playwright system dependencies ==="
python -m playwright install-deps chromium || echo "Warning: install-deps failed (may need root). Continuing..."

echo "=== Build complete ==="
