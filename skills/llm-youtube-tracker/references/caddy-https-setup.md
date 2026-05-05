# Caddy Auto-HTTPS Setup on AWS EC2 (ARM64)

## Install Caddy

```bash
# Download ARM64 binary (EC2 is aarch64, NOT x86-64!)
curl -fsSL "https://caddyserver.com/api/download?os=linux&arch=arm64" -o /tmp/caddy
chmod +x /tmp/caddy
sudo mv /tmp/caddy /usr/local/bin/caddy
caddy version
```

## Caddyfile

```
track.ionce.me {
    reverse_proxy localhost:8080
}
```

That's it — Caddy auto-obtains Let's Encrypt SSL, enables HTTP→HTTPS redirect, HTTP/2, HTTP/3.

## Start / Stop

```bash
# Start (needs sudo for ports 80/443)
sudo caddy start --config Caddyfile 2>&1

# Stop
sudo caddy stop

# Validate config
sudo caddy validate --config Caddyfile
```

## Pitfalls

- **Port 80 in use:** `sudo fuser -k 80/tcp` before starting. Old Python redirect proxy or other services may hold the port.
- **Wrong architecture:** Amazon Linux 2023 on this EC2 is ARM64. The Caddy download URL MUST include `arch=arm64`. x86-64 binary gives "Exec format error".
- **COPR repo doesn't work** on Amazon Linux — direct binary download is the reliable path.
- **Certificate storage:** `/root/.local/share/caddy/` — persists across restarts.
- **Admin API:** Available at `localhost:2019` for runtime config changes.

## Verification

```bash
curl -sI https://track.ionce.me | head -5
# Should show: HTTP/2 200, server: Caddy, via: 1.0 Caddy
```
