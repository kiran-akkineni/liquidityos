#!/usr/bin/env bash
# Start both Flask API (port 8000) and Vite dev server (port 3000)
set -e

DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "=== LiquidityOS Dev Environment ==="
echo ""

# Seed database if it doesn't exist
if [ ! -f "$DIR/liquidityos.db" ]; then
  echo "Seeding database..."
  python3 "$DIR/scripts/seed.py"
  echo ""
fi

echo "Starting Flask API on http://localhost:8000..."
python3 "$DIR/app/main.py" &
FLASK_PID=$!

echo "Starting Vite dev server on http://localhost:3000..."
cd "$DIR/frontend" && npm run dev &
VITE_PID=$!

echo ""
echo "  API:       http://localhost:8000/v1"
echo "  Dashboard: http://localhost:3000"
echo ""
echo "Press Ctrl+C to stop both servers."

trap "kill $FLASK_PID $VITE_PID 2>/dev/null; exit" INT TERM
wait
