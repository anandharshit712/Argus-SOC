# Deploying Argus SOC on Google Cloud (GCP)

Owner: Workstream B. The live demo runs on one GCP Compute Engine VM as one Docker Compose
project: Argus SOC, Talos, the live demo harness and both databases. Live since Oct 17, 2026.
This replaces the OCI plan (`deploy/oci_runbook.md`): OCI's free Ampere A1 shape had no capacity
in Hyderabad after ~40 minutes of retries, and the account limit was 2 OCPU / 12 GB (HLD D14).

The file names `docker-compose.oci.yml` and `deploy/nginx/oci/` are historical: they are the
cloud-VM HTTPS override and work unchanged on GCP.

## The live instance

| Item | Value |
| --- | --- |
| Project | My First Project (free trial: ₹28,796.63 credit, until Jan 16, 2027) |
| VM | `argus-soc`, zone `asia-south1-c` (Mumbai) |
| Machine | e2-standard-4: 4 vCPU, 16 GB, x86 |
| OS / disk | Ubuntu 24.04 LTS (x86/64), 50 GB balanced persistent disk, no snapshot schedule, no Ops Agent |
| Public IP | `34.93.139.203`, reserved as static (`argus-soc-ip`) |
| Firewall | Default VPC rules: SSH 22, HTTP 80, HTTPS 443 (tick "Allow HTTP/HTTPS traffic") |
| Argus UI + API | `https://argus-soc.34-93-139-203.sslip.io` |
| Demo web shop | `https://shop.34-93-139-203.sslip.io` |
| Private only | attack-bot (127.0.0.1:8090), FalkorDB Browser (127.0.0.1:3000), Talos, Postgres, SSH target |
| Cost | ~$123.51/month VM + disk (console estimate) ≈ $30 per 7 days, plus ~$0.84/week for the IP |

The host names are free **sslip.io** names (any name containing the IP resolves to it), because
the team owns no domain. To move to DuckDNS later: register two names, point them at the IP, run
certbot for them, change `ARGUS_DOMAIN` / `SHOP_DOMAIN` in `.env`, `dc up -d nginx`.

## 1. Create the VM (console)

1. Enable the **Compute Engine API** for the project.
2. **Compute Engine › VM instances › Create instance**: name `argus-soc`, region `asia-south1`,
   series E2, machine type **e2-standard-4**.
3. **OS and storage › Change**: Ubuntu, **Ubuntu 24.04 LTS (x86/64)**, balanced disk, **50 GB**.
4. **Data protection**: **No backups** (the default daily snapshots cost extra).
5. **Networking**: tick **Allow HTTP traffic** and **Allow HTTPS traffic**.
6. **Observability**: untick the Ops Agent (variable logging cost; the app logs on its own).
7. Create. Then **VPC network › IP addresses** › the VM's external IP › **Promote to static**.

## 2. Prepare the VM

SSH in with the console's **SSH** button, or Cloud Shell:
`gcloud compute ssh argus-soc --zone asia-south1-c`.

```bash
sudo fallocate -l 4G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
curl -fsSL https://get.docker.com | sudo sh
sudo apt-get install -y git dnsutils certbot
```

GCP's Ubuntu image does not block ports 80/443 in the OS firewall, so no iptables step.

## 3. Clone and fill in `.env`

```bash
git clone https://github.com/anandharshit712/Argus-SOC.git ~/Argus-SOC && cd ~/Argus-SOC
cp .env.example .env
grep -E '^ARGUS_SESSION_HOURS=' backend/.env.example >> .env   # ARGUS_DEMO_USERS / ARGUS_SESSION_SECRET too
chmod 600 .env
```

Set: `TALOS_DB_PASSWORD` (random, before the first start), `ARGUS_DOMAIN`, `SHOP_DOMAIN`,
`ARGUS_SESSION_SECRET` (random, 32+ chars), `ARGUS_DEMO_USERS` (one-line JSON, real passwords),
and for LLM mode `LLM_ENABLED=true`, `LLM_API_KEY`, `LLM_PROVIDER=openai` (exact spelling) and
`LLM_MODEL` (required for OpenAI; the live demo uses `gpt-5.5`), `LLM_TIMEOUT_SECONDS=30`.
Keep `DEMO_SOAK=0` unless you want the always-on random attack loop.

## 4. Certificate (before nginx starts)

```bash
sudo certbot certonly --standalone -n --agree-tos -m <email> \
  -d argus-soc.34-93-139-203.sslip.io -d shop.34-93-139-203.sslip.io
sudo mkdir -p /var/www/certbot
```

One certificate covers both names. Renewal must use webroot once nginx holds port 80: in
`/etc/letsencrypt/renewal/<ARGUS_DOMAIN>.conf` set `authenticator = webroot`,
`webroot_path = /var/www/certbot,` and `renew_hook = /usr/local/bin/dc exec -T nginx nginx -s reload`,
and add a `[[webroot_map]]` section with both names mapped to `/var/www/certbot`.

## 5. Build and start

A small wrapper keeps the four compose files and both profiles in one command:

```bash
printf '#!/bin/sh\ncd %s/Argus-SOC && exec sudo docker compose -f docker-compose.yml -f docker-compose.oci.yml -f demo/docker-compose.demo.yml -f docker-compose.public-shop.yml --profile app --profile demo "$@"\n' $HOME \
  | sudo tee /usr/local/bin/dc >/dev/null && sudo chmod +x /usr/local/bin/dc
dc build
dc up -d --scale agents=2
```

## 6. Check, demo, reset

```bash
dc ps                                                    # 13 containers; seed Exited (0)
curl -s https://argus-soc.34-93-139-203.sslip.io/api/health   # {"status":"ok","falkordb":true}
sudo ss -tlnp | grep -v 127.0.0                          # only 22, 80, 443
dc exec -T agents python -c "from argus_soc.agents.llm_client import provider, model_name; print(provider(), model_name())"

curl -X POST "localhost:8090/launch?attack=sqli"         # web_brute | cred_stuffing | sqli | xss | ssh_brute
curl localhost:8090/selfcheck                            # what Talos caught
dc run --rm seed python scripts/reset_demo.py --yes      # wipe and reseed before judging
git pull && dc up -d --build --scale agents=2            # ship a change
```

After an `.env` change, `dc up -d --scale agents=2` recreates the services that read it.

## Cost control

Stop the VM after judging (**VM instances › Stop**): only the disk (~$0.20/day) and the reserved
IP keep costing. A free-trial account is never billed to the card unless it is upgraded.

The first live end-to-end test on this VM (Oct 17) is summarised in `CHAT_LOG.md` turn 45; the full
report is kept locally in `local_reports/live_e2e_gcp_2026-10-17/` (git-excluded).
