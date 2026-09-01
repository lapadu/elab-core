# Deployment Guide

This document describes the production deployment of the **E-Lab** server
on a Linux host (tested with Debian 12 / Ubuntu 24.04). For the
development environment see [`install.md`](install.md).

## Contents

- [Deployment Guide](#deployment-guide)
  - [Architecture Overview](#architecture-overview)
  - [Prerequisites](#prerequisites)
  - [Systemd Unit](#systemd-unit)
  - [Reverse Proxy with nginx + TLS](#reverse-proxy-with-nginx--tls)
  - [Deploying the Frontend Build](#deploying-the-frontend-build)
  - [Session Backup](#session-backup)
  - [Log Rotation](#log-rotation)
  - [Updates](#updates)
  - [Security Notes](#security-notes)

---

## Architecture Overview

```text
            ┌────────────────────┐
 Browser ──►│ nginx (TLS, :443)  │──► Flask-SocketIO (gevent, :5000)
            └────────────────────┘
                   ▲
                   │ WebSocket-Upgrade (wss://)
                   │
        ESP32 Clients (LAN, no TLS)
                   │ UDP Discovery :5005
                   ▼
            E-Lab Dispatcher (server.py)
                   │
                   ▼
            sessions/*.sqlite
```

- **nginx** terminates TLS and proxies HTTP+WebSocket to `127.0.0.1:5000`.
- **ESP32 clients** connect on the LAN directly to the dispatcher (no TLS,
  since the devices are too weak for a proper crypto stack — see
  [`copilot-instructions.md`](../.github/copilot-instructions.md)).
- **Sessions** are stored as WAL-SQLite files in the `sessions/` directory.

---

## Prerequisites

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip nginx certbot \
                    python3-certbot-nginx sqlite3
```

Create an unprivileged service user:

```bash
sudo useradd --system --create-home --shell /usr/sbin/nologin elab
sudo mkdir -p /opt/elab
sudo chown elab:elab /opt/elab
```

Clone the source code and create a venv:

```bash
sudo -u elab git clone https://example.invalid/E-Lab.git /opt/elab
cd /opt/elab
sudo -u elab python3 -m venv .venv
sudo -u elab .venv/bin/pip install --upgrade pip
sudo -u elab .venv/bin/pip install -r requirements.txt
```

> **Note:** If no `requirements.txt` exists, the dependencies
> (`flask`, `flask-socketio`, `gevent`, `gevent-websocket`,
> `python-engineio`) must be installed explicitly.

---

## Systemd Unit

File `/etc/systemd/system/elab.service`:

```ini
[Unit]
Description=E-Lab Dispatcher
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=elab
Group=elab
WorkingDirectory=/opt/elab
Environment=PYTHONUNBUFFERED=1
# Optional: trusted plugin script origins (comma-separated; also configurable via CLI)
# Environment=ELAB_PLUGIN_ORIGINS=http://192.168.1.50:8080,http://internal-cdn:*
ExecStart=/opt/elab/.venv/bin/python /opt/elab/server.py
Restart=on-failure
RestartSec=5

# Hardening
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/opt/elab/sessions
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX AF_NETLINK
LockPersonality=true
MemoryDenyWriteExecute=false  # gevent uses JIT-like patches
SystemCallArchitectures=native

# Resource limits
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
```

Activate:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now elab.service
sudo systemctl status elab.service
journalctl -u elab.service -f       # Live logs
```

### Plugin Script Origins (Security)

Trusted plugin origins can be configured two ways:

**Option 1: Environment variable** (recommended for systemd)
```ini
# In /etc/systemd/system/elab.service [Service] section:
Environment=ELAB_PLUGIN_ORIGINS=http://192.168.1.50:8080,http://internal-cdn:*
```

**Option 2: CLI argument** (useful for development or when the service wrapper doesn't support `Environment=`)
```bash
ExecStart=/opt/elab/.venv/bin/python /opt/elab/server.py --plugin-origins "http://192.168.1.50:8080,http://internal-cdn:*"
```

Both sources are merged at startup. Format: `scheme://host[:port]` or `scheme://host:*` (port wildcard).
Origins must be trusted explicitly — the dispatcher will otherwise strip `ui.url` and `ui.integrity` from plugin manifests and fall back to generic mode.

---

## Reverse Proxy with nginx + TLS

File `/etc/nginx/sites-available/elab.conf`:

```nginx
upstream elab_backend {
    server 127.0.0.1:5000;
    keepalive 32;
}

server {
    listen 80;
    listen [::]:80;
    server_name elab.example.org;

    # Serve Let's Encrypt challenge, redirect everything else to HTTPS.
    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }
    location / {
        return 301 https://$host$request_uri;
    }
}

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name elab.example.org;

    ssl_certificate     /etc/letsencrypt/live/elab.example.org/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/elab.example.org/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;

    # Security headers
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    add_header X-Frame-Options "DENY" always;

    # Maximum upload size (plugin JS, manifest)
    client_max_body_size 4M;

    # WebSocket / Socket.IO
    location /socket.io/ {
        proxy_pass http://elab_backend/socket.io/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 3600s;       # Long-lived WS connections
        proxy_send_timeout 3600s;
        proxy_buffering off;
    }

    # Static frontend
    location / {
        root /opt/elab/elab_workbench/dist;
        try_files $uri $uri/ /index.html;
        gzip on;
        gzip_types text/css application/javascript application/json image/svg+xml;
    }
}
```

Enable + obtain TLS certificate:

```bash
sudo ln -s /etc/nginx/sites-available/elab.conf /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx

sudo certbot --nginx -d elab.example.org
```

certbot automatically installs a renewal cron in `/etc/cron.d/certbot`.

---

## Deploying the Frontend Build

```bash
cd /opt/elab/elab_workbench
sudo -u elab npm ci
sudo -u elab npm run build
```

The Vite build outputs to `elab_workbench/dist/` and is served directly by
nginx. Rebuild on every update.

---

## Session Backup

Sessions are WAL-SQLite files. For a consistent backup, do not copy them raw;
instead use `sqlite3 .backup` so the WAL and main file are merged into a
consistent snapshot.

Script `/usr/local/sbin/elab-backup.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
SRC=/opt/elab/sessions
DEST=/var/backups/elab
DATE=$(date +%Y-%m-%d)
mkdir -p "$DEST/$DATE"
find "$SRC" -name 'session.sqlite' -print0 | while IFS= read -r -d '' db; do
    rel=${db#$SRC/}
    target="$DEST/$DATE/${rel//\//_}"
    sqlite3 "$db" ".backup '$target'"
    gzip -f "$target"
done
# Retention: 30 days
find "$DEST" -maxdepth 1 -type d -mtime +30 -exec rm -rf {} +
```

Install:

```bash
sudo install -m 0755 elab-backup.sh /usr/local/sbin/elab-backup.sh
sudo crontab -e
# Daily backup at 03:15
15 3 * * * /usr/local/sbin/elab-backup.sh >> /var/log/elab-backup.log 2>&1
```

---

## Log Rotation

Since the server runs through `journalctl`, rotation is handled by
systemd-journald (`/etc/systemd/journald.conf`, `SystemMaxUse=`).

If the backup logs need to be rotated separately,
`/etc/logrotate.d/elab`:

``` text
/var/log/elab-backup.log {
    weekly
    rotate 8
    compress
    missingok
    notifempty
    create 0640 root root
}
```

---

## Updates

```bash
sudo systemctl stop elab.service
cd /opt/elab
sudo -u elab git pull --ff-only
sudo -u elab .venv/bin/pip install --upgrade -r requirements.txt
cd elab_workbench
sudo -u elab npm ci
sudo -u elab npm run build
cd ..
sudo systemctl start elab.service
```

Always create a **backup** before each update (`elab-backup.sh`).

---

## Security Notes

- **No TLS on the ESP32 path.** The devices are too weak, so the LAN segment
  where the ESP32 clients and the dispatcher reside MUST be isolated from the
  rest of the network (dedicated VLAN, firewall rules).
- **Plugin URLs** are filtered server-side via an allow-list
  (`elab_server/sockets.py`, `_PLUGIN_ORIGIN_ALLOWLIST`). New plugin hosts
  must be added there, otherwise the stream is blocked.
- **SRI hashes** for injected plugin scripts are transmitted in the manifest —
  see [`plugin_development.md`](plugin_development.md).
- **Service user** `elab` has no login shell and write permissions only to
  `sessions/`.
- **systemd hardening** (see unit above) prohibits new privileges, write
  access outside `sessions/`, and protects kernel tunables.
