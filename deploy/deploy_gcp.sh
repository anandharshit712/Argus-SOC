#!/usr/bin/env bash
# One command to provision a fresh GCP Ubuntu VM and start the whole Argus SOC stack.
#
# It automates deploy/gcp_runbook.md: host prep (swap, Docker, packages), clone/pull into
# /opt/Argus-SOC, team access, the TLS certificate, the `dc` compose wrapper, build and start,
# then a health check. Idempotent -- safe to re-run, so it is also the update path (git pull + up).
#
#   curl -fsSL https://raw.githubusercontent.com/anandharshit712/Argus-SOC/main/deploy/deploy_gcp.sh | sudo bash
#   # or, from a clone:  sudo deploy/deploy_gcp.sh
#
# First run: it clones, writes a .env skeleton, and stops so you can fill the secrets. Fill them,
# then run it again to build and start.
#
# Knobs (environment variables, all optional):
#   PROJECT_DIR     where the repo lives           (default /opt/Argus-SOC)
#   REPO_URL        git remote to clone            (default the public GitHub repo)
#   BRANCH          branch to deploy               (default main)
#   TEAM_USERS      space-separated Linux users to add to the argus group (default: none)
#   SKIP_HOST_PREP  =1 to skip swap/Docker/package install (already provisioned)
#   SKIP_CERT       =1 to skip certbot (certificate already exists, or HTTP-only)
#   CERT_EMAIL      email for Let's Encrypt        (required for the certificate step)
# ARGUS_DOMAIN / SHOP_DOMAIN come from .env. Set both for the public HTTPS stack; leave them empty
# for a local HTTP-only bring-up on 127.0.0.1:8088 (no nginx front, no certificate).
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-/opt/Argus-SOC}"
REPO_URL="${REPO_URL:-https://github.com/anandharshit712/Argus-SOC.git}"
BRANCH="${BRANCH:-main}"
ARGUS_GROUP=argus

log()  { printf '\n\033[1;32m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m[warn] %s\033[0m\n'  "$*" >&2; }
die()  { printf '\033[1;31m[error] %s\033[0m\n' "$*" >&2; exit 1; }

[ "$(id -u)" = "0" ] || die "run as root (sudo $0)"

# --- 1. Host prep -------------------------------------------------------------------------------
if [ "${SKIP_HOST_PREP:-0}" != "1" ]; then
  log "Host prep: swap, Docker, packages"
  if ! swapon --show | grep -q /swapfile; then
    fallocate -l 4G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
    grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
  fi
  if ! command -v docker >/dev/null 2>&1; then
    curl -fsSL https://get.docker.com | sh
  fi
  apt-get update -qq
  apt-get install -y -qq git dnsutils certbot acl >/dev/null
else
  log "Host prep skipped (SKIP_HOST_PREP=1)"
fi

# --- 2. Clone or update -------------------------------------------------------------------------
if [ -d "$PROJECT_DIR/.git" ]; then
  log "Updating $PROJECT_DIR ($BRANCH)"
  git config --system --add safe.directory "$PROJECT_DIR" 2>/dev/null || true
  git -C "$PROJECT_DIR" fetch --quiet origin "$BRANCH"
  git -C "$PROJECT_DIR" checkout --quiet "$BRANCH"
  git -C "$PROJECT_DIR" pull --quiet --ff-only origin "$BRANCH"
else
  log "Cloning $REPO_URL -> $PROJECT_DIR"
  git clone --branch "$BRANCH" "$REPO_URL" "$PROJECT_DIR"
fi
cd "$PROJECT_DIR"

# --- 3. .env ------------------------------------------------------------------------------------
if [ ! -f .env ]; then
  log "First run: writing .env skeleton -- fill in the secrets, then re-run this script"
  cp .env.example .env
  # auth vars (GAP-1) live in backend/.env.example; append any the main example lacks
  if [ -f backend/.env.example ]; then
    for key in ARGUS_DEMO_USERS ARGUS_SESSION_SECRET ARGUS_SESSION_HOURS; do
      grep -q "^${key}=" .env || grep -E "^${key}=" backend/.env.example >> .env || true
    done
  fi
  chmod 660 .env
  cat <<EOF

  .env created at $PROJECT_DIR/.env. Set at least:
    TALOS_DB_PASSWORD        (random)
    DEMO_POOL_PASSWORD       (random; required for attack-bot 'pass' runs)
    DEMO_SSH_POOL_PASSWORD   (random; required for SSH 'pass' runs)
    ARGUS_DOMAIN, SHOP_DOMAIN (public HTTPS; leave empty for local HTTP only)
    ARGUS_SESSION_SECRET, ARGUS_DEMO_USERS (UI login)
    LLM_* if you want LLM explanations (decisions never need it)
  Then re-run: sudo $0
EOF
  exit 0
fi

# Required-before-start checks (fail loud, never start half-configured).
# shellcheck disable=SC1091
set -a; . ./.env; set +a
[ -n "${TALOS_DB_PASSWORD:-}" ] || die "TALOS_DB_PASSWORD is empty in .env (set it before the first start)"
[ -n "${DEMO_POOL_PASSWORD:-}" ]     || warn "DEMO_POOL_PASSWORD empty: web/cred-stuffing 'pass' runs will be skipped"
[ -n "${DEMO_SSH_POOL_PASSWORD:-}" ] || warn "DEMO_SSH_POOL_PASSWORD empty: SSH 'pass' runs will be skipped"

PUBLIC=0
[ -n "${ARGUS_DOMAIN:-}" ] && [ -n "${SHOP_DOMAIN:-}" ] && PUBLIC=1

# --- 4. Team access (shared folder) -------------------------------------------------------------
log "Team access: group '$ARGUS_GROUP' owns $PROJECT_DIR"
groupadd -f "$ARGUS_GROUP"
for u in ${TEAM_USERS:-}; do
  id "$u" >/dev/null 2>&1 && usermod -aG "$ARGUS_GROUP" "$u" || warn "user '$u' not found, skipped"
done
chgrp -R "$ARGUS_GROUP" "$PROJECT_DIR"
chmod -R g+rwX "$PROJECT_DIR"
find "$PROJECT_DIR" -type d -exec chmod g+s {} +
setfacl -R -m g:"$ARGUS_GROUP":rwX -m d:g:"$ARGUS_GROUP":rwX "$PROJECT_DIR" 2>/dev/null || true
git config --system --add safe.directory "$PROJECT_DIR" 2>/dev/null || true
git config core.sharedRepository group

# --- 5. Certificate -----------------------------------------------------------------------------
COMPOSE_FILES="-f docker-compose.yml -f demo/docker-compose.demo.yml"
PROFILES="--profile app --profile demo"
if [ "$PUBLIC" = "1" ]; then
  COMPOSE_FILES="$COMPOSE_FILES -f docker-compose.oci.yml -f docker-compose.public-shop.yml"
  if [ "${SKIP_CERT:-0}" != "1" ] && [ ! -d "/etc/letsencrypt/live/$ARGUS_DOMAIN" ]; then
    [ -n "${CERT_EMAIL:-}" ] || die "CERT_EMAIL is required for the certificate (or set SKIP_CERT=1)"
    log "Requesting certificate for $ARGUS_DOMAIN + $SHOP_DOMAIN"
    certbot certonly --standalone -n --agree-tos -m "$CERT_EMAIL" \
      -d "$ARGUS_DOMAIN" -d "$SHOP_DOMAIN"
    mkdir -p /var/www/certbot
  else
    log "Certificate step skipped (present or SKIP_CERT=1)"
  fi
else
  warn "ARGUS_DOMAIN/SHOP_DOMAIN unset: local HTTP-only bring-up (http://127.0.0.1:8088), no TLS"
fi

# --- 6. The `dc` wrapper (one command for every compose file + profile) -------------------------
log "Installing /usr/local/bin/dc wrapper"
printf '#!/bin/sh\ncd %s && exec sudo docker compose %s %s "$@"\n' \
  "$PROJECT_DIR" "$COMPOSE_FILES" "$PROFILES" > /usr/local/bin/dc
chmod +x /usr/local/bin/dc

# --- 7. Build and start -------------------------------------------------------------------------
log "Building images"
# shellcheck disable=SC2086
docker compose $COMPOSE_FILES $PROFILES build
log "Starting the stack (agents scaled to 2 for the concurrency story)"
# shellcheck disable=SC2086
docker compose $COMPOSE_FILES $PROFILES up -d --scale agents=2

# --- 8. Health check ----------------------------------------------------------------------------
log "Waiting for the API to answer"
if [ "$PUBLIC" = "1" ]; then HEALTH="https://$ARGUS_DOMAIN/api/health"; else HEALTH="http://127.0.0.1:8088/api/health"; fi
for _ in $(seq 1 30); do
  if curl -fsS "$HEALTH" >/dev/null 2>&1; then
    log "Up. API healthy at $HEALTH"
    curl -fsS "$HEALTH"; echo
    # shellcheck disable=SC2086
    docker compose $COMPOSE_FILES $PROFILES ps
    exit 0
  fi
  sleep 3
done
warn "API did not answer at $HEALTH within 90s. Check: dc ps  /  dc logs api"
exit 1
