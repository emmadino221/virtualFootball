import sqlite3
import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import LabelEncoder
from sklearn.metrics import accuracy_score, classification_report
import warnings
import joblib

warnings.filterwarnings('ignore')

def load_and_sort_data():
    print("🔌 Connecting to database...")
    conn = sqlite3.connect("matches.db")
    # We load settled matches based on the actual_result being present
    query = """
        SELECT id, week, home_team, away_team, home_odds, draw_odds, away_odds, 
               actual_result, live_score, timestamp
        FROM matches 
        WHERE actual_result IS NOT NULL 
        AND actual_result IN ('HOME', 'DRAW', 'AWAY')
        ORDER BY id ASC
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    print(f"📊 Loaded {len(df)} historical matches.")
    return df

def calculate_rolling_form(df, window=3):
    print(f"⚙️ Engineering Rolling Form & GG/NG features (Looking at last {window} matches)...")
    
    # 1. Parse goals from the live_score column
    df['home_goals'] = df['live_score'].apply(lambda x: int(x.split('-')[0].strip()) if '-' in str(x) else 0)
    df['away_goals'] = df['live_score'].apply(lambda x: int(x.split('-')[1].strip()) if '-' in str(x) else 0)
    
    # 2. CREATE THE NEW TARGET VARIABLE: Goal Goal (GG) or No Goal (NG)
    df['actual_gg'] = np.where((df['home_goals'] > 0) & (df['away_goals'] > 0), 'GG', 'NG')
    
    # 3. Standard points calculation for form
    df['home_points'] = np.where(df['actual_result'] == 'HOME', 3, np.where(df['actual_result'] == 'DRAW', 1, 0))
    df['away_points'] = np.where(df['actual_result'] == 'AWAY', 3, np.where(df['actual_result'] == 'DRAW', 1, 0))
    
    history = []
    for idx, row in df.iterrows():
        history.append({'match_id': row['id'], 'team': row['home_team'], 'role': 'HOME', 'points': row['home_points'], 'goals_for': row['home_goals'], 'goals_against': row['away_goals']})
        history.append({'match_id': row['id'], 'team': row['away_team'], 'role': 'AWAY', 'points': row['away_points'], 'goals_for': row['away_goals'], 'goals_against': row['home_goals']})
    
    hist_df = pd.DataFrame(history)
    
    hist_df['past_pts'] = hist_df.groupby('team')['points'].transform(lambda x: x.shift(1).rolling(window, min_periods=1).sum())
    hist_df['past_gf'] = hist_df.groupby('team')['goals_for'].transform(lambda x: x.shift(1).rolling(window, min_periods=1).sum())
    hist_df['past_ga'] = hist_df.groupby('team')['goals_against'].transform(lambda x: x.shift(1).rolling(window, min_periods=1).sum())
    hist_df.fillna(0, inplace=True)
    
    home_hist = hist_df[hist_df['role'] == 'HOME'][['match_id', 'past_pts', 'past_gf', 'past_ga']].rename(columns={'match_id': 'id', 'past_pts': 'home_form_pts', 'past_gf': 'home_form_gf', 'past_ga': 'home_form_ga'})
    away_hist = hist_df[hist_df['role'] == 'AWAY'][['match_id', 'past_pts', 'past_gf', 'past_ga']].rename(columns={'match_id': 'id', 'past_pts': 'away_form_pts', 'past_gf': 'away_form_gf', 'past_ga': 'away_form_ga'})
    
    df = df.merge(home_hist, on='id').merge(away_hist, on='id')
    
    df['form_pts_diff'] = df['home_form_pts'] - df['away_form_pts']
    df['form_gd_diff'] = (df['home_form_gf'] - df['home_form_ga']) - (df['away_form_gf'] - df['away_form_ga'])
    
    df['prob_home'] = 1 / df['home_odds']
    df['prob_draw'] = 1 / df['draw_odds']
    df['prob_away'] = 1 / df['away_odds']
    df['overround'] = df['prob_home'] + df['prob_draw'] + df['prob_away']
    
    # Encode teams to numbers
    le = LabelEncoder()
    all_teams = pd.concat([df['home_team'], df['away_team']]).unique()
    le.fit(all_teams)
    df['home_team_id'] = le.transform(df['home_team'])
    df['away_team_id'] = le.transform(df['away_team'])
    
    return df, le

def train_and_evaluate(df, le):
    # Notice we include explicit Goals For (gf) and Goals Against (ga) features here, 
    # as they are highly relevant for predicting if both teams will score.
    features = [
        'home_team_id', 'away_team_id', 'home_odds', 'draw_odds', 'away_odds', 
        'prob_home', 'prob_draw', 'prob_away', 'overround',
        'home_form_pts', 'away_form_pts', 
        'home_form_gf', 'home_form_ga', 'away_form_gf', 'away_form_ga', 
        'form_pts_diff', 'form_gd_diff'
    ]
    
    X = df[features]
    # NEW TARGET
    y = df['actual_gg']
    
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, shuffle=False)
    print(f"🧠 Training GG/NG model on {len(X_train)} matches... (Testing on {len(X_test)} matches)")
    
    # We use a slightly different random state to ensure it initializes differently than the 1X2 model
    model = RandomForestClassifier(n_estimators=150, random_state=88, max_depth=6)
    model.fit(X_train, y_train)
    
    predictions = model.predict(X_test)
    accuracy = accuracy_score(y_test, predictions)
    
    print("\n" + "="*50)
    print(f"🎯 GG/NG AI MODEL ACCURACY: {accuracy * 100:.2f}%")
    print("="*50)
    
    print("\n💾 Exporting GG/NG AI Brain...")
    ai_package = {
        'model': model,
        'encoder': le,
        'features': features 
    }
    # EXPORT AS A SEPARATE FILE
    joblib.dump(ai_package, 'ai_brain_gg.pkl')
    print("✅ Successfully created 'ai_brain_gg.pkl' in your folder!")

if __name__ == "__main__":
    df = load_and_sort_data()
    
    if len(df) < 60:
        print("⚠️ WARNING: Keep your scraper running until you hit 100+ entries.")
    else:
        df, le = calculate_rolling_form(df, window=3)
        train_and_evaluate(df, le)