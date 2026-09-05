# Production Deploy (Nginx + HTTPS)

This stack runs:
- `web` (Django via Gunicorn)
- `nginx` (public reverse proxy on 80/443)
- `db`, `qdrant`
- `vllm` locally, **or** a remote RunPod Serverless OpenAI URL (`VLLM_URL` + `RUNPOD_API_KEY`)

## 1) Server prerequisites

- Install Docker Engine + Docker Compose plugin.
- Open firewall ports:
  - `80/tcp`
  - `443/tcp`
- DNS:
  - Point `A` record for your domain to server public IP.

## 2) Configure environment

From the project `app/` folder:

```bash
cp .env.production.example .env
```

Edit `.env`:
- `SERVER_NAME` = your real domain (example `api.example.com`)
- `DJANGO_SECRET_KEY` = long random string (generate command below)
- `DJANGO_ALLOWED_HOSTS` = same domain (comma-separated if multiple)
- `DJANGO_CSRF_TRUSTED_ORIGINS` = `https://<domain>`
- `DJANGO_CORS_ALLOWED_ORIGINS` = frontend URL(s), comma-separated
- `POSTGRES_PASSWORD` = strong DB password
- `HUGGING_FACE_HUB_TOKEN` = your private HF token
- `ADMIN_INGESTION_MOUNT_PATH` = host path where ingestion PDFs should persist

Generate a Django secret key on server:

```bash
python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(64))
PY
```

## 3) Issue Let's Encrypt certificate (host-level)

Stop anything currently binding port 80:

```bash
sudo lsof -i :80
```

Install Certbot on host (Ubuntu example):

```bash
sudo apt update
sudo apt install -y certbot
```

Request certificate:

```bash
sudo certbot certonly --standalone -d your.domain.com --agree-tos -m you@example.com --non-interactive
```

This writes certs to:
- `/etc/letsencrypt/live/your.domain.com/fullchain.pem`
- `/etc/letsencrypt/live/your.domain.com/privkey.pem`

## 4) Start the stack

From `app/`:

```bash
docker compose --env-file .env pull
docker compose --env-file .env build web
docker compose --env-file .env up -d
```

## 5) Validate

```bash
docker compose ps
curl -I https://your.domain.com
```

## 6) Certificate renewals

Use host cron/systemd timer for Certbot renewals:

```bash
sudo certbot renew
```

After successful renewal, reload Nginx container:

```bash
docker compose exec nginx nginx -s reload
```

Tip: automate by adding deploy hook in host certbot renewal config to run Nginx reload command.

Example deploy hook:

```bash
sudo certbot renew --deploy-hook "cd /path/to/project/app && docker compose exec nginx nginx -s reload"
```
