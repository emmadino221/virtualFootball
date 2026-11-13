"""GG/NG model that uses only the pre-match 1X2 odds.

On 90,620 settled matches (13 November 2026) the older GG/NG model, which also
uses team names and recent form, picked NG winners 47.3% of the time. A model
on the odds alone picked them about 54% of the time on unseen matches, and GG
about 57% against 55.3%. See evaluate_models.py.
"""
import math

from over15_model import features

TARGET = 'btts_gg_from_odds'


def predict(package, match):
    """Chance in percent that both teams score, or None when no model is usable."""
    if not package or package.get('target') != TARGET:
        return None
    try:
        values = features(match['home_odds'], match['draw_odds'], match['away_odds'])
        model = package['model']
        index = list(model.classes_).index('GG')
        chance = float(model.predict_proba([values])[0][index]) * 100
        return chance if math.isfinite(chance) and 0 <= chance <= 100 else None
    except (ValueError, KeyError, TypeError, AttributeError):
        return None
