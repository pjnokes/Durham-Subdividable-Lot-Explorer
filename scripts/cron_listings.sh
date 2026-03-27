#!/bin/sh
# Daily Redfin listing refresh. Runs once at startup, then every 24 hours.
set -e

echo "[listings-cron] Starting daily Redfin listing refresh service"
echo "[listings-cron] Database: configured via \$DATABASE_URL"

while true; do
    echo ""
    echo "[listings-cron] $(date -Iseconds) — Running fetch_listings..."
    python -u /app/backend/ingestion/fetch_listings.py || echo "[listings-cron] ERROR: fetch failed (exit $?)"
    echo "[listings-cron] Next run in 24 hours."
    sleep 86400
done
