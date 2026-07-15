from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from dotenv import load_dotenv

import sqlite3
import time
import os
import re
import requests
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import joblib
import numpy as np

# ==============================================================================
# CONFIGURATION & INITIAL AI LOADING
# ==============================================================================
load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

if not TOKEN or not CHAT_ID:
    raise ValueError("Missing Telegram credentials. Check your .env file.")

MATCHES_PER_SHORTLIST = 3

print("⏳ Loading initial AI Brain...")
try:
    ai_package = joblib.load('ai_brain.pkl')
    ai_model = ai_package['model']
    ai_encoder = ai_package['encoder']
    print("🧠 AI Brain loaded and ready to predict!")
except Exception as e:
    print(f"⚠️ CRITICAL: Could not load 'ai_brain.pkl'. Did you run train_model.py? Error: {e}")
    exit()

TEAM_SHIRT_COLORS = {
    "ASV": "🟩", "LEE": "🟦", "TOT": "⚪", "EVE": "🔵", "NWC": "🟧",
    "BOU": "🟡", "CHE": "🔵", "FUL": "⚫", "BRI": "🔵", "FOR": "🟤",
}

def team_shirt(team): return TEAM_SHIRT_COLORS.get(team, "👕")

def wait_for_page_ready(timeout=4):
    WebDriverWait(driver, timeout).until(lambda d: d.execute_script("return document.readyState") == "complete")
    time.sleep(0.3)

def switch_to_iframe_if_present(timeout=3):
    try:
        iframe = WebDriverWait(driver, timeout).until(EC.presence_of_element_located((By.TAG_NAME, "iframe")))
        driver.switch_to.frame(iframe)
        return True
    except Exception: return False

def wait_for_match_rows(timeout=2):
    try:
        WebDriverWait(driver, timeout).until(lambda d: len(d.find_elements(By.TAG_NAME, "tr")) >= 3)
        return True
    except Exception: return False

def normalize_team_name(name): return re.sub(r'[^A-Za-z0-9]', '', name).strip().upper()
def normalize_week_key(wl):
    if not wl: return "N/A"
    m = re.search(r'(\d+)', str(wl).strip())
    return f"WK{int(m.group(1))}" if m else re.sub(r'[^A-Za-z0-9]+', '', str(wl)).upper() or "N/A"

def teams_match(target, parsed):
    th, ta = normalize_team_name(target.get("home_team", "")), normalize_team_name(target.get("away_team", ""))
    ph, pa = normalize_team_name(parsed.get("home_team", "")), normalize_team_name(parsed.get("away_team", ""))
    if not th or not ta or not ph or not pa: return False
    return (th == ph and ta == pa) or (th == pa and ta == ph)

def get_result_from_score(h, a): return "HOME" if h > a else "AWAY" if a > h else "DRAW"
def calculate_total_goals(score_str):
    try:
        h, a = map(int, score_str.replace(" ", "").split("-"))
        return h + a
    except: return 0

# ==============================================================================
# CLOUD & NETWORK WRAPPERS
# ==============================================================================
def safe_request(url, payload, max_retries=3):
    for _ in range(max_retries):
        try: return requests.post(url, json=payload, timeout=15).json()
        except requests.exceptions.RequestException: time.sleep(5)
    return {}

def safe_google_export(week, shortlisted_targets, stats, all_targets, max_retries=3):
    for attempt in range(max_retries):
        try:
            scope = ["https://spreadsheets.google.com/feeds", 'https://www.googleapis.com/auth/spreadsheets', "https://www.googleapis.com/auth/drive.file", "https://www.googleapis.com/auth/drive"]
            creds = ServiceAccountCredentials.from_json_keyfile_name('credentials.json', scope)
            client = gspread.authorize(creds)
            
            sheet1 = client.open("VirtualFootballResults").worksheet("Sheet1")
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            rows1 = [[ts, week, t["home_team"], t["away_team"], t["prediction"], t["prediction_ou"], t["home_odds"], t["draw_odds"], t["away_odds"], t.get("final_score", "0 - 0"), t.get("status", "WRONG"), t.get("ou_status", "WRONG"), stats["acca_1x2"], stats["acca_ou"], f"{stats['win_rate_1x2']}%", stats["max_streak_1x2"], f"{stats['win_rate_ou']}%", stats["max_streak_ou"]] for t in shortlisted_targets]
            sheet1.append_rows(rows1)
            
            sheet2 = client.open("VirtualFootballResults").worksheet("LeagueData")
            rows2 = []
            for t in all_targets:
                try: hg, ag = map(int, t.get("final_score", "0 - 0").replace(" ", "").split("-"))
                except: hg, ag = 0, 0
                rows2.append([week, t["home_team"], t["away_team"], hg, ag, "H Win" if hg>ag else "H Loss" if ag>hg else "H Draw", "A Win" if ag>hg else "A Loss" if hg>ag else "A Draw"])
            sheet2.append_rows(rows2)
            print(f"☁️ Cloud Sync Complete: AI Top 3 to Sheet1 | All to LeagueData.")
            return
        except Exception as e:
            print(f"⚠️ Sheets Error (Attempt {attempt+1}): {e}")
            time.sleep(5)

# ==============================================================================
# TELEGRAM
# ==============================================================================
def send_telegram_message(text):
    data = safe_request(f"https://api.telegram.org/bot{TOKEN}/sendMessage", {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"})
    return data["result"]["message_id"] if data and data.get("ok") else None

def build_shortlist_message(week, matches):
    lines = [f"<b>🤖 AI TARGETS | Week: {week}</b>\n"]
    lines.append("<b>🏆 1X2 PREDICTIONS</b>")
    for i, m in enumerate(matches, 1):
        lines.append(f"{i}. {team_shirt(m['home_team'])}{m['home_team']} vs {team_shirt(m['away_team'])}{m['away_team']} — Pick: <b>{m['prediction']}</b> (AI: {m['ai_confidence']:.1f}%)")
    lines.append("\n<b>⚽ GOALS (OVER 1.5)</b>")
    for i, m in enumerate(matches, 1):
        lines.append(f"{i}. {team_shirt(m['home_team'])}{m['home_team']} vs {team_shirt(m['away_team'])}{m['away_team']} — Pick: <b>Over 1.5</b>")
    lines.append("\n<b>Status:</b> 🟡 <b>PENDING</b>")
    return "\n".join(lines)

def send_or_update_shortlist(msg_id, week, matches):
    text = build_shortlist_message(week, matches)
    if msg_id:
        data = safe_request(f"https://api.telegram.org/bot{TOKEN}/editMessageText", {"chat_id": CHAT_ID, "message_id": msg_id, "text": text, "parse_mode": "HTML"})
        if data and data.get("ok"): return msg_id
    return send_telegram_message(text)

def update_telegram_settlement(msg_id, week, matches):
    lines = [f"<b>🏁 MATCH RESULTS | Week: {week}</b>\n"]
    lines.append("<b>🏆 1X2 RESULTS</b>")
    for m in matches:
        st = "✅" if m.get("status") == "CORRECT" else "❌" if m.get("status") == "WRONG" else "🟡"
        lines.append(f"{st} {m['home_team']} vs {m['away_team']} ({m.get('final_score', 'PENDING')}) — {m.get('prediction')}")
    lines.append("\n<b>⚽ OVER 1.5 RESULTS</b>")
    for m in matches:
        st = "✅" if m.get("ou_status") == "CORRECT" else "❌" if m.get("ou_status") == "WRONG" else "🟡"
        lines.append(f"{st} {m['home_team']} vs {m['away_team']} ({m.get('final_score', 'PENDING')})")
    safe_request(f"https://api.telegram.org/bot{TOKEN}/editMessageText", {"chat_id": CHAT_ID, "message_id": msg_id, "text": "\n".join(lines), "parse_mode": "HTML"})

# ==============================================================================
# JS SCRAPERS & AI FEATURE ENGINE
# ==============================================================================
def get_live_scores_js():
    js = r"""const res=[];const hs=document.querySelectorAll('span[id^="goal_team_A_"]');for(const h of hs){try{const i=h.id.replace('goal_team_A_','');const a=document.getElementById('goal_team_B_'+i);if(!a)continue;const hc=parseInt(h.textContent.trim(),10);const ac=parseInt(a.textContent.trim(),10);if(isNaN(hc)||isNaN(ac))continue;const hr=h.closest('tr');const ar=a.closest('tr');const et=(r)=>{const tds=r.querySelectorAll('td');for(const td of tds){const txt=td.textContent.trim();if(/^[A-Z]{2,4}$/.test(txt))return txt;}return null;};const ht=et(hr);const at=et(ar);if(!ht||!at)continue;const mc=hr.closest('table').parentElement.parentElement||document.body;const f=/\b(FT|FINISHED|FULL\s*TIME|ENDED)\b/i.test(mc.textContent);res.push({home_team:ht,away_team:at,home_score:hc,away_score:ac,is_finished:f});}catch(e){}}return res;"""
    try: return driver.execute_script(js) or []
    except: return []

def extract_raw_odds_js():
    js = r"""const rows=document.querySelectorAll('tr');const res=[];for(const r of rows){if(r.offsetParent===null)continue;const c=r.querySelectorAll('input.checkbox_bets');if(c.length<3)continue;const ho=parseFloat(c[0].value);const doo=parseFloat(c[1].value);const ao=parseFloat(c[2].value);if(!(ho>0&&doo>0&&ao>0))continue;let tn=[];const b=r.querySelectorAll('td div.badge-market.w-30');for(const s of b){const t=s.textContent.trim();if(t&&t!=='-')tn.push(t);}if(tn.length<2){tn=[];const alt=r.querySelectorAll('td .badge-market');for(const s of alt){const t=s.textContent.trim();if(t&&t!=='-')tn.push(t);}}if(tn.length<2){tn=[];const d=r.querySelectorAll('div');for(const di of d){const t=di.textContent.trim();if(t.length>0&&t.length<=4&&t===t.toUpperCase()&&t!=='-')tn.push(t);}}if(tn.length>=2)res.push({home_team:tn[0],away_team:tn[1],home_odds:ho,draw_odds:doo,away_odds:ao});}return res;"""
    try: return driver.execute_script(js) or []
    except: return []

def calculate_dynamic_form(team_name, db_cursor, window=3):
    db_cursor.execute("SELECT home_team, actual_result, live_score FROM matches WHERE (home_team = ? OR away_team = ?) AND match_status = 'SETTLED' ORDER BY id DESC LIMIT ?", (team_name, team_name, window))
    rows = db_cursor.fetchall()
    pts, gf, ga = 0, 0, 0
    for h_team, res, score in rows:
        try: hg, ag = map(int, score.replace(" ", "").split("-"))
        except: continue
        if team_name == h_team:
            pts += 3 if res == 'HOME' else (1 if res == 'DRAW' else 0)
            gf += hg; ga += ag
        else:
            pts += 3 if res == 'AWAY' else (1 if res == 'DRAW' else 0)
            gf += ag; ga += hg
    return pts, gf, ga

def predict_with_ai(raw_matches):
    predicted = []
    seen = set()
    for m in raw_matches:
        ht, at = m["home_team"], m["away_team"]
        if (ht, at) in seen: continue
        seen.add((ht, at))
        ho, do, ao = float(m["home_odds"]), float(m["draw_odds"]), float(m["away_odds"])
        ph, pd, pa = 1/ho, 1/do, 1/ao
        ovr = ph + pd + pa
        
        try:
            h_id = ai_encoder.transform([ht])[0]
            a_id = ai_encoder.transform([at])[0]
        except ValueError: h_id, a_id = 0, 0 
            
        h_pts, h_gf, h_ga = calculate_dynamic_form(ht, cursor)
        a_pts, a_gf, a_ga = calculate_dynamic_form(at, cursor)
        pts_diff = h_pts - a_pts
        gd_diff = (h_gf - h_ga) - (a_gf - a_ga)
        
        features = [[h_id, a_id, ho, do, ao, ph, pd, pa, ovr, h_pts, a_pts, pts_diff, gd_diff]]
        
        try:
            pred_class = ai_model.predict(features)[0]
            pred_probs = ai_model.predict_proba(features)[0]
            class_idx = list(ai_model.classes_).index(pred_class)
            confidence = pred_probs[class_idx] * 100
        except Exception as e:
            print(f"AI Error: {e}")
            pred_class, confidence = "HOME", 33.3
            
        predicted.append({
            "home_team": ht, "away_team": at, "home_odds": ho, "draw_odds": do, "away_odds": ao,
            "prediction": pred_class, "prediction_ou": "OVER 1.5", "ai_confidence": confidence,
            "settled": False, "last_known_score": "0 - 0"
        })
        
    return sorted(predicted, key=lambda x: x["ai_confidence"], reverse=True)

# ==============================================================================
# DATABASE SETUP (With Locking Protection)
# ==============================================================================
# Timeout=20 ensures it waits nicely if auto_trainer.py is updating the database
conn = sqlite3.connect("matches.db", timeout=20)
cursor = conn.cursor()
cursor.execute("CREATE TABLE IF NOT EXISTS matches (id INTEGER PRIMARY KEY AUTOINCREMENT, home_team TEXT, away_team TEXT, home_odds REAL, draw_odds REAL, away_odds REAL, prediction TEXT, confidence REAL, actual_result TEXT, prediction_status TEXT, timestamp TEXT, week TEXT, live_score TEXT, match_status TEXT, is_shortlisted INTEGER DEFAULT 0)")
cursor.execute("CREATE TABLE IF NOT EXISTS weekly_accumulators (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, week TEXT, result_1x2 TEXT, result_ou TEXT)")
cursor.execute("PRAGMA table_info(matches)")
existing_columns = [row[1] for row in cursor.fetchall()]
for col, col_type in [("prediction_ou", "TEXT"), ("prediction_ou_status", "TEXT"), ("is_shortlisted", "INTEGER DEFAULT 0")]:
    if col not in existing_columns: cursor.execute(f"ALTER TABLE matches ADD COLUMN {col} {col_type}")
conn.commit()

# ==============================================================================
# MAIN LOOP (With Anti-Zombie Protocol)
# ==============================================================================
options = webdriver.ChromeOptions()
options.add_argument("--disable-gpu"); options.add_argument("--window-size=1280,720")
driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
driver.get("https://vsmobile.bet9ja.com/bet9ja-mobile/login/?game=league&mode=premier")

shortlist_message_ids = {}
tracked_week = None
empty_page_counter = 0  # Tracks how long the page has been dead

while True:
    try:
        # 1. RAM PROTECTION: Delete weeks older than 10 iterations to stop memory bloat
        if len(shortlist_message_ids) > 10:
            oldest_week = list(shortlist_message_ids.keys())[0]
            del shortlist_message_ids[oldest_week]

        wait_for_page_ready(1); switch_to_iframe_if_present(1); wait_for_match_rows(1)
        current_week = "N/A"
        for elem in driver.find_elements(By.XPATH, "//*[contains(text(), 'Week')]"):
            match = re.search(r'Week\s*(\d+)', elem.text.strip(), re.IGNORECASE)
            if match: current_week = f"Wk {match.group(1)}"; break

        # ----------------------------------------------------------------------
        # FLIP DETECTOR & EXPORT
        # ----------------------------------------------------------------------
        if tracked_week and current_week != "N/A" and current_week != tracked_week:
            print(f"\n🔄 UI FLIP: {tracked_week} ended.")
            old_state = shortlist_message_ids.get(normalize_week_key(tracked_week))
            if old_state and not old_state.get("fully_settled"):
                shortlisted_targets = []
                for target in old_state.get("all_targets", []):
                    if not target.get("settled"):
                        final_score = target.get("last_known_score", "0 - 0")
                        actual_outcome = target.get("last_known_outcome", "DRAW")
                        target["final_score"], target["actual_outcome"] = final_score, actual_outcome
                        target["status"] = "CORRECT" if actual_outcome == target["prediction"] else "WRONG"
                        target["ou_status"] = "CORRECT" if calculate_total_goals(final_score) > 1 else "WRONG"
                        target["settled"] = True
                        cursor.execute("UPDATE matches SET actual_result=?, prediction_status=?, prediction_ou_status=?, live_score=?, match_status=? WHERE week=? AND home_team=? AND away_team=?", (actual_outcome, target["status"], target["ou_status"], final_score, "SETTLED", tracked_week, target["home_team"], target["away_team"]))
                        if target.get("is_shortlisted"): shortlisted_targets.append(target)
                conn.commit()
                
                if old_state.get("message_id") and shortlisted_targets: update_telegram_settlement(old_state["message_id"], tracked_week, shortlisted_targets)
                
                if len(shortlisted_targets) == MATCHES_PER_SHORTLIST:
                    acca_1x2 = "WIN" if all(t.get("status") == "CORRECT" for t in shortlisted_targets) else "LOSS"
                    acca_ou = "WIN" if all(t.get("ou_status") == "CORRECT" for t in shortlisted_targets) else "LOSS"
                    cursor.execute("INSERT INTO weekly_accumulators (timestamp, week, result_1x2, result_ou) VALUES (?, ?, ?, ?)", (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), tracked_week, acca_1x2, acca_ou))
                    conn.commit()
                    
                    history = cursor.execute("SELECT result_1x2, result_ou FROM weekly_accumulators ORDER BY id ASC").fetchall()
                    total_weeks = len(history)
                    wr_1x2 = round((sum(1 for r in history if r[0] == 'WIN') / total_weeks) * 100, 2) if total_weeks > 0 else 0
                    wr_ou = round((sum(1 for r in history if r[1] == 'WIN') / total_weeks) * 100, 2) if total_weeks > 0 else 0
                    
                    c1, m1, c2, m2 = 0, 0, 0, 0
                    for r in history:
                        c1 = c1 + 1 if r[0] == 'LOSS' else 0; m1 = max(m1, c1)
                        c2 = c2 + 1 if r[1] == 'LOSS' else 0; m2 = max(m2, c2)
                            
                    stats = {"acca_1x2": acca_1x2, "acca_ou": acca_ou, "win_rate_1x2": wr_1x2, "max_streak_1x2": m1, "win_rate_ou": wr_ou, "max_streak_ou": m2}
                    safe_google_export(tracked_week, shortlisted_targets, stats, old_state["all_targets"])
                old_state["fully_settled"] = True
        tracked_week = current_week

      # ----------------------------------------------------------------------
        # AI PREDICTION GENERATION
        # ----------------------------------------------------------------------
        
        # 2. DYNAMIC BRAIN UPDATE: Reload AI model on every loop just in case auto_trainer upgraded it!
        try:
            new_ai = joblib.load('ai_brain.pkl')
            ai_model = new_ai['model']
            ai_encoder = new_ai['encoder']
        except Exception: pass
        
        raw_matches = extract_raw_odds_js()
        
        # 3. ZOMBIE PROTECTION: Checks if we got disconnected from Bet9ja
        if not raw_matches:
            empty_page_counter += 1
            if empty_page_counter > 20:  # Roughly 2-3 minutes of dead space
                print("⚠️ ZOMBIE STATE DETECTED: No odds found. Session likely expired.")
                print("🔄 Executing Hard Reset...")
                driver.get("https://vsmobile.bet9ja.com/bet9ja-mobile/login/?game=league&mode=premier")
                time.sleep(10)
                switch_to_iframe_if_present(5)
                empty_page_counter = 0
                continue 
        else:
            empty_page_counter = 0

        week_key = normalize_week_key(current_week)
        week_state = shortlist_message_ids.setdefault(week_key, {"message_id": None, "prediction_sent": False, "all_targets": [], "fully_settled": False})
        
        if not week_state["all_targets"] and raw_matches:
            # FEED RAW ODDS TO AI
            ai_scored_matches = predict_with_ai(raw_matches)
            top_3 = ai_scored_matches[:MATCHES_PER_SHORTLIST]
            
            for m in ai_scored_matches:
                m["is_shortlisted"] = m in top_3
                week_state["all_targets"].append(m)
                try: cursor.execute("INSERT INTO matches (home_team, away_team, home_odds, draw_odds, away_odds, prediction, prediction_ou, timestamp, week, live_score, match_status, is_shortlisted, confidence) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (m["home_team"], m["away_team"], m["home_odds"], m["draw_odds"], m["away_odds"], m["prediction"], "OVER 1.5", datetime.now().strftime("%Y-%m-%d %H:%M:%S"), current_week, "0 - 0", "UPCOMING", m["is_shortlisted"], m["ai_confidence"]))
                except Exception: pass
            conn.commit()

        if week_state["all_targets"] and not week_state["prediction_sent"]:
            top_3 = [t for t in week_state["all_targets"] if t["is_shortlisted"]]
            msg_id = send_or_update_shortlist(week_state.get("message_id"), current_week, top_3)
            week_state.update({"message_id": msg_id, "prediction_sent": True})
            print(f"✨ AI Sent Top 3 Targets for {current_week} to Telegram.")

        # ----------------------------------------------------------------------
        # LIVE TRACKING
        # ----------------------------------------------------------------------
        for parsed in get_live_scores_js():
            for target in week_state["all_targets"]:
                if teams_match(target, parsed):
                    cs = f"{parsed['home_score']} - {parsed['away_score']}"
                    target["last_known_score"] = cs
                    target["last_known_outcome"] = get_result_from_score(parsed['home_score'], parsed['away_score'])
                    if target["is_shortlisted"]: print(f"✅ AI Tracking: {target['home_team']} vs {target['away_team']} | {cs}")
                    if not target.get("settled") and parsed.get("is_finished"):
                        target["final_score"], target["settled"] = target["last_known_score"], True
                        if target["is_shortlisted"] and week_state.get("message_id"): update_telegram_settlement(week_state.get("message_id"), current_week, [t for t in week_state["all_targets"] if t["is_shortlisted"]])
        time.sleep(0.5)
    except Exception as e:
        print(f"🔴 Main Loop Error: {e}")
        time.sleep(10)
        try: driver.refresh(); time.sleep(10); switch_to_iframe_if_present(5)
        except: pass