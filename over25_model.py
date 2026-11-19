"""Over 2.5 goals model: three or more goals in the match.

Inputs, per match:
- the 1X2 odds (home, draw, away), as raw prices and as normalised probabilities;
- the Over/Under 1.5 price, as the bookmaker's probability of two or more goals;
- each team's recent record: average total goals and the share of games with 3+ goals;
- the two teams' past meetings: the same two numbers.

Missing inputs (no Over 1.5 price, a team with no history yet, teams that have not met)
are passed as NaN, which the gradient-boosting model handles directly.

Training (train_model_over25.py) and live prediction (new.py) both build the history
inputs with history_features(), so the model sees the same numbers in both places.
"""
import math
import re

from over15_model import features as odds_features

TARGET = 'total_goals_over_2_5'
TEAM_WINDOW = 10     # each team's last 10 finished matches
MEETING_WINDOW = 5   # the two teams' last 5 meetings, in either venue
NAN = float('nan')

FEATURE_NAMES = [
    'home_odds', 'draw_odds', 'away_odds', 'home_prob', 'draw_prob', 'away_prob', 'overround',
    'over15_prob',
    'home_team_avg_goals', 'home_team_over25_rate', 'home_team_games',
    'away_team_avg_goals', 'away_team_over25_rate', 'away_team_games',
    'meeting_avg_goals', 'meeting_over25_rate', 'meetings',
]


def total_goals(score):
    """Total goals from a 'H - A' score, or None when the score is not usable."""
    parsed = re.fullmatch(r'\s*(\d{1,2})\s*-\s*(\d{1,2})\s*', str(score or ''))
    return sum(map(int, parsed.groups())) if parsed else None


def over15_probability(over_odds, under_odds):
    """Bookmaker's chance of two or more goals, with the margin removed when both prices exist."""
    try:
        over, under = float(over_odds or 0), float(under_odds or 0)
    except (TypeError, ValueError):
        return NAN
    if over > 1 and under > 1:
        return (1 / over) / (1 / over + 1 / under)
    return 1 / over if over > 1 else NAN


def _summary(totals, window):
    recent = [value for value in totals if value is not None][:window]
    if not recent:
        return [NAN, NAN, 0.0]
    return [sum(recent) / len(recent), sum(value >= 3 for value in recent) / len(recent), float(len(recent))]


def history_features(home_totals, away_totals, meeting_totals):
    """Each argument lists total goals of past finished matches, newest first."""
    return (_summary(home_totals, TEAM_WINDOW) + _summary(away_totals, TEAM_WINDOW)
            + _summary(meeting_totals, MEETING_WINDOW))


def features(match, home_totals, away_totals, meeting_totals):
    values = odds_features(match['home_odds'], match['draw_odds'], match['away_odds'])
    values.append(over15_probability(match.get('over_15_odds'), match.get('under_15_odds')))
    return values + history_features(home_totals, away_totals, meeting_totals)


def predict(package, match, home_totals, away_totals, meeting_totals):
    """Over 2.5 confidence in percent, or None when the model or the odds are unusable."""
    if not package or package.get('target') != TARGET:
        return None
    try:
        values = features(match, home_totals, away_totals, meeting_totals)
        # The trainer drops inputs that had no usable values (see usable_columns).
        values = [values[i] for i in package.get('columns', range(len(values)))]
        model = package['model']
        index = list(model.classes_).index('OVER')
        confidence = float(model.predict_proba([values])[0][index]) * 100
        return confidence if math.isfinite(confidence) and 0 <= confidence <= 100 else None
    except (ValueError, KeyError, TypeError, AttributeError):
        return None


def usable_columns(vectors):
    """Indices of inputs with at least two distinct known values.

    A column that is missing everywhere (the Over 1.5 price before it was collected) or
    never changes gives the model nothing to learn, and the gradient-boosting binning step
    fails on it, so it is left out of training and prediction.
    """
    columns = []
    for index in range(len(vectors[0]) if vectors else 0):
        known = {row[index] for row in vectors if not math.isnan(row[index])}
        if len(known) >= 2:
            columns.append(index)
    return columns


def select(vectors, columns):
    return [[row[i] for i in columns] for row in vectors]


def recent_totals(cursor, home_team, away_team):
    """Live lookup of the history inputs from the generator's database, newest first."""
    def team(name):
        rows = cursor.execute(
            "SELECT live_score FROM matches WHERE (home_team = ? OR away_team = ?) AND match_status = 'SETTLED' "
            "ORDER BY id DESC LIMIT ?", (name, name, TEAM_WINDOW)).fetchall()
        return [total_goals(row[0]) for row in rows]
    meetings = cursor.execute(
        "SELECT live_score FROM matches WHERE ((home_team = ? AND away_team = ?) OR (home_team = ? AND away_team = ?)) "
        "AND match_status = 'SETTLED' ORDER BY id DESC LIMIT ?",
        (home_team, away_team, away_team, home_team, MEETING_WINDOW)).fetchall()
    return team(home_team), team(away_team), [total_goals(row[0]) for row in meetings]
