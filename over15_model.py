"""Dedicated total-goals model; never falls back to a BTTS prediction."""
import math


def features(home_odds, draw_odds, away_odds):
    odds = [float(home_odds), float(draw_odds), float(away_odds)]
    if any(not math.isfinite(value) or value <= 1 for value in odds):
        raise ValueError('Invalid pre-match odds')
    implied = [1 / value for value in odds]
    total = sum(implied)
    return odds + [value / total for value in implied] + [total]


def predict(package, match):
    if not package or package.get('target') != 'total_goals_over_1_5':
        return None
    try:
        values = features(match['home_odds'], match['draw_odds'], match['away_odds'])
        model = package['model']
        index = list(model.classes_).index('OVER')
        confidence = float(model.predict_proba([values])[0][index]) * 100
        return confidence if math.isfinite(confidence) and 0 <= confidence <= 100 else None
    except (ValueError, KeyError, TypeError, AttributeError):
        return None
