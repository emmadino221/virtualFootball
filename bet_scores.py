"""Adds final scores to the bets a member's extension reports, from the generator's database."""
import sqlite3
from contextlib import closing

# Market key each mode's pick is saved under in matches.website_markets.
MODE_MARKETS = {"OU": "over", "O25": "over25", "UN": "under", "1X2": "win", "GG": "gg", "NG": "ng"}


def attach_scores(bets, db_path):
    """Return copies of the bets with a score and finished flag on every pick.

    Picks come from the extension; bets from older extensions without picks get the round's
    published matches for their mode. A bet whose round is not in the database is returned
    unchanged. Never raises: the dashboard still shows bets if the database is busy.
    """
    bets = [dict(b) for b in bets if isinstance(b, dict)]
    rounds = sorted({b.get("roundId") for b in bets if b.get("roundId")})
    if not rounds:
        return bets
    try:
        with closing(sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)) as db:
            placeholders = ",".join("?" * len(rounds))
            rows = db.execute(f"""SELECT website_round, home_team, away_team, live_score, match_status, website_markets
                FROM matches WHERE website_round IN ({placeholders})""", rounds).fetchall()
    except sqlite3.Error:
        return bets
    by_round = {}
    for round_id, home, away, score, status, markets in rows:
        by_round.setdefault(round_id, []).append({"home": home, "away": away, "status": status, "markets": markets or "",
                                                  "score": score if status == "SETTLED" else None})
    for bet in bets:
        matches = by_round.get(bet.get("roundId"), [])
        if not matches:
            continue
        picks = bet.get("picks") or []
        if not picks:
            market = MODE_MARKETS.get(bet.get("mode"))
            picks = [{"home": m["home"], "away": m["away"], "pick": None} for m in matches
                     if market and f'"{market}"' in m["markets"]]
        enriched = []
        for pick in picks:
            match = next((m for m in matches if {m["home"], m["away"]} == {pick.get("home"), pick.get("away")}), None)
            enriched.append({**pick, "score": match["score"] if match else None,
                             "finished": bool(match and match["status"] == "SETTLED")})
        bet["picks"] = enriched
    return bets
