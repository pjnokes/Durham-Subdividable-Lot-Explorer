#!/bin/sh
# Monthly data refresh: parcels, zoning, utilities.
# Runs once at startup, then sleeps until the 1st of next month.
# After data refresh, re-runs the subdivision analysis batch.
set -e

echo "[data-cron] Starting monthly data refresh service"
echo "[data-cron] Database: configured via \$DATABASE_URL"

seconds_until_first() {
    now=$(date +%s)
    # 1st of next month at 03:00 UTC
    if [ "$(date +%d)" = "01" ] && [ "$(date +%H)" -lt 3 ]; then
        target=$(date -d "$(date +%Y-%m-01) 03:00:00" +%s 2>/dev/null || date +%s)
    else
        target=$(date -d "$(date -d 'next month' +%Y-%m-01) 03:00:00" +%s 2>/dev/null || echo 0)
    fi
    if [ "$target" = "0" ] || [ "$target" -le "$now" ]; then
        echo 2592000  # fallback: 30 days
    else
        echo $(( target - now ))
    fi
}

run_refresh() {
    echo ""
    echo "[data-cron] $(date -Iseconds) — Starting monthly data refresh"

    echo "[data-cron] Refreshing parcels..."
    python -u -m backend.ingestion.fetch_parcels || echo "[data-cron] WARNING: parcels fetch failed (exit $?)"

    echo "[data-cron] Refreshing zoning districts..."
    python -u -m backend.ingestion.fetch_zoning || echo "[data-cron] WARNING: zoning fetch failed (exit $?)"

    echo "[data-cron] Refreshing utility layers..."
    python -u -m backend.ingestion.fetch_utilities || echo "[data-cron] WARNING: utilities fetch failed (exit $?)"

    echo "[data-cron] Refreshing synthetic footprints..."
    python -u -m backend.ingestion.generate_synthetic_footprints || echo "[data-cron] WARNING: synthetic footprints failed (exit $?)"

    echo "[data-cron] Re-running subdivision analysis..."
    python -u scripts/run_analysis.py || echo "[data-cron] WARNING: analysis batch failed (exit $?)"

    echo "[data-cron] $(date -Iseconds) — Monthly refresh complete"
}

# Run once at startup
run_refresh

while true; do
    wait_secs=$(seconds_until_first)
    echo "[data-cron] Next refresh in ~$(( wait_secs / 86400 )) days (sleeping ${wait_secs}s)"
    sleep "$wait_secs"
    run_refresh
done
