#!/usr/bin/env bash
# ------------------------------------------------------------------
# deploy.sh — Deploy from local machine to the Lightsail instance
#
# Prerequisites:
#   1. Server provisioned with deploy/setup-server.sh
#   2. SSH key configured (~/.ssh/lightsail-key or similar)
#   3. Local database running with all analyzed data
#
# Usage:
#   export SERVER_IP=<your-lightsail-ip>
#   export SSH_KEY=~/.ssh/lightsail-key        # optional, omit for default key
#   export DOMAIN=your.domain.com                    # for SSL
#   bash deploy/deploy.sh
# ------------------------------------------------------------------
set -euo pipefail

SERVER_IP="${SERVER_IP:?Set SERVER_IP to your Lightsail public IP}"
SSH_KEY="${SSH_KEY:-}"
REMOTE_USER="${REMOTE_USER:-ubuntu}"
APP_DIR="/opt/durham-lots"
DB_DUMP="durham_lots_dump.custom"
LOCAL_CONTAINER="${LOCAL_CONTAINER:-durham_subdividable_lots-db-1}"
DOMAIN="${DOMAIN:-}"
SSL_EMAIL="${SSL_EMAIL:-you@example.com}"

SSH_OPTS="-o StrictHostKeyChecking=no"
if [[ -n "$SSH_KEY" ]]; then
    SSH_OPTS="$SSH_OPTS -i $SSH_KEY"
fi

ssh_cmd() { ssh $SSH_OPTS "$REMOTE_USER@$SERVER_IP" "$@"; }
scp_cmd() { scp $SSH_OPTS "$@"; }

# ----- Step 1: Dump local database (custom/binary format) -----
echo "==> Step 1/7: Dumping local database..."
if [[ ! -f "$DB_DUMP" ]]; then
    echo "    Exporting from local Docker Postgres (custom format)..."
    docker exec "$LOCAL_CONTAINER" bash -c \
        "pg_dump -U durham -d durham_lots --no-owner --no-privileges -Fc > /tmp/dump.custom"
    docker cp "$LOCAL_CONTAINER:/tmp/dump.custom" "$DB_DUMP"
    docker exec "$LOCAL_CONTAINER" rm /tmp/dump.custom
    echo "    Dump size: $(du -h "$DB_DUMP" | cut -f1)"
else
    echo "    Using existing dump: $DB_DUMP ($(du -h "$DB_DUMP" | cut -f1))"
    echo "    Delete it to re-export."
fi

# ----- Step 2: Package project files -----
echo "==> Step 2/7: Packaging project files..."
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
echo "    Tarball size: $(du -h /tmp/durham-lots-deploy.tar.gz | cut -f1)"

# ----- Step 3: Upload to server -----
echo "==> Step 3/7: Uploading project files..."
scp_cmd /tmp/durham-lots-deploy.tar.gz "$REMOTE_USER@$SERVER_IP:$APP_DIR/deploy.tar.gz"
ssh_cmd "cd $APP_DIR && tar xzf deploy.tar.gz && rm deploy.tar.gz"

echo "    Uploading database dump..."
scp_cmd "$DB_DUMP" "$REMOTE_USER@$SERVER_IP:$APP_DIR/$DB_DUMP"

# ----- Step 4: Fix Windows line endings in shell scripts -----
echo "==> Step 4/7: Fixing line endings..."
ssh_cmd "cd $APP_DIR && find . -name '*.sh' -exec sed -i 's/\r$//' {} +"

# ----- Step 5: Create .env.prod on server (if missing) -----
echo "==> Step 5/7: Ensuring .env.prod exists on server..."
ssh_cmd "cd $APP_DIR && \
    if [ ! -f .env.prod ]; then \
        PASS=\$(openssl rand -base64 24 | tr -d '/+=') && \
        echo 'POSTGRES_DB=durham_lots' > .env.prod && \
        echo 'POSTGRES_USER=durham' >> .env.prod && \
        echo \"POSTGRES_PASSWORD=\$PASS\" >> .env.prod && \
        echo '    Created .env.prod with random password'; \
    else \
        echo '    .env.prod already exists, skipping'; \
    fi"

# ----- Step 6: Build, start, and restore database -----
echo "==> Step 6/7: Building and starting services..."

# If DOMAIN is set and SSL config exists, use it
if [[ -n "$DOMAIN" ]]; then
    echo "    SSL domain: $DOMAIN — using nginx.ssl.conf"
    ssh_cmd "sed 's/__DOMAIN__/$DOMAIN/g' $APP_DIR/deploy/nginx.ssl.conf > $APP_DIR/deploy/nginx.conf"
fi

ssh_cmd "cd $APP_DIR && \
    export \$(cat .env.prod | xargs) && \
    sg docker -c 'docker compose -f docker-compose.prod.yml --env-file .env.prod build' && \
    sg docker -c 'docker compose -f docker-compose.prod.yml --env-file .env.prod up -d' && \
    echo 'Waiting for database to be healthy...' && \
    sleep 10 && \
    echo 'Restoring database dump...' && \
    sg docker -c 'docker cp $APP_DIR/$DB_DUMP durham-lots-db-1:/tmp/dump.custom' && \
    sg docker -c 'docker compose -f docker-compose.prod.yml exec -T db pg_restore -U durham -d durham_lots --clean --if-exists --no-owner --no-privileges /tmp/dump.custom' && \
    sg docker -c 'docker compose -f docker-compose.prod.yml exec -T db rm /tmp/dump.custom' && \
    sg docker -c 'docker compose -f docker-compose.prod.yml restart backend' && \
    rm -f $APP_DIR/$DB_DUMP && \
    echo 'Database restored and cleaned up.'"

# ----- Step 7: SSL certificate (if DOMAIN is set) -----
if [[ -n "$DOMAIN" ]]; then
    echo "==> Step 7/7: Setting up SSL certificate..."
    ssh_cmd "if [ ! -d /etc/letsencrypt/live/$DOMAIN ]; then \
        echo '    Installing certbot...' && \
        sudo apt-get update -qq && sudo apt-get install -y -qq certbot 2>&1 | tail -1 && \
        echo '    Stopping nginx for cert issuance...' && \
        cd $APP_DIR && export \$(cat .env.prod | xargs) && \
        sg docker -c 'docker compose -f docker-compose.prod.yml stop frontend' && \
        echo '    Requesting certificate...' && \
        sudo certbot certonly --standalone -d $DOMAIN --non-interactive --agree-tos --email $SSL_EMAIL && \
        echo '    Restarting frontend with SSL...' && \
        sg docker -c 'docker compose -f docker-compose.prod.yml up -d frontend' && \
        echo '    Setting up auto-renewal cron...' && \
        sudo bash -c 'echo \"0 3 * * * root certbot renew --quiet --deploy-hook \\\"docker restart durham-lots-frontend-1\\\"\" > /etc/cron.d/certbot-renew' && \
        echo '    SSL configured!'; \
    else \
        echo '    Certificate already exists, skipping.'; \
        cd $APP_DIR && export \$(cat .env.prod | xargs) && \
        sg docker -c 'docker compose -f docker-compose.prod.yml up -d frontend'; \
    fi"

    echo ""
    echo "========================================"
    echo " Deployment complete!"
    echo " App:  https://$DOMAIN"
    echo " API:  https://$DOMAIN/api/analysis/stats"
    echo " Docs: https://$DOMAIN/docs"
    echo "========================================"
else
    echo "==> Step 7/7: Skipping SSL (no DOMAIN set)"
    echo ""
    echo "========================================"
    echo " Deployment complete!"
    echo " App:  http://$SERVER_IP"
    echo " API:  http://$SERVER_IP/api/analysis/stats"
    echo " Docs: http://$SERVER_IP/docs"
    echo ""
    echo " To add SSL, re-run with:"
    echo "   export DOMAIN=your.domain.com"
    echo "========================================"
fi
