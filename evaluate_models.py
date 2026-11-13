"""Read-only report on how well the virtual football predictions work.

It never writes to the database and never changes a model file. It prints:
  A. how much settled history there is and the plain base rates;
  B. how the predictions that were really published have done;
  C. whether other model types would rank matches better, tested on the newest
     20% of the history after training on the older 80%.

Run on the VPS:
    cd /home/balls49/virtualFootball
    VIRTUAL_DB_PATH=/var/lib/balls49-virtual/matches.db .venv/bin/python evaluate_models.py
"""
import json
import math
import os
import re
import sqlite3
import warnings
from collections import defaultdict
from pathlib import Path

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings('ignore')
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / '.env')
except Exception:
    pass
DB = Path(os.getenv('VIRTUAL_DB_PATH', Path(__file__).resolve().parent / 'matches.db')).expanduser()


def pct(value):
    return '   -  ' if value is None or not math.isfinite(value) else f'{value * 100:5.1f}%'


def load():
    with sqlite3.connect(DB.resolve().as_uri() + '?mode=ro', uri=True) as connection:
        columns = {row[1] for row in connection.execute('PRAGMA table_info(matches)')}
        optional = ['prediction', 'confidence', 'prediction_gg', 'confidence_gg', 'confidence_over15', 'website_markets', 'website_round']
        select = ', '.join(name if name in columns else f'NULL AS {name}' for name in optional)
        rows = connection.execute(f"""SELECT home_team, away_team, home_odds, draw_odds, away_odds, live_score, actual_result,
            timestamp, {select} FROM matches WHERE match_status='SETTLED' AND actual_result IN ('HOME','DRAW','AWAY')
            ORDER BY timestamp, id""").fetchall()
    matches = []
    for row in rows:
        score = re.fullmatch(r'\s*(\d{1,2})\s*-\s*(\d{1,2})\s*', str(row[5]))
        try:
            odds = [float(row[2]), float(row[3]), float(row[4])]
        except (TypeError, ValueError):
            continue
        if not score or not row[7] or any(not math.isfinite(o) or o <= 1 for o in odds):
            continue
        hg, ag = int(score.group(1)), int(score.group(2))
        try:
            markets = json.loads(row[13]) if row[13] else None
        except ValueError:
            markets = None
        matches.append({'home': row[0], 'away': row[1], 'odds': odds, 'hg': hg, 'ag': ag, 'result': row[6], 'time': row[7],
                        'round': row[14] or row[7], 'over': hg + ag >= 2, 'gg': hg > 0 and ag > 0,
                        'pred': row[8], 'conf': row[9], 'pred_gg': row[10], 'conf_gg': row[11], 'conf_over': row[12], 'markets': markets})
    return matches


def add_features(matches):
    """Odds features plus each team's record so far (only matches played earlier)."""
    team = defaultdict(lambda: [0, 0, 0, 0, 0])  # games, goals for, goals against, overs, both-scored
    pair = defaultdict(lambda: [0, 0, 0])        # games, overs, both-scored for this exact fixture
    total = [0, 0, 0, 0]                         # games, goals, overs, both-scored
    pending, last_round = [], None

    def flush():
        for m in pending:
            for name, gf, ga in ((m['home'], m['hg'], m['ag']), (m['away'], m['ag'], m['hg'])):
                record = team[name]
                record[0] += 1; record[1] += gf; record[2] += ga; record[3] += m['over']; record[4] += m['gg']
            fixture = pair[(m['home'], m['away'])]
            fixture[0] += 1; fixture[1] += m['over']; fixture[2] += m['gg']
            total[0] += 1; total[1] += m['hg'] + m['ag']; total[2] += m['over']; total[3] += m['gg']
        pending.clear()

    for m in matches:
        if m['round'] != last_round:
            flush(); last_round = m['round']
        implied = [1 / o for o in m['odds']]
        margin = sum(implied)
        fair = [value / margin for value in implied]
        m['fair'] = fair
        m['x_odds'] = m['odds'] + fair + [margin]
        m['x_fair'] = [fair[0], fair[1], abs(fair[0] - fair[2]), max(fair[0], fair[2])]
        games = max(total[0], 1)
        mean_goals, mean_over, mean_gg = total[1] / games / 2, total[2] / games, total[3] / games
        history = []
        for name in (m['home'], m['away']):
            n, gf, ga, overs, ggs = team[name]
            k = 20  # shrink small samples towards the league average
            history += [(gf + k * mean_goals) / (n + k), (ga + k * mean_goals) / (n + k), (overs + k * mean_over) / (n + k), (ggs + k * mean_gg) / (n + k)]
        n, overs, ggs = pair[(m['home'], m['away'])]
        history += [(overs + 5 * mean_over) / (n + 5), (ggs + 5 * mean_gg) / (n + 5), min(n, 50)]
        m['x_team'] = m['x_odds'] + history
        pending.append(m)


def log_loss(prob, truth):
    prob = np.clip(np.asarray(prob, dtype=float), 1e-6, 1 - 1e-6)
    truth = np.asarray(truth, dtype=float)
    return float(-np.mean(truth * np.log(prob) + (1 - truth) * np.log(1 - prob)))


def rounds_of(matches):
    grouped = defaultdict(list)
    for index, m in enumerate(matches):
        grouped[m['round']].append(index)
    return [indexes for indexes in grouped.values() if len(indexes) >= 5]


def pick_rates(prob, truth, groups):
    """Round results if the top matches were picked: top-1 hit, top-2 both hit, bottom-1 miss."""
    top1, top2, low = [], [], []
    for indexes in groups:
        order = sorted(indexes, key=lambda i: -prob[i])
        top1.append(truth[order[0]])
        top2.append(truth[order[0]] and truth[order[1]])
        low.append(not truth[order[-1]])
    mean = lambda values: sum(values) / len(values) if values else None
    return mean(top1), mean(top2), mean(low)


def candidates():
    return {
        'forest on odds (current type)': ('x_odds', lambda: RandomForestClassifier(n_estimators=150, max_depth=6, min_samples_leaf=10, random_state=89, n_jobs=1)),
        'logistic on odds': ('x_odds', lambda: make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000))),
        'logistic on fair chances': ('x_fair', lambda: make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000))),
        'boosting on odds': ('x_odds', lambda: HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=200, min_samples_leaf=40, random_state=7)),
        'logistic on odds + team record': ('x_team', lambda: make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000, C=0.3))),
        'boosting on odds + team record': ('x_team', lambda: HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=200, min_samples_leaf=40, random_state=7)),
    }


def compare(title, key, train, test, low_label):
    y_train = [m[key] for m in train]
    y_test = [m[key] for m in test]
    groups = rounds_of(test)
    base = sum(y_train) / len(y_train)
    print(f'\n{title}: happened in {pct(sum(y_test) / len(y_test))} of the test matches ({len(test)} matches, {len(groups)} rounds)')
    print(f'  {"model":34} {"log loss":>8} {"top-1 hit":>10} {"top-2 both":>11} {low_label:>13}')
    print(f'  {"no model (same chance for all)":34} {log_loss([base] * len(y_test), y_test):8.4f} {pct(sum(y_test) / len(y_test)):>10} {pct((sum(y_test) / len(y_test)) ** 2):>11} {pct(1 - sum(y_test) / len(y_test)):>13}')
    if len(set(y_train)) < 2:
        print('  only one outcome in the training part; nothing to compare'); return
    for name, (field, build) in candidates().items():
        try:
            model = build().fit([m[field] for m in train], y_train)
            prob = model.predict_proba([m[field] for m in test])[:, list(model.classes_).index(True)]
            top1, top2, low = pick_rates(prob, y_test, groups)
            print(f'  {name:34} {log_loss(prob, y_test):8.4f} {pct(top1):>10} {pct(top2):>11} {pct(low):>13}')
        except Exception as error:
            print(f'  {name:34} failed: {type(error).__name__}')


def buckets(title, pairs):
    print(f'\n{title}')
    if not pairs:
        print('  no stored values'); return
    edges = [0, 50, 55, 60, 65, 70, 75, 80, 85, 90, 101]
    for low, high in zip(edges, edges[1:]):
        hits = [hit for conf, hit in pairs if low <= conf < high]
        if hits:
            print(f'  said {low:>3}-{min(high, 100):<3}%: {len(hits):6} matches, came true {pct(sum(hits) / len(hits))}')


def main():
    matches = load()
    print(f'A. HISTORY\n  settled matches with odds and score: {len(matches)}')
    if len(matches) < 60:
        print('  Too little history to say anything.'); return
    add_features(matches)
    print(f'  from {matches[0]["time"]} to {matches[-1]["time"]}; teams: {len({m["home"] for m in matches})}')
    count = len(matches)
    print(f'  home {pct(sum(m["result"] == "HOME" for m in matches) / count)}  draw {pct(sum(m["result"] == "DRAW" for m in matches) / count)}  away {pct(sum(m["result"] == "AWAY" for m in matches) / count)}')
    print(f'  over 1.5 {pct(sum(m["over"] for m in matches) / count)}  under 1.5 {pct(1 - sum(m["over"] for m in matches) / count)}  GG {pct(sum(m["gg"] for m in matches) / count)}  NG {pct(1 - sum(m["gg"] for m in matches) / count)}')
    print(f'  average bookmaker margin on 1X2: {pct(sum(sum(1 / o for o in m["odds"]) for m in matches) / count - 1)}')
    if count < 1000:
        print('  NOTE: under 1000 matches. Differences of a few points below are noise.')

    print('\nB. WHAT WAS REALLY PUBLISHED')
    with_pred = [m for m in matches if m['pred'] in ('HOME', 'DRAW', 'AWAY')]
    if with_pred:
        favourite = sum(('HOME', 'DRAW', 'AWAY')[int(np.argmin(m['odds']))] == m['result'] for m in with_pred) / len(with_pred)
        print(f'  Win model right on {pct(sum(m["pred"] == m["result"] for m in with_pred) / len(with_pred))} of {len(with_pred)} matches; always taking the favourite: {pct(favourite)}')
    with_gg = [m for m in matches if m['pred_gg'] in ('GG', 'NG')]
    if with_gg:
        print(f'  GG/NG model right on {pct(sum((m["pred_gg"] == "GG") == m["gg"] for m in with_gg) / len(with_gg))} of {len(with_gg)} matches')
    buckets('  Over 1.5 confidence against what happened:', [(float(m['conf_over']), m['over']) for m in matches if m['conf_over'] is not None])
    buckets('  GG/NG confidence against what happened:', [(float(m['conf_gg']), (m['pred_gg'] == 'GG') == m['gg']) for m in with_gg if m['conf_gg'] is not None])
    buckets('  Win confidence against what happened:', [(float(m['conf']), m['pred'] == m['result']) for m in with_pred if m['conf'] is not None])
    print('\n  Published picks (one line per market):')
    for market, won in (('over', lambda m: m['over']), ('under', lambda m: not m['over']), ('gg', lambda m: m['gg']), ('ng', lambda m: not m['gg']), ('win', lambda m: m['pred'] == m['result'])):
        picks = [m for m in matches if m['markets'] and market in m['markets']]
        if not picks:
            print(f'    {market:6} no picks stored'); continue
        line = f'    {market:6} {len(picks):5} picks, won {pct(sum(won(m) for m in picks) / len(picks))}'
        if market == 'win':
            price = [m['odds'][0 if m['pred'] == 'HOME' else 2] for m in picks if m['pred'] in ('HOME', 'AWAY')]
            returned = sum(m['odds'][0 if m['pred'] == 'HOME' else 2] for m in picks if m['pred'] in ('HOME', 'AWAY') and won(m))
            if price:
                line += f', average odds {sum(price) / len(price):.2f}, return per 1 staked {returned / len(price):.3f} (above 1.000 is profit)'
        print(line)

    print('\nC. WOULD ANOTHER MODEL RANK MATCHES BETTER?')
    print('  Trained on the oldest 80%, tested on the newest 20%. Lower log loss is better.')
    print('  top-1 hit = the most confident match of each round came true; top-2 both = the two most confident both did.')
    cutoff = matches[int(count * 0.8)]['round']
    position = next(i for i, m in enumerate(matches) if m['round'] == cutoff)
    train, test = matches[:position], matches[position:]
    if len(train) < 50 or len(test) < 10:
        print('  not enough history for a split'); return
    compare('OVER 1.5', 'over', train, test, 'lowest under')
    compare('GG (both teams score)', 'gg', train, test, 'lowest = NG')
    for m in matches:
        m['homewin'] = m['result'] == 'HOME'; m['awaywin'] = m['result'] == 'AWAY'
    compare('HOME WIN', 'homewin', train, test, 'lowest loses')
    fair_loss = log_loss([m['fair'][0] for m in test], [m['homewin'] for m in test])
    print(f'  {"bookmaker odds alone (no training)":34} {fair_loss:8.4f}')
    print('\nDone. Nothing was changed.')


if __name__ == '__main__':
    main()
