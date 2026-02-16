#!/usr/bin/env bash
set -euo pipefail

echo "── Hardware Builder Setup ──"

# Python deps
echo "[1/4] Installing Python dependencies..."
pip install -r requirements.txt

# Frontend
if command -v node &>/dev/null; then
    echo "[2/4] Building frontend..."
    cd frontend && npm install && npm run build && cd ..
else
    echo "[2/4] SKIP: Node.js not found (frontend build optional)"
fi

# Database
if [ ! -f parts.db ]; then
    echo "[3/4] No parts.db found. Run 'make scrape' to build the parts database."
    echo "       (Scrapes ~14,758 products from robu.in via Wayback Machine)"
else
    echo "[3/4] parts.db exists ($(sqlite3 parts.db 'SELECT COUNT(*) FROM parts') parts)"
fi

# API key check
if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
    echo "[4/4] WARNING: ANTHROPIC_API_KEY not set. Export it before running builds."
else
    echo "[4/4] Anthropic API key detected ✓"
fi

echo ""
echo "── Ready ──"
echo "  make serve        → Start web UI + API on :8000"
echo "  make run PROMPT='autonomous drone'  → CLI build"
echo "  make scrape       → Build parts database"
