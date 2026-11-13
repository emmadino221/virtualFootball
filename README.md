# Virtual Football: predictions, website feed and auto-bet extension

This repository holds the backend that predicts Bet9ja virtual football rounds
and the Chrome extension that places the bets. The website that shows the
predictions lives in the separate `balls49` repository.

Last updated: 13 November 2026 (extension 3.1).

## How the parts fit together

```
Bet9ja virtual page
      │  read by headless Chrome
      ▼
new.py  (generator, balls49-virtual.service)
      │  writes matches.db            ├──► Telegram messages
      │                               └──► /virtual-api/  ◄── Chrome extension
      ▼
publish_site_feed.py  (balls49-virtual-feed.service)
      │  signed snapshot every 10 s
      ▼
balls49 website  (virtual-football.js receiver, React pages)
      ▼
https://159.65.25.30/virtual-football.html  and  /virtual-results.html
```

One rule holds everywhere: the picks shown on the website, sent to Telegram and
played by the extension are the same picks. The generator chooses them once per
round and nothing downstream chooses again.

## Backend (this repository)

| File | What it does |
| --- | --- |
| `new.py` | The generator. Reads each round's fixtures and odds from Bet9ja with headless Chrome, scores them with the models, chooses the picks, settles them when scores arrive, sends Telegram messages, and serves the extension API. |
| `publish_site_feed.py` | Reads `matches.db` and posts a signed snapshot to the website every 10 seconds. It passes the picks through unchanged. |
| `over15_model.py`, `train_model_over15.py` | The Over 1.5 goals model and its trainer. The trained file `ai_brain_over15.pkl` is not in Git; it is created on the VPS. |
| `train_model.py`, `train_model_gg.py` | Trainers for the Win model (`ai_brain.pkl`) and the GG/NG model (`ai_brain_gg.pkl`). Both model files are in Git. |
| `evaluate_models.py` | Read-only report: how the published predictions have done and whether another model type would rank matches better. Changes nothing. |
| `auto_trainer.py` | Retrains the models on a timer. It has no systemd service; it only runs if started by hand. |
| `deploy/` | VPS installer, the two systemd services, the Nginx routes and an example environment file. See `DEPLOYMENT.md`. |

### Picks chosen each round

| Market | Rule | Picks |
| --- | --- | --- |
| Over 1.5 | The two highest Over 1.5 confidences, each at least 60%. Fewer than two means the round is skipped. | 2 or 0 |
| Under 1.5 | The match with the lowest Over 1.5 confidence, whatever the percentage. Never one of the Over picks. | 1 |
| GG | Highest-confidence GG prediction. | 1 or 0 |
| NG | Highest-confidence NG prediction. | 1 or 0 |
| Win | Highest-confidence HOME or AWAY whose odds are above 1.70. | 1 or 0 |

Under 1.5 has no model of its own. It depends on the Over 1.5 model file: if
that file is missing there are no Over picks and no Under picks.

### Database

SQLite at `/var/lib/balls49-virtual/matches.db` on the VPS. Table `matches`
holds every fixture with its predictions, confidences, `website_markets` (the
picks) and the score. Table `weekly_accumulators` holds one row per round with
`result_1x2`, `result_ou`, `result_gg`, `result_ng` and `result_un`
(`WIN`, `LOSS` or `N/A`). New columns are added automatically at start-up.

### Extension API (Flask, behind Nginx at `/virtual-api/`)

Every call needs the `X-License-Key` header.

| Route | Use |
| --- | --- |
| `POST /sync` | Main call. Returns the round id, `picks` for `OU`, `UN`, `1X2`, `GG`, `NG`, recent `results`, and pending Telegram commands. |
| `GET /get_bets` | Used by the popup to check the server and the key. |
| `GET /is_week_ready` | Tells the extension whether the round's picks are ready. |
| `POST /send_receipt` | The extension reports a settled bet so Telegram can show it. |

### Telegram commands

`/start`, `/stop`, `/stake <amount>`, `/tp <amount>`, `/sl <amount>`,
`/mode OU|UN|1X2|GG|NG`, `/reset`, `/history`, `/status`.

## Frontend

### Website (`balls49` repository)

- `virtual-football.js`: receives the signed snapshot at
  `POST /internal/virtual-football-snapshot`, validates it, stores it and
  serves `GET /public-virtual-football` and
  `GET /public-virtual-football-history`. Saved picks cannot be changed by a
  later snapshot.
- `web/src/pages/VirtualFootballPage.jsx`: the predictions page and the results
  page, with tabs for Over 1.5, Under 1.5, GG, NG and Win.
- Rules and feed format: `balls49/docs/29-virtual-football-markets.md`.

### Chrome extension (`bet_auto_extension/`, version 3.1)

- `popup.html`, `popup.js`: licence key, base stake, take profit, stop loss,
  max loss streak, max stake, min total odds, Telegram chat id and the mode.
- `content.js`: runs on `vsmobile.bet9ja.com`. Every 3 seconds it calls
  `/sync`, and for a new round it opens the market tab, ticks the picks, checks
  the odds, enters the stake and places the bet.

| Mode | Bet9ja tab | Ticks |
| --- | --- | --- |
| Over 1.5 Double | Over/Under 1.5 | Over on two matches |
| Under 1.5 Single | Over/Under 1.5 | Under on one match |
| Win Single | Match Result | Home or Away |
| GG Single | GG/NG | GG |
| NG Single | GG/NG | NG |

Stake after losses: `base + streakLoss / (odds − 1)`, so one win recovers the
streak plus the normal profit. A round is skipped when the total odds are below
the minimum: 1.65 by default, 1.40 for Over 1.5, or the value typed in the
popup. The bot stops itself when it cannot find the market, the tab does not
open, or a limit (take profit, stop loss, max loss streak) is reached.

## Deploying a change

Order matters when the feed format changes: **website first, then this
repository.** An older website rejects snapshots it does not understand and the
feed stops.

```bash
# 1. Website
sudo systemctl start balls49-site-backup.service && cd ~/balls49-site && git pull --ff-only origin main && npm --prefix web ci && npm --prefix web run build:same-origin && sudo systemctl restart balls49-site

# 2. Generator and feed
cd /home/balls49/virtualFootball && git pull --ff-only origin main && bash deploy/install-vps.sh
```

Extension: reload it in `chrome://extensions`, reload the Bet9ja tab, press
Start. To confirm a deploy, open `https://159.65.25.30/public-virtual-football`
and look for the new data in the newest round.

## What still needs to be done

Not yet proven:

1. **Under 1.5 results.** The pick bets against a model that rates the match
   about 70% likely to go over. Let the website record about 100 rounds and
   compare the win rate with the odds before using the mode with money.
2. **Under and Over button names on Bet9ja.** The names of the Over/Under and
   GG/NG buttons were never captured. When a name is not recognised the
   extension uses position (first button Over or GG, second Under or NG). Check
   the first ticket of each mode.
3. **Over 1.5 minimum odds of 1.40.** Tested in the simulation only.

Known gaps in the backend:

4. **Odds for GG, NG, Over and Under are not collected reliably.**
   `get_all_market_odds()` in `new.py` switches markets through a menu that, on
   the real page, lists only the extra markets. The stored GG/NG odds are
   probably wrong and `over_15_odds` is never filled. Fixing this would allow
   an odds-based check before a pick is published.
5. **No dedicated Under 1.5 model.** A model trained for Under, or a rule that
   uses real Under odds, would be a better basis than "lowest Over confidence".
6. **Loss streaks reset on restart.** The generator keeps them in memory, so
   `/status` starts from zero after every restart.
7. **A restart can lose one round.** The round in progress when the generator
   restarts may not be settled.
8. **`auto_trainer.py` is not a service.** Models are only retrained when
   someone runs it. `ai_brain_over15.pkl` must exist on the VPS.
9. **No automated test for `new.py`.** Only `publish_site_feed.py` has one
   (`test_publish_site_feed.py`). The extension has a simulation in
   `tests/extension_sim.cjs`.

Housekeeping:

10. **`bet_auto_extension.zip` and `work.py`** are still tracked in Git but
    deleted in the local working copy. Decide whether to remove them for good
    or rebuild the zip from the current extension.
11. **The site runs on a bare IP address** (`159.65.25.30`). A domain name
    would need updates in `content.js`, `popup.js`, `manifest.json` and the
    installer.
