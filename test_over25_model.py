import math
import sqlite3
import tempfile
import unittest
from pathlib import Path

import over25_model
from over25_model import TARGET, history_features, over15_probability, predict, recent_totals, total_goals
from train_model_over25 import load_samples

SCHEMA = """CREATE TABLE matches (id INTEGER PRIMARY KEY, home_team TEXT, away_team TEXT,
    home_odds REAL, draw_odds REAL, away_odds REAL, over_15_odds REAL, under_15_odds REAL,
    live_score TEXT, match_status TEXT, timestamp TEXT, week TEXT, website_round TEXT)"""


def same(a, b):
    return all((math.isnan(x) and math.isnan(y)) or x == y for x, y in zip(a, b)) and len(a) == len(b)


class FakeModel:
    classes_ = ['OVER', 'UNDER']

    def __init__(self):
        self.seen = None

    def predict_proba(self, rows):
        self.seen = rows[0]
        return [[0.64, 0.36]]


class Over25ModelTests(unittest.TestCase):
    def test_history_summaries(self):
        values = history_features([3, 1, 4, None], [], [2, 5])
        self.assertAlmostEqual(values[0], 8 / 3)          # home average goals, unusable score skipped
        self.assertAlmostEqual(values[1], 2 / 3)          # home share of 3+ goal games
        self.assertEqual(values[2], 3.0)
        self.assertTrue(math.isnan(values[3]) and math.isnan(values[4]) and values[5] == 0.0)
        self.assertEqual(values[6:], [3.5, 0.5, 2.0])     # past meetings
        self.assertEqual(len(history_features(list(range(30)), [], list(range(30)))), 9)
        self.assertEqual(history_features([3] * 30, [], [])[2], float(over25_model.TEAM_WINDOW))

    def test_over15_probability_and_scores(self):
        self.assertAlmostEqual(over15_probability(1.25, 3.75), 0.75)
        self.assertAlmostEqual(over15_probability(1.25, None), 0.8)
        self.assertTrue(math.isnan(over15_probability(0, 0)))
        self.assertEqual(total_goals('2 - 1'), 3)
        self.assertIsNone(total_goals('-'))

    def test_predict_returns_percent_and_rejects_other_packages(self):
        model = FakeModel()
        match = {'home_odds': 2.1, 'draw_odds': 3.4, 'away_odds': 3.3, 'over_15_odds': 1.3, 'under_15_odds': 3.2}
        self.assertAlmostEqual(predict({'model': model, 'target': TARGET}, match, [3], [1], []), 64.0)
        self.assertEqual(len(model.seen), len(over25_model.FEATURE_NAMES))
        self.assertIsNone(predict({'model': model, 'target': 'total_goals_over_1_5'}, match, [], [], []))
        self.assertIsNone(predict(None, match, [], [], []))
        self.assertIsNone(predict({'model': model, 'target': TARGET}, {**match, 'home_odds': 0}, [], [], []))

    def test_inputs_without_usable_values_are_dropped_and_predict_uses_the_same_columns(self):
        nan = float('nan')
        vectors = [[1.0, nan, 5.0, 2.0], [2.0, nan, 5.0, nan], [3.0, nan, 5.0, 4.0]]
        # Column 1 is missing everywhere (the Over 1.5 price before 14 November), column 2 never changes.
        self.assertEqual(over25_model.usable_columns(vectors), [0, 3])
        self.assertEqual(over25_model.select(vectors, [0, 3])[2], [3.0, 4.0])
        self.assertEqual(over25_model.usable_columns([]), [])
        model = FakeModel()
        match = {'home_odds': 2.1, 'draw_odds': 3.4, 'away_odds': 3.3}
        columns = [i for i, name in enumerate(over25_model.FEATURE_NAMES) if name != 'over15_prob']
        self.assertAlmostEqual(predict({'model': model, 'target': TARGET, 'columns': columns}, match, [3], [1], []), 64.0)
        self.assertEqual(len(model.seen), len(over25_model.FEATURE_NAMES) - 1)
        full = over25_model.features(match, [3], [1], [])
        self.assertTrue(same(model.seen, [full[i] for i in columns]))

    def test_training_and_live_inputs_match_and_never_see_the_result(self):
        rows = []
        teams = ['ARS', 'CHE', 'LIV', 'TOT']
        for index in range(40):
            home, away = teams[index % 4], teams[(index + 1 + index // 4) % 4]
            if home == away:
                away = teams[(index + 2) % 4]
            rows.append((index + 1, home, away, 2.0, 3.3, 3.6, 1.28 if index % 3 else None, 3.4 if index % 3 else None,
                         f'{index % 4} - {index % 3}', 'SETTLED', f'2026-11-01 08:{index:02d}:00', 'Wk 1', f'{index:032x}'))
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / 'matches.db'
            connection = sqlite3.connect(database)
            connection.execute(SCHEMA)
            connection.executemany('INSERT INTO matches VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)', rows)
            # The next fixture, not played yet: the live generator scores it from the 40 above.
            connection.execute("INSERT INTO matches VALUES (41,'ARS','LIV',1.9,3.4,3.9,1.3,3.3,'0 - 0','UPCOMING','2026-11-01 09:00:00','Wk 2',NULL)")
            connection.commit()
            live = recent_totals(connection.cursor(), 'ARS', 'LIV')
            live_vector = over25_model.features({'home_odds': 1.9, 'draw_odds': 3.4, 'away_odds': 3.9,
                                                 'over_15_odds': 1.3, 'under_15_odds': 3.3}, *live)
            # Once it is settled, the trainer must build the same inputs for it.
            connection.execute("UPDATE matches SET match_status='SETTLED', live_score='3 - 2' WHERE id=41")
            connection.commit()
            connection.close()
            samples = load_samples(database)
        self.assertEqual(len(samples), 41)
        self.assertTrue(same(samples[-1][0], live_vector))
        self.assertEqual(samples[-1][1], 'OVER')
        self.assertEqual(samples[0][0][-1], 0.0)  # the first match has no history at all
        self.assertEqual(samples[-1][3], 'Wk 2|2026-11-01 09:00:00')


if __name__ == '__main__':
    unittest.main()
