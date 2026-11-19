import os
import sqlite3
import tempfile
import unittest
from contextlib import closing

from bet_scores import attach_scores
from ext_sessions import clean_state


class BetScoreTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.dir.name, "matches.db")
        with closing(sqlite3.connect(self.db)) as db:
            db.execute("""CREATE TABLE matches (id INTEGER PRIMARY KEY, home_team TEXT, away_team TEXT, live_score TEXT,
                match_status TEXT, website_round TEXT, website_markets TEXT)""")
            db.executemany("INSERT INTO matches (home_team, away_team, live_score, match_status, website_round, website_markets) VALUES (?,?,?,?,?,?)", [
                ("ARS", "CHE", "2 - 1", "SETTLED", "r1", '["over", "over25"]'),
                ("LIV", "TOT", "0 - 0", "SETTLED", "r1", '["over"]'),
                ("EVE", "FUL", "1 - 1", "SETTLED", "r1", '["under"]'),
                ("BOU", "NWC", "0 - 0", "UPCOMING", "r2", '["over25"]'),
            ])
            db.commit()

    def tearDown(self):
        self.dir.cleanup()

    def test_picks_get_their_final_score(self):
        bets = [{"roundId": "r1", "mode": "O25", "picks": [{"home": "ARS", "away": "CHE", "pick": "Over 2.5"}], "outcome": "WIN"}]
        [bet] = attach_scores(bets, self.db)
        self.assertEqual(bet["picks"][0]["score"], "2 - 1")
        self.assertTrue(bet["picks"][0]["finished"])
        self.assertNotIn("score", bets[0]["picks"][0])          # the input is not changed

    def test_bets_without_picks_use_the_round_s_published_matches(self):
        [bet] = attach_scores([{"roundId": "r1", "mode": "OU"}], self.db)
        self.assertEqual([(p["home"], p["score"]) for p in bet["picks"]], [("ARS", "2 - 1"), ("LIV", "0 - 0")])
        [bet] = attach_scores([{"roundId": "r1", "mode": "O25"}], self.db)
        self.assertEqual([p["home"] for p in bet["picks"]], ["ARS"])   # "over" does not match "over25"

    def test_unfinished_and_unknown_rounds(self):
        [pending] = attach_scores([{"roundId": "r2", "mode": "O25", "picks": [{"home": "BOU", "away": "NWC"}]}], self.db)
        self.assertIsNone(pending["picks"][0]["score"])
        self.assertFalse(pending["picks"][0]["finished"])
        [missing] = attach_scores([{"roundId": "gone", "mode": "OU", "picks": []}], self.db)
        self.assertEqual(missing["picks"], [])
        self.assertEqual(attach_scores([{"roundId": "r1"}], os.path.join(self.dir.name, "absent.db"))[0], {"roundId": "r1"})

    def test_reported_history_is_cleaned(self):
        state = clean_state({"betHistory": [
            {"stake": 300, "odds": 1.9, "mode": "O25", "roundId": "r1", "week": "Week 3", "outcome": "WIN", "profit": 270,
             "picks": [{"home": "ARS", "away": "CHE", "pick": "Over 2.5"}, {"home": "<b>", "away": None}], "settledAt": 1},
            {"stake": "abc"}, {"stake": 100, "outcome": "MAYBE"}] + [{"stake": 1}] * 40,
            "pendingBet": {"stake": 200, "mode": "OU", "picks": [{"home": "LIV", "away": "TOT"}]}})
        self.assertEqual(len(state["betHistory"]), 30)
        first = state["betHistory"][0]
        self.assertEqual((first["outcome"], first["profit"], first["odds"]), ("WIN", 270.0, 1.9))
        self.assertEqual(first["picks"], [{"home": "ARS", "away": "CHE", "pick": "Over 2.5"}])
        self.assertEqual(state["betHistory"][1]["outcome"], "UNKNOWN")
        self.assertNotIn("outcome", state["pendingBet"])
        self.assertEqual(state["pendingBet"]["picks"][0]["home"], "LIV")


if __name__ == "__main__":
    unittest.main()
