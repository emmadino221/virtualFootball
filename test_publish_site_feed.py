import hashlib
import hmac
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import publish_site_feed
from publish_site_feed import build_snapshot


class BuildSnapshotTests(unittest.TestCase):
    def test_publishes_shortlisted_picks_and_settled_scores(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "matches.db"
            connection = sqlite3.connect(database)
            connection.execute(
                """CREATE TABLE matches (
                    id INTEGER PRIMARY KEY, home_team TEXT, away_team TEXT, week TEXT,
                    prediction TEXT, prediction_gg TEXT, confidence REAL, timestamp TEXT,
                    match_status TEXT, live_score TEXT, is_shortlisted INTEGER
                )"""
            )
            connection.executemany(
                "INSERT INTO matches VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                [
                    (1, "HOME", "AWAY", "Week 1", "HOME", "GG", 75.5,
                     "2026-11-01 08:00:00", "UPCOMING", "0 - 0", 1),
                    (2, "Old", "Match", "Week 1", "DRAW", "NG", 60,
                     "2026-11-01 07:00:00", "UPCOMING", "0 - 0", 0),
                    (3, "Reported", "Game", "Week 1", "AWAY", "NG", 83,
                     "2026-11-01 08:01:00", "SETTLED", "1 - 2", 1),
                ],
            )
            connection.commit()
            connection.close()

            snapshot = build_snapshot(database, source_at=1793510400000)

        self.assertEqual(snapshot["version"], 1)
        self.assertEqual(snapshot["sourceId"], "virtualfootball")
        self.assertEqual(snapshot["sourceAt"], 1793510400000)
        self.assertEqual([match["id"] for match in snapshot["matches"]], [3, 1])
        self.assertEqual(snapshot["matches"][0]["status"], "REPORTED")
        self.assertEqual(snapshot["matches"][0]["score"], "1 - 2")
        self.assertEqual(snapshot["matches"][0]["pick"], "AWAY")
        self.assertEqual(snapshot["matches"][1]["confidence"], 75.5)

    def test_rejects_bad_match_timestamps(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "matches.db"
            connection = sqlite3.connect(database)
            connection.execute(
                """CREATE TABLE matches (
                    id INTEGER PRIMARY KEY, home_team TEXT, away_team TEXT, week TEXT,
                    prediction TEXT, prediction_gg TEXT, confidence REAL, timestamp TEXT,
                    match_status TEXT, live_score TEXT, is_shortlisted INTEGER
                )"""
            )
            connection.execute(
                "INSERT INTO matches VALUES (1,'A','B','Week','HOME','GG',50,'bad','UPCOMING','0 - 0',1)"
            )
            connection.commit()
            connection.close()

            with self.assertRaisesRegex(ValueError, "invalid timestamp"):
                build_snapshot(database)

    @patch("publish_site_feed.requests.post")
    def test_signs_the_exact_snapshot_body(self, post):
        response = post.return_value
        response.json.return_value = {"ok": True, "received": 1}
        publish_site_feed.FEED_URL = "https://example.test/internal/virtual-football-snapshot"
        publish_site_feed.FEED_SECRET = "test-secret-with-more-than-thirty-two-characters"
        snapshot = {"version": 1, "sourceId": "virtualfootball", "sourceAt": 1, "matches": []}

        publish_site_feed.publish_snapshot(snapshot)

        _, request = post.call_args
        timestamp = request["headers"]["X-Virtual-Timestamp"]
        body = request["data"].decode("utf-8")
        expected = hmac.new(
            publish_site_feed.FEED_SECRET.encode("utf-8"),
            f"{timestamp}.{body}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        self.assertEqual(json.loads(body), snapshot)
        self.assertEqual(request["headers"]["X-Virtual-Signature"], expected)


if __name__ == "__main__":
    unittest.main()
