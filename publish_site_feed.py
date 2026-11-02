import hashlib
import hmac
import json
import logging
import os
from datetime import datetime
from pathlib import Path
import re
import sqlite3
import time

import requests


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("VIRTUAL_DB_PATH", BASE_DIR / "matches.db")).expanduser()
FEED_URL = os.getenv("VIRTUAL_FEED_URL", "")
FEED_SECRET = os.getenv("VIRTUAL_FEED_SECRET", "")
SOURCE_ID = os.getenv("VIRTUAL_FEED_SOURCE_ID", "virtualfootball")
PUBLISH_INTERVAL_SECONDS = int(os.getenv("VIRTUAL_FEED_INTERVAL_SECONDS", "10"))


def timestamp_ms(value):
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as error:
        raise ValueError("A virtual match has an invalid timestamp.") from error
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return int(parsed.timestamp() * 1000)


def build_snapshot(db_path=DB_PATH, source_id=SOURCE_ID, source_at=None):
    connection = sqlite3.connect(db_path, timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """SELECT id, home_team, away_team, week, prediction, prediction_gg,
                      confidence, timestamp, match_status, live_score
               FROM matches
               WHERE is_shortlisted = 1
               ORDER BY id DESC
               LIMIT 200"""
        ).fetchall()
    finally:
        connection.close()

    matches = []
    for row in rows:
        status = "REPORTED" if str(row["match_status"] or "").upper() == "SETTLED" else "UPCOMING"
        pick = str(row["prediction"] or "").upper()
        btts = str(row["prediction_gg"] or "").upper()
        confidence = row["confidence"]
        matches.append({
            "id": int(row["id"]),
            "home": str(row["home_team"] or ""),
            "away": str(row["away_team"] or ""),
            "week": str(row["week"] or ""),
            "createdAt": timestamp_ms(row["timestamp"]),
            "pick": pick if pick in {"HOME", "DRAW", "AWAY"} else None,
            "btts": btts if btts in {"GG", "NG"} else None,
            "confidence": float(confidence) if confidence is not None else None,
            "status": status,
            "score": row["live_score"] if status == "REPORTED" else None,
        })

    return {
        "version": 1,
        "sourceId": source_id,
        "sourceAt": source_at if source_at is not None else int(time.time() * 1000),
        "matches": matches,
    }


def publish_snapshot(snapshot):
    timestamp = str(int(time.time() * 1000))
    body = json.dumps(snapshot, separators=(",", ":"), ensure_ascii=False)
    signature = hmac.new(
        FEED_SECRET.encode("utf-8"),
        f"{timestamp}.{body}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    response = requests.post(
        FEED_URL,
        data=body.encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-Virtual-Timestamp": timestamp,
            "X-Virtual-Signature": signature,
        },
        timeout=15,
    )
    response.raise_for_status()
    result = response.json()
    if not result.get("ok"):
        raise ValueError("The website rejected the virtual football snapshot.")
    logging.info("Published %s virtual matches.", result.get("received", 0))


def main():
    if not FEED_URL.startswith("https://"):
        raise ValueError("VIRTUAL_FEED_URL must use HTTPS.")
    if len(FEED_SECRET) < 32:
        raise ValueError("VIRTUAL_FEED_SECRET must be at least 32 characters.")
    if not re.fullmatch(r"[a-zA-Z0-9_-]{8,64}", SOURCE_ID):
        raise ValueError("VIRTUAL_FEED_SOURCE_ID must be 8-64 letters, numbers, '_' or '-'.")
    if PUBLISH_INTERVAL_SECONDS < 10:
        raise ValueError("VIRTUAL_FEED_INTERVAL_SECONDS must be at least 10.")

    while True:
        try:
            publish_snapshot(build_snapshot())
        except (OSError, sqlite3.Error, requests.RequestException, ValueError) as error:
            logging.exception("Could not publish virtual football feed: %s", error)
        time.sleep(PUBLISH_INTERVAL_SECONDS)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    main()
