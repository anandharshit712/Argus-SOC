# Deploying Argus SOC on the OCI instance

> **Superseded on Oct 17, 2026.** The live deployment runs on GCP: see `deploy/gcp_runbook.md`
> (HLD D14). Kept for reference. `docker-compose.oci.yml` and `deploy/nginx/oci/` are still the
> cloud-VM HTTPS override, used unchanged on GCP.

Owner: Workstream B (Md Adnan Afzal). One Ubuntu VM on OCI, one Docker Compose project.
Only nginx is reachable from the internet (ports 80 and 443); FalkorDB, Talos, its
PostgreSQL, the API and the agents stay on the private `soc-net` network.

## 1. Once per instance

1. **Open the ports.** In the OCI console, the instance's subnet security list (or NSG)
   needs ingress TCP 80 and 443 from `0.0.0.0/0`, plus 22 for SSH. On the VM itself
   (Ubuntu images block everything but SSH with iptables):
   ```bash
   sudo iptables -I INPUT 6 -p tcp --dport 80 -j ACCEPT
   sudo iptables -I INPUT 6 -p tcp --dport 443 -j ACCEPT
   sudo netfilter-persistent save
   ```
2. **DNS.** Point an A record for the demo host name (for example `argus.example.org`) at
   the instance's public IP.
3. **Docker.** Install Docker Engine and the Compose plugin (docs.docker.com/engine/install/ubuntu),
   then `sudo usermod -aG docker $USER` and log in again.
4. **Certificate** (before nginx runs, so port 80 is free):
   ```bash
   sudo apt-get install -y certbot
   sudo certbot certonly --standalone -d argus.example.org
   sudo mkdir -p /var/www/certbot
   ```
   Renewal later uses the running nginx:
   `sudo certbot renew --webroot -w /var/www/certbot --deploy-hook "docker compose -f ~/Argus-SOC/docker-compose.yml -f ~/Argus-SOC/docker-compose.oci.yml exec nginx nginx -s reload"`.

## 2. Each deploy

```bash
git clone https://github.com/anandharshit712/Argus-SOC.git && cd Argus-SOC   # first time
git pull                                                                    # later
cp .env.example .env        # first time; then edit:
#   TALOS_DB_PASSWORD=<long random value>
#   ARGUS_DOMAIN=argus.example.org
#   LLM_* if the LLM is used; demo users / session secret once GAP-1 lands
docker compose -f docker-compose.yml -f docker-compose.oci.yml --profile app up -d --build
```

## 3. Check it

```bash
docker compose ps                      # falkordb, talos-postgres, talos, api, ui: (healthy); seed: exited (0)
docker compose logs seed               # "seeded {'hosts': 64, ...}" for acme and globex
curl -s https://argus.example.org/api/health
docker compose --profile app up -d --scale agents=2   # second worker for the concurrency demo
```

## 4. Reset for the judges

```bash
docker compose run --rm seed python scripts/reset_demo.py --yes
```

Memory survives `docker compose restart` and `down`/`up` (volume `falkordb-data`); only
`reset_demo.py` or `docker compose down -v` wipes it.
