# Virtual Football VPS deployment

The virtual generator remains in this repository. A separate publisher reads its
SQLite match database and sends a signed snapshot to the Balls49 website. The
website never connects directly to the generator's database.

## Prepare the website

Deploy the latest `balls49` repository to
`/home/balls49/balls49-site`, rebuild its web assets with
`npm run build:same-origin`, and restart `balls49-site.service`. The site API
must include `POST /internal/virtual-football-snapshot` and
`GET /public-virtual-football`.

The site must use the updated Nginx configuration in
`balls49/deploy/balls49-site.nginx.conf`. It proxies the signed feed to the
website API and maps `/virtual-api/` to the private Flask API on localhost.

## Prepare the virtual worker

The worker requires a headless Chrome/Chromium installation, Python 3, outbound
HTTPS access, and the tracked AI model files. Keep runtime files and credentials
out of GitHub. In particular, do not commit `.env`, `credentials.json`, or a
live `matches.db`.

On the VPS, create `/etc/balls49/virtual.env` from
`deploy/virtual.env.example`, set `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, and
a private `VALID_KEYS` value, then protect the file:

```bash
sudo chown root:root /etc/balls49/virtual.env
sudo chmod 600 /etc/balls49/virtual.env
```

If Google Sheets export is enabled, place its service-account file at
`/etc/balls49/virtual/credentials.json` with owner `balls49` and mode `600`.
Otherwise the Sheets export can be left unconfigured.

Clone this repository to `/home/balls49/virtualFootball`, update the Balls49
site checkout first, then run as the `balls49` user:

```bash
cd /home/balls49/virtualFootball
bash deploy/install-vps.sh
```

The installer creates a persistent database under
`/var/lib/balls49-virtual`, installs the Python dependencies and two systemd
services, synchronizes a generated HMAC secret between the website and the
virtual worker, and adds the HTTPS Nginx routes. It validates Nginx and restores
the previous configuration if validation fails. The `balls49-virtual.service`
generator and `balls49-virtual-feed.service` publisher are enabled at boot and
restart automatically after a failure.

The website feed publisher defaults to a 10-second interval. For an existing
installation, set `VIRTUAL_FEED_INTERVAL_SECONDS=10` in
`/etc/balls49/virtual.env` and restart `balls49-virtual-feed.service` to apply
the faster cadence. The frontend checks for feed updates every 10 seconds.

After installation, confirm both services are active:

```bash
sudo systemctl status balls49-virtual.service balls49-virtual-feed.service --no-pager
sudo journalctl -u balls49-virtual.service -u balls49-virtual-feed.service -n 50 --no-pager
```

Reload the unpacked browser extension after updating it from this repository;
its API now uses the VPS HTTPS origin. Virtual Football predictions appear at
`https://159.65.25.30/virtual-football.html`.

## Updating

Keep the SQLite database in `/var/lib/balls49-virtual`; never pull code into the
data directory. After pulling code in `/home/balls49/virtualFootball`, rerun
`bash deploy/install-vps.sh` to update dependencies and restart the services.
Use the separate Balls49 site deployment process for website API or frontend
changes.
