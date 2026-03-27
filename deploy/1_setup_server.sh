#!/usr/bin/env bash
# ------------------------------------------------------------------
# setup-server.sh — Run on a fresh Ubuntu 22.04/24.04 Lightsail instance
#
# Usage:  ssh ubuntu@<IP> 'bash -s' < deploy/setup-server.sh
# ------------------------------------------------------------------
set -euo pipefail

echo "==> Installing Docker..."
sudo apt-get update -qq
sudo apt-get install -y -qq ca-certificates curl gnupg

sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update -qq
sudo apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin

sudo usermod -aG docker ubuntu
echo "==> Docker installed. Version: $(docker --version)"

echo "==> Creating app directory..."
sudo mkdir -p /opt/durham-lots
sudo chown ubuntu:ubuntu /opt/durham-lots

echo "==> Server setup complete."
echo "    Log out and back in (or run 'newgrp docker') for group changes."
echo "    Next: run deploy/deploy.sh from your local machine."
