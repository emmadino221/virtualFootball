"""Train explicitly with: python train_model_over25.py. Does not start the collector.

Reads the generator's database without changing it and writes ai_brain_over25.pkl.
Every match is scored only from matches that finished before it, so the history inputs
match what the live generator can see when it makes the pick.
"""
from collections import defaultdict, deque
from contextlib import closing
import math
import os
from pathlib import Path
import sqlite3
import tempfile

import joblib
from dotenv import load_dotenv

from over25_model import FEATURE_NAMES, MEETING_WINDOW, TARGET, TEAM_WINDOW, features, total_goals

MINIMUM_MATCHES = 2000


def load_samples(db):
    with closing(sqlite3.connect(Path(db).resolve().as_uri() + '?mode=ro', uri=True)) as connection:
        columns = {row[1] for row in connection.execute('PRAGMA table_info(matches)')}
        optional = ', '.join(name if name in columns else f'NULL AS {name}'
                             for name in ('over_15_odds', 'under_15_odds', 'website_round'))
        rows = connection.execute(f"""SELECT home_team, away_team, home_odds, draw_odds, away_odds,
            live_score, timestamp, week, {optional} FROM matches
            WHERE match_status = 'SETTLED' ORDER BY id""").fetchall()
    team_history = defaultdict(lambda: deque(maxlen=TEAM_WINDOW))
    meeting_history = defaultdict(lambda: deque(maxlen=MEETING_WINDOW))
    samples = []
    for home, away, home_odds, draw_odds, away_odds, score, timestamp, week, over15, under15, round_id in rows:
        goals = total_goals(score)
        if goals is None or not timestamp:
            continue
        pair = frozenset((home, away))
        match = {'home_odds': home_odds, 'draw_odds': draw_odds, 'away_odds': away_odds,
                 'over_15_odds': over15, 'under_15_odds': under15}
        try:
            # Newest first, as the live lookup returns them.
            vector = features(match, list(team_history[home])[::-1], list(team_history[away])[::-1],
                              list(meeting_history[pair])[::-1])
        except (ValueError, TypeError):
            vector = None
        if vector is not None:
            samples.append((vector, 'OVER' if goals >= 3 else 'UNDER', timestamp, round_id or f'{week}|{timestamp}'))
        # Recorded after scoring, so a match never sees its own result.
        team_history[home].append(goals)
        team_history[away].append(goals)
        meeting_history[pair].append(goals)
    return samples


def top_pick_rate(model, holdout):
    """Share of rounds whose highest-confidence match went over 2.5: what the published pick does."""
    rounds = defaultdict(list)
    for vector, label, _, round_key in holdout:
        rounds[round_key].append((vector, label))
    index = list(model.classes_).index('OVER')
    hits = played = 0
    for entries in rounds.values():
        if len(entries) < 2:
            continue
        chances = model.predict_proba([vector for vector, _ in entries])[:, index]
        best = max(range(len(entries)), key=lambda i: chances[i])
        played += 1
        hits += entries[best][1] == 'OVER'
    return (hits / played if played else math.nan), played


def main():
    base = Path(__file__).resolve().parent
    load_dotenv(base / '.env')
    db = Path(os.getenv('VIRTUAL_DB_PATH', base / 'matches.db')).expanduser()
    output = Path(os.getenv('VIRTUAL_AI_OVER25_MODEL_PATH', base / 'ai_brain_over25.pkl')).expanduser()
    samples = load_samples(db)
    if len(samples) < MINIMUM_MATCHES:
        raise ValueError(f'Need at least {MINIMUM_MATCHES} settled matches with valid odds and scores; found {len(samples)}.')
    # Chronological split; identical publication timestamps stay on the same side.
    cutoff = samples[int(len(samples) * 0.8)][2]
    train = [row for row in samples if row[2] < cutoff]
    holdout = [row for row in samples if row[2] >= cutoff]
    if len(train) < MINIMUM_MATCHES // 2 or len(holdout) < 200 or len({row[1] for row in train}) != 2:
        raise ValueError('Insufficient chronological training history or missing target class.')

    from sklearn.ensemble import HistGradientBoostingClassifier  # imported here so load_samples() runs without it

    def new_model():
        return HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05, max_leaf_nodes=15,
                                              min_samples_leaf=50, l2_regularization=1.0, random_state=89)

    model = new_model()
    model.fit([row[0] for row in train], [row[1] for row in train])
    accuracy = model.score([row[0] for row in holdout], [row[1] for row in holdout])
    base_rate = sum(row[1] == 'OVER' for row in holdout) / len(holdout)
    pick_rate, rounds = top_pick_rate(model, holdout)
    print(f'Training matches: {len(train)}; holdout matches: {len(holdout)}')
    print(f'Holdout accuracy: {accuracy:.1%} (always-majority baseline {max(base_rate, 1 - base_rate):.1%})')
    print(f'Holdout Over 2.5 rate, any match: {base_rate:.1%}')
    print(f'Holdout Over 2.5 rate, top pick of each round: {pick_rate:.1%} over {rounds} rounds')
    with_price = sum(not math.isnan(row[0][FEATURE_NAMES.index('over15_prob')]) for row in samples)
    print(f'Matches with an Over 1.5 price: {with_price} of {len(samples)}')
    print('Confidence is a model estimate, not a calibrated win guarantee.')

    final = new_model()
    final.fit([row[0] for row in samples], [row[1] for row in samples])
    package = {'model': final, 'target': TARGET, 'features': FEATURE_NAMES, 'training_rows': len(samples),
               'trained_through': samples[-1][2], 'holdout_accuracy': accuracy,
               'holdout_base_rate': base_rate, 'holdout_top_pick_rate': pick_rate}
    output.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=output.parent, suffix='.tmp')
    os.close(handle)
    try:
        joblib.dump(package, temporary)
        os.replace(temporary, output)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    print(f'Saved Over 2.5 model: {output}')


if __name__ == '__main__':
    main()
