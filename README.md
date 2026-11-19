# Virtual Football: predictions, website feed and auto-bet extension

This repository holds the backend that predicts Bet9ja virtual football rounds
and the Chrome extension that places the bets. The website that shows the
predictions lives in the separate `balls49` repository.

Last updated: 19 November 2026 (extension 3.3, Over 2.5).

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
https://predictions.emmyfxchart.com/virtual-football.html  and  /virtual-results.html
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
| `over25_model.py`, `train_model_over25.py` | The Over 2.5 goals model and its trainer: 1X2 odds, the Over 1.5 price, each team's last 10 matches and the two teams' last 5 meetings. The trained file `ai_brain_over25.pkl` is not in Git; it is created on the VPS. |
| `gg_odds_model.py`, `train_model_gg_odds.py` | GG/NG model that uses only the 1X2 odds, and its trainer. When its file `ai_brain_gg_odds.pkl` (not in Git, created on the VPS) exists, it replaces the older GG/NG model. |
| `train_model.py`, `train_model_gg.py` | Trainers for the Win model (`ai_brain.pkl`) and the GG/NG model (`ai_brain_gg.pkl`). Both model files are in Git. |
| `evaluate_models.py` | Read-only report: how the published predictions have done and whether another model type would rank matches better. Changes nothing. |
| `auto_trainer.py` | Retrains the models on a timer. It has no systemd service; it only runs if started by hand. |
| `deploy/` | VPS installer, the two systemd services, the Nginx routes and an example environment file. See `DEPLOYMENT.md`. |

### Picks chosen each round

| Market | Rule | Picks |
| --- | --- | --- |
| Over 1.5 | The two highest Over 1.5 confidences, each at least 60%. Fewer than two means the round is skipped. | 2 or 0 |
| Over 2.5 | The highest Over 2.5 confidence of the round, only at 50% or more. Wins on 3+ goals. Website, Telegram and the extension's Over 2.5 Single mode. | 1 or 0 |
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

### Website dashboard (`/dashboard/status`, `/dashboard/command`)

Each licence key has its own session (`ext_sessions.py`): the state its extension reports,
a command queue, and recently delivered commands. Members link their licence key once on
`virtual-automation.html`; the website stores it encrypted and calls these two routes on
`127.0.0.1:5000` with the `X-Dashboard-Secret` header (`VIRTUAL_FEED_SECRET`, shared with the
website). Nginx does not forward `/virtual-api/dashboard/`. Commands reach the extension on
its next `/sync`, within about 3 seconds. Sessions are kept in memory and refill on the
next sync after a restart.

### Licence keys

Keys in `VALID_KEYS` (the service environment) never expire. Members' keys are issued from the
website's owner section (Virtual football → Licence keys): the website calls
`/dashboard/licence` to grant, renew or revoke, and `licences.py` stores only a hash of each key
with its expiry in the `extension_licences` table of `matches.db`. No restart is needed; an
expired or revoked key gets 401 on its next sync and the extension stops.

### Telegram commands

`/start`, `/stop`, `/stake <amount>`, `/tp <amount>`, `/sl <amount>`,
`/mode OU|O25|UN|1X2|GG|NG`, `/reset`, `/history`, `/status`.
Commands reach only the extensions that saved that chat ID in their popup; the admin
chats reach every connected extension. `/reset` from an admin chat also resets the
shared market loss streaks.

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

### Chrome extension (`bet_auto_extension/`, version 3.3)

- `popup.html`, `popup.js`: licence key, base stake, take profit, stop loss,
  max loss streak, max stake, min total odds, Telegram chat id and the mode.
- `content.js`: runs on `vsmobile.bet9ja.com`. Every 3 seconds it calls
  `/sync`, and for a new round it opens the market tab, ticks the picks, checks
  the odds, enters the stake and places the bet.

| Mode | Bet9ja tab | Ticks |
| --- | --- | --- |
| Over 1.5 Double | Over/Under 1.5 | Over on two matches |
| Over 2.5 Single | Over/Under 2.5 (market menu) | Over on one match |
| Under 1.5 Single | Over/Under 1.5 | Under on one match |
| Win Single | Match Result | Home or Away |
| GG Single | GG/NG | GG |
| NG Single | GG/NG | NG |

Stake after losses: `base + streakLoss / (odds − 1)`, so one win recovers the
streak plus the normal profit. A round is skipped when the total odds are below
the minimum: 1.65 by default for every mode, or the value typed in the popup. The bot stops itself when it cannot find the market, the tab does not
open, or a limit (take profit, stop loss, max loss streak) is reached.

## What the history says (13 November 2026, 90,620 settled matches)

Measured with `evaluate_models.py`:

- **Nothing beats the bookmaker's odds.** For home wins, the plain odds predict
  as well as every trained model. Team names and past form add nothing, so the
  results appear to be drawn from the odds.
- **Over 1.5** is at its ceiling: every model type scores the same. The two
  picks both win in about 62% of rounds, so the double only pays when the
  combined odds are above about 1.62.
- **Under 1.5** (lowest Over confidence) wins about 28% of the time, so it only
  pays at odds above about 3.6.
- **GG / NG**: the older model's picks won 55.3% (GG) and 47.3% (NG). The
  odds-only model reached about 57% and 54% on unseen matches, which is why it
  replaced the older one. Break-even odds are about 1.75 for GG and 1.85 for NG.
- **Win** picks won 47.8% at average odds 2.05: a return of 0.965 per 1 staked,
  a loss of about 3.5%, close to the bookmaker's 5.2% margin.

The recovery staking does not change these averages; it only changes when the
losses arrive.

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
Start. To confirm a deploy, open `https://predictions.emmyfxchart.com/public-virtual-football`
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
3. **Whether any market pays at the real prices.** Since 14 November 2026 the
   generator stores the real Over, Under, GG and NG prices. After about a day
   of rounds, run `evaluate_models.py` and read "Picks with real market prices
   stored": a return above 1.000 is profit, below is loss.

Known gaps in the backend:

4. **The new price reader is not yet confirmed on the live page.**
   `get_all_market_odds()` in `new.py` now reads the Over/Under 1.5 and GG/NG
   panels directly and stores `over_15_odds`, `under_15_odds`, `gg_odds` and
   `ng_odds`. Check the log line `Market prices read:`; the Over/Under and
   GG/NG counts should equal the 1X2 count. GG/NG prices stored before
   14 November 2026 are unreliable. Once confirmed, the prices can be used
   to skip a pick whose price is too low to pay.
5. **No dedicated Under 1.5 model.** A model trained for Under, or a rule that
   uses real Under odds, would be a better basis than "lowest Over confidence".
6. **Loss streaks reset on restart.** The generator keeps them in memory, so
   `/status` starts from zero after every restart.
7. **A restart can lose one round.** The round in progress when the generator
   restarts may not be settled.
8. **`auto_trainer.py` is not a service.** Models are only retrained when
   someone runs it. `ai_brain_over15.pkl` and `ai_brain_gg_odds.pkl` must
   exist on the VPS.
9. **No automated test for `new.py`.** Only `publish_site_feed.py` has one
   (`test_publish_site_feed.py`). The extension has a simulation in
   `tests/extension_sim.cjs`.

10. **Over 2.5 market on Bet9ja not yet seen by the bot.** The extension looks for
    `Over_Under_2_5` in the market menu, as the extension simulation models the
    page. If Bet9ja names it differently, the bot stops before ticking anything
    and its message lists the market values the page has; check the first
    Over 2.5 ticket by hand.

Housekeeping:

11. **`bet_auto_extension.zip` and `work.py`** are still tracked in Git but
    deleted in the local working copy. Decide whether to remove them for good
    or rebuild the zip from the current extension.
12. **Domain.** Extension 3.5 connects to `predictions.emmyfxchart.com` and falls back to
    the server IP (`159.65.25.30`) while the domain cannot be reached (`api-base.js`). The
    domain needs a DNS A record to the server and is set up on the server with
    `bash deploy/add-site-domain.sh predictions.emmyfxchart.com` in the balls49 repository.
    Run that again after `deploy/install-vps.sh`, which only updates the IP's nginx block.