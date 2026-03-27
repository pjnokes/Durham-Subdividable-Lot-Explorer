#!/usr/bin/env bash
# ------------------------------------------------------------------
# update.sh — Push code changes to production (no DB re-import)
#
# Usage:
#   export SERVER_IP=<your-lightsail-ip>
#   export SSH_KEY=~/.ssh/your-lightsail-key.pem
#   bash deploy/update.sh                    # rebuild all
#   bash deploy/update.sh backend            # rebuild backend only
#   bash deploy/update.sh frontend           # rebuild frontend only
# ------------------------------------------------------------------
set -euo pipefail

SERVER_IP="${SERVER_IP:?Set SERVER_IP to your Lightsail public IP}"
SSH_KEY="${SSH_KEY:-}"
REMOTE_USER="${REMOTE_USER:-ubuntu}"
APP_DIR="/opt/durham-lots"
DOMAIN="${DOMAIN:-}"
SERVICE="${1:-}"

SSH_OPTS="-o StrictHostKeyChecking=no"
if [[ -n "$SSH_KEY" ]]; then
    SSH_OPTS="$SSH_OPTS -i $SSH_KEY"
fi

ssh_cmd() { ssh $SSH_OPTS "$REMOTE_USER@$SERVER_IP" "$@"; }

echo "==> Packaging project files..."
tar czf /tmp/durham-lots-deploy.tar.gz \
    --exclude='.git' \
    --exclude='node_modules' \
    --exclude='.venv' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='durham_lots_dump.*' \
    --exclude='.env' \
    --exclude='.env.prod' \
    --exclude='data' \
    --exclude='.cursor' \
    .

echo "==> Uploading to server..."
scp $SSH_OPTS /tmp/durham-lots-deploy.tar.gz "$REMOTE_USER@$SERVER_IP:$APP_DIR/deploy.tar.gz"
ssh_cmd "cd $APP_DIR && tar xzf deploy.tar.gz && rm deploy.tar.gz"

echo "==> Fixing line endings..."
ssh_cmd "cd $APP_DIR && find . -name '*.sh' -exec sed -i 's/\r$//' {} +"

if [[ -n "$DOMAIN" ]]; then
    echo "==> Stamping domain into nginx SSL config..."
    ssh_cmd "sed 's/__DOMAIN__/$DOMAIN/g' $APP_DIR/deploy/nginx.ssl.conf > $APP_DIR/deploy/nginx.conf"
fi

if [[ -n "$SERVICE" ]]; then
    echo "==> Rebuilding $SERVICE..."
    ssh_cmd "cd $APP_DIR && export \$(cat .env.prod | xargs) && \
        sg docker -c 'docker compose -f docker-compose.prod.yml --env-file .env.prod build $SERVICE && \
        docker compose -f docker-compose.prod.yml --env-file .env.prod up -d $SERVICE'"
else
    echo "==> Rebuilding all services..."
    ssh_cmd "cd $APP_DIR && export \$(cat .env.prod | xargs) && \
        sg docker -c 'docker compose -f docker-compose.prod.yml --env-file .env.prod build && \
        docker compose -f docker-compose.prod.yml --env-file .env.prod up -d'"
fi

echo ""
echo "========================================"
echo " Update complete!"
echo "========================================"
