#!/usr/bin/env bash
# ------------------------------------------------------------------
# teardown.sh — Stop and clean up everything on the server
#
# Usage:
#   export SERVER_IP=<your-lightsail-ip>
#   bash deploy/teardown.sh
# ------------------------------------------------------------------
set -euo pipefail

SERVER_IP="${SERVER_IP:?Set SERVER_IP to your Lightsail public IP}"
SSH_KEY="${SSH_KEY:-}"
REMOTE_USER="${REMOTE_USER:-ubuntu}"
APP_DIR="/opt/durham-lots"

SSH_OPTS="-o StrictHostKeyChecking=no"
if [[ -n "$SSH_KEY" ]]; then
    SSH_OPTS="$SSH_OPTS -i $SSH_KEY"
fi

echo "==> Stopping all services and removing volumes..."
ssh $SSH_OPTS "$REMOTE_USER@$SERVER_IP" \
    "cd $APP_DIR && \
     docker compose -f docker-compose.prod.yml --env-file .env.prod down -v && \
     docker system prune -af && \
     echo 'All containers, images, and volumes removed.'"

echo ""
echo "Server cleaned up. You can now delete the Lightsail instance from the AWS console."
echo "  https://lightsail.aws.amazon.com/ls/webapp/home/instances"
