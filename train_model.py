import sqlite3
import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import LabelEncoder
from sklearn.metrics import accuracy_score, classification_report
import warnings
import joblib  # <-- NEW: For saving the AI

warnings.filterwarnings('ignore')

def load_and_sort_data():
    print("🔌 Connecting to database...")
    conn = sqlite3.connect("matches.db")
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
    print(f"⚙️ Engineering Rolling Form features (Looking at last {window} matches)...")
    
    df['home_goals'] = df['live_score'].apply(lambda x: int(x.split('-')[0].strip()) if '-' in str(x) else 0)
    df['away_goals'] = df['live_score'].apply(lambda x: int(x.split('-')[1].strip()) if '-' in str(x) else 0)
    
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
    
    # We must save the EXACT encoder used to train the AI
    le = LabelEncoder()
    all_teams = pd.concat([df['home_team'], df['away_team']]).unique()
    le.fit(all_teams)
    df['home_team_id'] = le.transform(df['home_team'])
    df['away_team_id'] = le.transform(df['away_team'])
    
    return df, le  # <-- Returning the encoder so we can save it

def train_and_evaluate(df, le):
    features = [
        'home_team_id', 'away_team_id', 'home_odds', 'draw_odds', 'away_odds', 
        'prob_home', 'prob_draw', 'prob_away', 'overround',
        'home_form_pts', 'away_form_pts', 'form_pts_diff', 'form_gd_diff'
    ]
    
    X = df[features]
    y = df['actual_result']
    
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, shuffle=False)
    print(f"🧠 Training model on {len(X_train)} matches... (Testing on {len(X_test)} matches)")
    
    model = RandomForestClassifier(n_estimators=150, random_state=42, max_depth=6)
    model.fit(X_train, y_train)
    
    predictions = model.predict(X_test)
    accuracy = accuracy_score(y_test, predictions)
    
    print("\n" + "="*50)
    print(f"🎯 UPGRADED AI MODEL ACCURACY: {accuracy * 100:.2f}%")
    print("="*50)
    
    # ==========================================================
    # NEW: EXPORT THE AI BRAIN TO A FILE
    # ==========================================================
    print("\n💾 Exporting AI Brain for the live scraper...")
    # We package the model and the encoder together
    ai_package = {
        'model': model,
        'encoder': le,
        'features': features # Save the exact order of features the AI expects
    }
    joblib.dump(ai_package, 'ai_brain.pkl')
    print("✅ Successfully created 'ai_brain.pkl' in your folder!")

if __name__ == "__main__":
    df = load_and_sort_data()
    
    if len(df) < 60:
        print("⚠️ WARNING: Keep your scraper running until you hit 100+ entries.")
    else:
        df, le = calculate_rolling_form(df, window=3)
        train_and_evaluate(df, le)