# Phase 4: Add Nginx for TLS and Routing

## Current State

- Prod uses ALB for TLS termination, health checks, and path routing
- Local dev hits Daphne directly on port 8000 (no TLS)
- Guacamole needs to be reachable at `/guacamole` from the browser
- Django serves everything else

## Why Nginx

- TLS termination (Let's Encrypt or provided cert)
- Route `/guacamole` to guacamole-client, everything else to Django
- WebSocket upgrade support (Django Channels + Guacamole)
- Static file serving
- Standard, well-understood, minimal config

## Changes

### 1. Create nginx config

**File:** `shifter/shifter_platform/nginx/nginx.conf`

```nginx
upstream django {
    server web:8000;
}

upstream guacamole {
    server guacamole:8080;
}

server {
    listen 80;
    server_name _;

    # Redirect to HTTPS (if TLS enabled)
    # return 301 https://$host$request_uri;

    # Or serve directly on 80 for environments without TLS
    include /etc/nginx/conf.d/locations.conf;
}

server {
    listen 443 ssl;
    server_name _;

    ssl_certificate /etc/nginx/ssl/cert.pem;
    ssl_certificate_key /etc/nginx/ssl/key.pem;
    ssl_protocols TLSv1.2 TLSv1.3;

    include /etc/nginx/conf.d/locations.conf;
}
```

**File:** `shifter/shifter_platform/nginx/locations.conf`

```nginx
# Health check
location /health {
    proxy_pass http://django;
}

# Guacamole
location /guacamole/ {
    proxy_pass http://guacamole:8080/guacamole/;
    proxy_buffering off;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $http_connection;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}

# Static files (collected by Django)
location /static/ {
    alias /app/staticfiles/;
    expires 30d;
}

# Django (everything else)
location / {
    proxy_pass http://django;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 86400;  # WebSocket connections
}
```

### 2. Add nginx service to docker-compose

```yaml
nginx:
  image: nginx:alpine
  ports:
    - "80:80"
    - "443:443"
  volumes:
    - ./nginx/nginx.conf:/etc/nginx/nginx.conf:ro
    - ./nginx/locations.conf:/etc/nginx/conf.d/locations.conf:ro
    - ./staticfiles:/app/staticfiles:ro
    - ${TLS_CERT_DIR:-./nginx/ssl}:/etc/nginx/ssl:ro
  depends_on:
    - web
    - guacamole
  restart: unless-stopped
```

### 3. TLS certificates

Three options depending on deployment context:

**a) Self-signed (dev/internal):**
```bash
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout ssl/key.pem -out ssl/cert.pem \
  -subj "/CN=shifter.local"
```

**b) Let's Encrypt (public domain):**
Add certbot sidecar or use acme.sh. Out of scope for initial deployment - can be a follow-up.

**c) Provided cert (corporate):**
Mount cert files via `TLS_CERT_DIR` env var.

### 4. Remove direct port exposure from web/guacamole

Only nginx exposes ports 80/443. Remove `ports` from `web` and `guacamole` services.

### 5. Update Django settings

`SECURE_PROXY_SSL_HEADER` is likely already set. Verify `CSRF_TRUSTED_ORIGINS` includes the deployment domain.

## Verification

- `curl -k https://localhost/health` returns 200
- `curl -k https://localhost/guacamole/` returns Guacamole page
- WebSocket connections work through nginx (terminal UI)
- Static files served by nginx (check response headers)
