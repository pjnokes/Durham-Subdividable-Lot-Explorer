# Deployment Guide — Durham Subdividable Lots

One-week demo deployment on AWS Lightsail with HTTPS. Total cost: ~$5.

## Architecture (Production)

```
┌──────────────────────────────────────────────────────────┐
│  Lightsail Instance (4 GB RAM / 2 vCPU / $20/mo)        │
│                                                          │
│  ┌──────────┐    ┌──────────┐    ┌──────────────────┐    │
│  │  nginx    │───▶│ FastAPI  │───▶│  PostGIS 16-3.4  │    │
│  │  :80/:443 │    │  :8000   │    │  :5432           │    │
│  │ (SSL +    │    │ (2 uvicorn    │ (128k parcels +  │    │
│  │  static   │    │  workers)│    │  analysis data)  │    │
│  │  + proxy) │    └──────────┘    └──────────────────┘    │
│  └──────────┘                                            │
│  ┌──────────────┐                                        │
│  │ listings-cron│  (daily Redfin refresh)                 │
│  └──────────────┘                                        │
└──────────────────────────────────────────────────────────┘
```

## Prerequisites

- AWS account with Lightsail access
- Local database running with all analyzed parcel data
- Git Bash, WSL, or any bash shell (for deploy scripts on Windows)
- A domain with DNS pointed at the server (for HTTPS)

## Full Deploy from Scratch (~8 minutes)

### 1. Create Lightsail Instance + Static IP

```bash
# Create SSH key
aws --profile your-aws-profile lightsail create-key-pair \
    --key-pair-name durham-lots-key --region us-east-1 \
    --query 'privateKeyBase64' --output text > ~/.ssh/your-lightsail-key.pem
chmod 600 ~/.ssh/your-lightsail-key.pem

# Create instance (4 GB RAM, 2 vCPU, Ubuntu 24.04)
aws --profile your-aws-profile lightsail create-instances \
    --instance-names durham-lots \
    --availability-zone us-east-1a \
    --blueprint-id ubuntu_24_04 \
    --bundle-id medium_3_0 \
    --key-pair-name durham-lots-key \
    --region us-east-1

# Wait for it to be running
aws --profile your-aws-profile lightsail get-instance-state \
    --instance-name durham-lots --region us-east-1

# Allocate and attach static IP
aws --profile your-aws-profile lightsail allocate-static-ip \
    --static-ip-name durham-lots-ip --region us-east-1
aws --profile your-aws-profile lightsail attach-static-ip \
    --static-ip-name durham-lots-ip --instance-name durham-lots --region us-east-1

# Get the static IP
aws --profile your-aws-profile lightsail get-static-ip \
    --static-ip-name durham-lots-ip --region us-east-1 \
    --query 'staticIp.ipAddress' --output text

# Open firewall: SSH + HTTP + HTTPS
aws --profile your-aws-profile lightsail put-instance-public-ports \
    --instance-name durham-lots --region us-east-1 \
    --port-infos "fromPort=22,toPort=22,protocol=tcp" \
                 "fromPort=80,toPort=80,protocol=tcp" \
                 "fromPort=443,toPort=443,protocol=tcp"
```

### 2. Point DNS at the Static IP

In Cloudflare (or your DNS provider):
- **Type:** A
- **Name:** `trianglelots` (or your subdomain)
- **Content:** the static IP from step 1
- **Proxy:** OFF (grey cloud) — required for Let's Encrypt

### 3. Set Up Server + Deploy + SSL

```bash
export SERVER_IP=<static-ip-from-step-1>
export SSH_KEY=~/.ssh/your-lightsail-key.pem
export DOMAIN=your.domain.com

# One-time: install Docker on server (~2 min)
ssh -o StrictHostKeyChecking=no -i $SSH_KEY ubuntu@$SERVER_IP 'bash -s' < deploy/1_setup_server.sh

# Full deploy: DB dump, upload, build, restore, SSL (~6 min)
bash deploy/2_deploy_full.sh
```

The deploy script handles everything:
1. Dumps local database (binary custom format, ~157 MB)
2. Packages and uploads project files (~4.6 MB)
3. Uploads database dump
4. Fixes Windows line endings in shell scripts
5. Generates `.env.prod` with random password
6. Builds Docker images, starts services, restores database
7. Installs certbot, gets Let's Encrypt cert, sets up auto-renewal

### 4. Verify

- **App:** `https://your.domain.com`
- **API:** `https://your.domain.com/api/analysis/stats`

### 5. Run Smoke Tests

```bash
py -3.11 -m pytest tests/test_deploy_smoke.py -v --prod
```

This runs 21 checks: site loads, all API endpoints respond, data integrity (no government owners in subdividable results), and response times are acceptable. See `PRODUCTION.md` for the full test coverage table.

## Re-deploying Code Changes (No DB)

For quick code-only redeploys (skips DB dump/restore):

```bash
export SERVER_IP=<your-static-ip>
export SSH_KEY=~/.ssh/your-lightsail-key.pem
export DOMAIN=your.domain.com

# This will re-use existing DB dump if present, skip SSL if cert exists
bash deploy/2_deploy_full.sh
```

To force a fresh database export:
```bash
rm durham_lots_dump.custom
bash deploy/2_deploy_full.sh
```

## Pushing Code Changes (No DB)

```bash
export SERVER_IP=<your-static-ip>
export SSH_KEY=~/.ssh/your-lightsail-key.pem

bash deploy/3_deploy_update.sh                # rebuild all (~60s)
bash deploy/3_deploy_update.sh backend        # backend only (~30s)
bash deploy/3_deploy_update.sh frontend       # frontend only (~60s)
```

## Tearing Down

```bash
export SERVER_IP=<your-static-ip>
export SSH_KEY=~/.ssh/your-lightsail-key.pem

# Stop containers and clean up Docker
bash deploy/4_teardown.sh

# Delete AWS resources
aws --profile your-aws-profile lightsail detach-static-ip --static-ip-name durham-lots-ip --region us-east-1
aws --profile your-aws-profile lightsail release-static-ip --static-ip-name durham-lots-ip --region us-east-1
aws --profile your-aws-profile lightsail delete-instance --instance-name durham-lots --region us-east-1
aws --profile your-aws-profile lightsail delete-key-pair --key-pair-name durham-lots-key --region us-east-1

# Remove Cloudflare DNS record for your.domain.com
```

## Monitoring & Troubleshooting

```bash
ssh -i ~/.ssh/your-lightsail-key.pem ubuntu@<your-static-ip>
cd /opt/durham-lots

# All containers
docker compose -f docker-compose.prod.yml ps

# Logs
docker compose -f docker-compose.prod.yml logs -f
docker compose -f docker-compose.prod.yml logs -f backend

# Restart a service
docker compose -f docker-compose.prod.yml restart backend

# Database size
docker compose -f docker-compose.prod.yml exec db \
    psql -U durham -d durham_lots -c "SELECT pg_size_pretty(pg_database_size('durham_lots'));"

# SSL cert expiry
sudo certbot certificates
```

## Cost

| Resource | Cost | Notes |
|----------|------|-------|
| Lightsail 4 GB | $20/month (~$5/week) | Prorated daily billing |
| Static IP (attached) | Free | Free while attached to a running instance |
| Data transfer | Free | First 4 TB included |
| SSL | Free | Let's Encrypt, auto-renews |
| **Total for 1 week** | **~$5** | Delete instance to stop billing |

## File Reference

| File | Purpose |
|------|---------|
| `docker-compose.prod.yml` | Production service definitions (DB, API, nginx, cron) |
| `Dockerfile.backend` | FastAPI API server image |
| `Dockerfile.frontend` | Vite build → nginx static server |
| `deploy/nginx.conf` | nginx config (HTTP-only, used during initial deploy) |
| `deploy/nginx.ssl.conf` | nginx config with HTTPS + HTTP→HTTPS redirect |
| `deploy/1_setup_server.sh` | One-time server provisioning (Docker install) |
| `deploy/2_deploy_full.sh` | Full deploy: sync, build, DB restore, SSL |
| `deploy/3_deploy_update.sh` | Code-only update: sync, rebuild, restart (~30-60s) |
| `deploy/4_teardown.sh` | Stop services, clean up Docker |
| `.env.prod.example` | Template for production environment variables |
| `PRODUCTION.md` | Live deployment details (URL, IP, SSH access) |
