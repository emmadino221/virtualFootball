"""Train explicitly with: python train_model_over15.py. Does not start the collector."""
import os
from pathlib import Path
import re
import sqlite3
import tempfile

import joblib
from dotenv import load_dotenv
from sklearn.ensemble import RandomForestClassifier
from over15_model import features


def main():
    base = Path(__file__).resolve().parent
    load_dotenv(base / '.env')
    db = Path(os.getenv('VIRTUAL_DB_PATH', base / 'matches.db')).expanduser()
    output = Path(os.getenv('VIRTUAL_AI_OVER15_MODEL_PATH', base / 'ai_brain_over15.pkl')).expanduser()
    with sqlite3.connect(db.resolve().as_uri() + '?mode=ro', uri=True) as connection:
        rows = connection.execute("""SELECT home_odds, draw_odds, away_odds, live_score,
            timestamp FROM matches WHERE match_status='SETTLED'
            AND actual_result IN ('HOME','DRAW','AWAY') ORDER BY timestamp, id""").fetchall()
    samples = []
    for home, draw, away, score, timestamp in rows:
        parsed = re.fullmatch(r'\s*(\d{1,2})\s*-\s*(\d{1,2})\s*', str(score))
        if not parsed or not timestamp:
            continue
        try:
            vector = features(home, draw, away)
        except (ValueError, TypeError):
            continue
        label = 'OVER' if sum(map(int, parsed.groups())) >= 2 else 'UNDER'
        samples.append((vector, label, timestamp))
    if len(samples) < 200:
        raise ValueError('Need at least 200 settled matches with valid odds and scores.')
    # Keep identical publication timestamps together across the chronological split.
    cutoff = samples[int(len(samples) * 0.8)][2]
    train = [row for row in samples if row[2] < cutoff]
    holdout = [row for row in samples if row[2] >= cutoff]
    if len(train) < 100 or len(holdout) < 20 or len({row[1] for row in train}) != 2:
        raise ValueError('Insufficient chronological training history or missing target class.')
    model = RandomForestClassifier(n_estimators=150, max_depth=6, min_samples_leaf=10, random_state=89, n_jobs=1)
    model.fit([row[0] for row in train], [row[1] for row in train])
    accuracy = model.score([row[0] for row in holdout], [row[1] for row in holdout])
    print(f'Chronological holdout accuracy: {accuracy:.1%}; holdout matches: {len(holdout)}')
    print(f'Holdout always-Over baseline: {sum(row[1] == "OVER" for row in holdout) / len(holdout):.1%}')
    print('Confidence is a model estimate, not a calibrated win guarantee.')
    model.fit([row[0] for row in samples], [row[1] for row in samples])
    package = {'model': model, 'target': 'total_goals_over_1_5', 'training_rows': len(samples),
               'trained_through': samples[-1][2], 'holdout_accuracy': accuracy}
    output.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=output.parent, suffix='.tmp')
    os.close(handle)
    try:
        joblib.dump(package, temporary)
        os.replace(temporary, output)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    print(f'Saved dedicated Over 1.5 model: {output}')


if __name__ == '__main__':
    main()
