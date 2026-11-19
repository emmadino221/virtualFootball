#!/usr/bin/env bash
set -euo pipefail

if [ "$(id -un)" != balls49 ]; then
  echo 'Run this script as the balls49 user.' >&2
  exit 1
fi

repo=/home/balls49/virtualFootball
site_repo=/home/balls49/balls49-site
virtual_env=/etc/balls49/virtual.env
site_env=/etc/balls49/site.env
nginx_site=/etc/nginx/sites-available/balls49-extension
data_dir=/var/lib/balls49-virtual

if [ "$(cd "$(dirname "$0")/.." && pwd)" != "$repo" ]; then
  echo "Expected the repository at $repo." >&2
  exit 1
fi
command -v python3 >/dev/null
command -v pip3 >/dev/null
command -v chromium >/dev/null 2>&1 || command -v chromium-browser >/dev/null 2>&1 || command -v google-chrome >/dev/null 2>&1 || {
  echo 'Install Chromium or Google Chrome before enabling the Virtual Football worker.' >&2
  exit 1
}
sudo -v
sudo test -f "$site_env"
sudo test -f "$virtual_env" || {
  echo "Create $virtual_env from deploy/virtual.env.example and add the Telegram and extension credentials." >&2
  exit 1
}
sudo test -f "$nginx_site"
test -f "$site_repo/deploy/balls49-site.nginx.conf" || {
  echo 'Update the Balls49 site checkout before installing this service.' >&2
  exit 1
}

sudo python3 - "$site_env" "$virtual_env" <<'PY'
import os
import secrets
import sys

site_path, virtual_path = sys.argv[1:]

def read_values(path):
    values = {}
    with open(path, encoding='utf-8') as source:
        for line in source:
            stripped = line.strip()
            if stripped and not stripped.startswith('#') and '=' in stripped:
                key, value = stripped.split('=', 1)
                values[key.strip()] = value.strip().strip('"').strip("'")
    return values

def set_values(path, updates):
    with open(path, encoding='utf-8') as source:
        lines = source.read().splitlines()
    remaining = dict(updates)
    output = []
    for line in lines:
        key, separator, _ = line.partition('=')
        if separator and key.strip() in remaining:
            value = remaining.pop(key.strip())
            output.append(f'{key.strip()}={value}')
        else:
            output.append(line)
    output.extend(f'{key}={value}' for key, value in remaining.items())
    with open(path, 'w', encoding='utf-8') as target:
        target.write('\n'.join(output) + '\n')
    os.chmod(path, 0o600)

site = read_values(site_path)
virtual = read_values(virtual_path)
for required in ('TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID', 'VALID_KEYS'):
    if not virtual.get(required):
        raise SystemExit(f'{required} must be set in {virtual_path}.')
if 'MASTER-KEY-999' in virtual['VALID_KEYS']:
    raise SystemExit('Replace the default extension key with a private key before deployment.')
site_secret = site.get('VIRTUAL_FEED_SECRET', '')
virtual_secret = virtual.get('VIRTUAL_FEED_SECRET', '')
if site_secret and virtual_secret and site_secret != virtual_secret:
    raise SystemExit('VIRTUAL_FEED_SECRET differs between the website and virtual service environment files.')
secret = site_secret or virtual_secret or secrets.token_hex(32)
if len(secret) < 32:
    raise SystemExit('VIRTUAL_FEED_SECRET must contain at least 32 characters.')
set_values(site_path, {'VIRTUAL_FEED_SECRET': secret})
set_values(virtual_path, {
    'VIRTUAL_FEED_SECRET': secret,
    'VIRTUAL_FEED_URL': 'https://159.65.25.30/internal/virtual-football-snapshot',
    'VIRTUAL_DB_PATH': '/var/lib/balls49-virtual/matches.db',
    'VIRTUAL_API_HOST': '127.0.0.1',
    'VIRTUAL_API_PORT': '5000',
    'GOOGLE_CREDENTIALS_FILE': '/etc/balls49/virtual/credentials.json',
})
PY

sudo install -d -m 700 -o balls49 -g balls49 "$data_dir"
sudo install -d -m 700 -o balls49 -g balls49 /etc/balls49/virtual
if [ ! -e "$data_dir/matches.db" ] && [ -f "$repo/matches.db" ]; then
  sudo install -m 600 -o balls49 -g balls49 "$repo/matches.db" "$data_dir/matches.db"
fi

if [ ! -x "$repo/.venv/bin/python" ]; then
  python3 -m venv "$repo/.venv"
fi
"$repo/.venv/bin/python" -m pip install --upgrade pip
"$repo/.venv/bin/python" -m pip install -r "$repo/requirements.txt"

sudo install -m 644 "$repo/deploy/balls49-virtual.service" /etc/systemd/system/balls49-virtual.service
sudo install -m 644 "$repo/deploy/balls49-virtual-feed.service" /etc/systemd/system/balls49-virtual-feed.service

backup="${nginx_site}.before-virtual-$(date +%s)"
sudo cp -p "$nginx_site" "$backup"
sudo python3 - "$nginx_site" "$repo/deploy/virtual-football-api.nginx.conf" <<'PY'
import sys

nginx_path, snippet_path = sys.argv[1:]
with open(nginx_path, encoding='utf-8') as source:
    config = source.read()
marker = '# BEGIN Balls49 Virtual Football API'
end_marker = '# END Balls49 Virtual Football API'
with open(snippet_path, encoding='utf-8') as snippet:
    block = snippet.read().rstrip()
if marker in config:
    # Refresh an installed block so route changes in the snippet reach existing servers.
    start = config.index(marker)
    end = config.find(end_marker, start)
    if end < 0:
        raise SystemExit('Nginx has a Virtual Football begin marker without an end marker; review it before continuing.')
    config = config[:start] + marker + '\n' + block + '\n' + config[end:]
else:
    has_ingest = 'location = /internal/virtual-football-snapshot' in config
    has_extension_api = 'location ^~ /virtual-api/' in config
    if has_ingest != has_extension_api:
        raise SystemExit('Nginx has a partial Virtual Football configuration; review it before continuing.')
    if not has_ingest:
        anchor = config.rfind('    location / {')
        if anchor < 0:
            raise SystemExit('Could not find the HTTPS website route in the Nginx configuration.')
        with open(snippet_path, encoding='utf-8') as snippet:
            block = snippet.read().rstrip()
        config = config[:anchor] + marker + '\n' + block + '\n# END Balls49 Virtual Football API\n' + config[anchor:]
with open(nginx_path, 'w', encoding='utf-8') as target:
    target.write(config)
PY
if ! sudo nginx -t; then
  sudo cp -p "$backup" "$nginx_site"
  echo 'Nginx validation failed; the previous configuration was restored.' >&2
  exit 1
fi

sudo systemctl daemon-reload
sudo systemctl restart balls49-site.service
sudo systemctl enable balls49-virtual.service balls49-virtual-feed.service
# restart, not only start: a service that is already running must load the new code.
sudo systemctl restart balls49-virtual.service balls49-virtual-feed.service
sudo systemctl reload nginx
sudo systemctl --no-pager --full status balls49-virtual.service balls49-virtual-feed.service
