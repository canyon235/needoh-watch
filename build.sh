#!/bin/bash
# Build script for Render.com deployment
# Installs Python packages + Playwright browser + system deps

set -e

echo "=== Installing Python dependencies ==="
pip install -r requirements.txt

echo "=== Installing Playwright Chromium ==="
python -m playwright install chromium

echo "=== Installing system dependencies for Chromium ==="
# Try apt-get first (works on Render's build environment which has root)
if command -v apt-get &> /dev/null; then
    apt-get update -qq && apt-get install -y -qq \
        libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
        libcups2 libdrm2 libxkbcommon0 libxcomposite1 \
        libxdamage1 libxrandr2 libgbm1 libpango-1.0-0 \
        libcairo2 libasound2 libxfixes3 2>/dev/null || echo "Some apt packages unavailable, continuing..."
fi

# Also try playwright install-deps as fallback
python -m playwright install-deps chromium 2>/dev/null || echo "playwright install-deps skipped"

echo "=== Build complete ==="
