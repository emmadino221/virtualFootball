import json
import uuid
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_cors import CORS
import sqlite3
import time
import os
import re
import requests
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
from pathlib import Path
import joblib
import numpy as np
import threading

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
DB_PATH = Path(os.getenv("VIRTUAL_DB_PATH", BASE_DIR / "matches.db")).expanduser()
AI_MODEL_PATH = Path(os.getenv("VIRTUAL_AI_MODEL_PATH", BASE_DIR / "ai_brain.pkl")).expanduser()
AI_GG_MODEL_PATH = Path(os.getenv("VIRTUAL_AI_GG_MODEL_PATH", BASE_DIR / "ai_brain_gg.pkl")).expanduser()
GOOGLE_CREDENTIALS_FILE = Path(os.getenv("GOOGLE_CREDENTIALS_FILE", BASE_DIR / "credentials.json")).expanduser()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
VALID_KEYS = [key.strip() for key in os.getenv("VALID_KEYS", "").split(",") if key.strip()]

if not TOKEN or not CHAT_ID or not VALID_KEYS:
    raise ValueError("Missing Telegram or extension credentials. Configure the service environment.")

print("⏳ Loading Dual-Brain AI System...")
try:
    ai_package = joblib.load(AI_MODEL_PATH)
    ai_model = ai_package['model']
    ai_encoder = ai_package['encoder']
    
    ai_package_gg = joblib.load(AI_GG_MODEL_PATH)
    ai_model_gg = ai_package_gg['model']
    print("🧠 DUAL AI Brains loaded and ready to predict!")
except Exception as e:
    print(f"⚠️ CRITICAL: Could not load AI models. Error: {e}")
    exit()

TEAM_SHIRT_COLORS = {
    "ASV": "🟩", "LEE": "🟦", "TOT": "⚪", "EVE": "🔵", "NWC": "🟧",
    "BOU": "🟡", "CHE": "🔵", "FUL": "⚫", "BRI": "🔵", "FOR": "🟤",
}

app = Flask(__name__)
CORS(app)

current_live_targets = []
current_ready_week = None
current_loss_streak_ou = 0  
current_loss_streak_1x2 = 0 
current_loss_streak_gg = 0
pending_commands = []
last_known_ext_state = {"botEnabled": False, "baseStake": 100, "takeProfit": 0, "stopLoss": 0, "totalProfit": 0.0, "bettingMode": "OU"}

def check_auth(req):
    key = req.headers.get("X-License-Key")
    return key in VALID_KEYS

@app.route('/get_bets', methods=['GET'])
def get_bets(): 
    if not check_auth(request): return jsonify({"error": "Unauthorized"}), 401
    return jsonify({"status": "ok"})

@app.route('/sync', methods=['POST'])
def sync_ext():
    if not check_auth(request): return jsonify({"error": "Unauthorized"}), 401
    global last_known_ext_state, pending_commands
    data = request.json
    if data: last_known_ext_state.update(data)
    cmds = pending_commands[:]
    pending_commands.clear()
    return jsonify({
        "targets_ou": [t for t in current_live_targets if t.get("is_ou_target")],
        "targets_1x2": [t for t in current_live_targets if t.get("is_1x2_target")],
        "targets_gg": [t for t in current_live_targets if t.get("is_gg_target")],
        "loss_streak_ou": current_loss_streak_ou,
        "loss_streak_1x2": current_loss_streak_1x2,
        "loss_streak_gg": current_loss_streak_gg,
        "commands": cmds
    })

@app.route('/is_week_ready', methods=['GET'])
def is_week_ready(): 
    if not check_auth(request): return jsonify({"error": "Unauthorized"}), 401
    return jsonify({"ready_week": current_ready_week, "is_ready": current_ready_week is not None})

@app.route('/send_receipt', methods=['POST'])
def send_receipt():
    if not check_auth(request): return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    if not data or not data.get('chat_id'): return jsonify({"status": "error"}), 400
    res_type, stake, net_profit = data['result'], data['stake'], data['net_profit']
    emoji = "✅" if res_type == "WIN" else "❌"
    sign = "+" if net_profit >= 0 else "-"
    msg = f"<b>🧾 BOT RECEIPT | {res_type} {emoji}</b>\n\n"
    msg += f"<b>Stake Placed:</b> ₦{stake:,.2f}\n"
    msg += f"<b>Total Net Profit:</b> {sign}₦{abs(net_profit):,.2f}\n"
    msg += "—"*20 + "\n"
    msg += f"<b>Win Streak:</b> {data['win_streak']} | <b>Loss Streak:</b> {data['loss_streak']}\n"
    msg += f"<b>Max Wins:</b> {data['max_win_streak']} | <b>Max Losses:</b> {data['max_loss_streak']}\n"
    safe_request(f"https://api.telegram.org/bot{TOKEN}/sendMessage", {"chat_id": data['chat_id'], "text": msg, "parse_mode": "HTML"})
    return jsonify({"status": "sent"})

def run_server():
    import logging
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    app.run(
        host=os.getenv("VIRTUAL_API_HOST", "127.0.0.1"),
        port=int(os.getenv("VIRTUAL_API_PORT", "5000")),
        use_reloader=False,
        debug=False,
    )

def send_telegram_message(text, target_chat_id=None):
    cid = target_chat_id if target_chat_id else CHAT_ID
    data = safe_request(f"https://api.telegram.org/bot{TOKEN}/sendMessage", {"chat_id": cid, "text": text, "parse_mode": "HTML"})
    return data["result"]["message_id"] if data and data.get("ok") else None

def telegram_poller():
    offset = None
    while True:
        try:
            url = f"https://api.telegram.org/bot{TOKEN}/getUpdates"
            params = {"timeout": 30, "allowed_updates": ["message"]}
            if offset: params["offset"] = offset
            resp = requests.get(url, params=params).json()
            if resp.get("ok"):
                for result in resp.get("result", []):
                    offset = result["update_id"] + 1
                    msg = result.get("message", {})
                    text = msg.get("text", "").strip()
                    chat_id = str(msg.get("chat", {}).get("id", ""))
                    if text.startswith("/"): handle_telegram_command(text, chat_id)
        except Exception: time.sleep(5)

def handle_telegram_command(text, req_chat_id):
    global pending_commands, current_loss_streak_ou, current_loss_streak_1x2, current_loss_streak_gg
    cmd = text.lower().split(); main_cmd = cmd[0]
    if main_cmd == "/stop":
        pending_commands.append({"type": "STOP"})
        send_telegram_message("🛑 <b>COMMAND RECEIVED:</b> Bot Kill-Switch Activated.", req_chat_id)
    elif main_cmd == "/start":
        pending_commands.append({"type": "START"})
        send_telegram_message("🟢 <b>COMMAND RECEIVED:</b> Bot Armed.", req_chat_id)
    elif main_cmd == "/stake" and len(cmd) > 1:
        try:
            val = float(cmd[1])
            pending_commands.append({"type": "STAKE", "value": val})
            send_telegram_message(f"💰 <b>COMMAND RECEIVED:</b> Base Stake updated to ₦{val}", req_chat_id)
        except: send_telegram_message("⚠️ <b>ERROR:</b> Invalid amount.", req_chat_id)
    elif main_cmd == "/tp" and len(cmd) > 1:
        try:
            val = float(cmd[1])
            pending_commands.append({"type": "TP", "value": val})
            send_telegram_message(f"🎯 <b>COMMAND RECEIVED:</b> Take Profit updated to +₦{val:,.2f}", req_chat_id)
        except: send_telegram_message("⚠️ <b>ERROR:</b> Invalid amount.", req_chat_id)
    elif main_cmd == "/sl" and len(cmd) > 1:
        try:
            val = float(cmd[1])
            pending_commands.append({"type": "SL", "value": val})
            send_telegram_message(f"🛡️ <b>COMMAND RECEIVED:</b> Stop Loss updated to -₦{val:,.2f}", req_chat_id)
        except: send_telegram_message("⚠️ <b>ERROR:</b> Invalid amount.", req_chat_id)
    elif main_cmd == "/mode" and len(cmd) > 1:
        new_mode = cmd[1].upper()
        if new_mode in ["OU", "1X2", "GG"]:
            pending_commands.append({"type": "MODE", "value": new_mode})
            send_telegram_message(f"⚙️ <b>COMMAND RECEIVED:</b> Strategy switched to {new_mode}", req_chat_id)
    elif main_cmd == "/reset":
        current_loss_streak_ou = current_loss_streak_1x2 = current_loss_streak_gg = 0
        pending_commands.append({"type": "RESET"})
        send_telegram_message("🔄 <b>COMMAND RECEIVED:</b> System Reset. Wiped to zero.", req_chat_id)
    elif main_cmd == "/history":
        try:
            conn_hist = sqlite3.connect(DB_PATH, timeout=20)
            c_hist = conn_hist.cursor()
            history = c_hist.execute("SELECT week, result_ou, result_1x2, result_gg FROM weekly_accumulators ORDER BY id DESC LIMIT 5").fetchall()
            conn_hist.close()
            if not history: send_telegram_message("📜 <b>HISTORY:</b> No settled matches yet.", req_chat_id)
            else:
                msg = "📜 <b>LAST 5 MATCHES:</b>\n\n"
                for r in history:
                    e_ou = "✅" if r[1] == "WIN" else "❌" if r[1] == "LOSS" else "🟡"
                    e_1x2 = "✅" if r[2] == "WIN" else "❌" if r[2] == "LOSS" else "🟡"
                    e_gg = "✅" if r[3] == "WIN" else "❌" if r[3] == "LOSS" else "🟡"
                    msg += f"<b>{r[0]}:</b> O/U: {e_ou} | 1X2: {e_1x2} | GG: {e_gg}\n"
                send_telegram_message(msg, req_chat_id)
        except: send_telegram_message(f"⚠️ <b>ERROR:</b> Could not read history.", req_chat_id)
    elif main_cmd == "/status":
        st = last_known_ext_state
        mode = st.get("bettingMode", "OU")
        active_streak = current_loss_streak_ou if mode == "OU" else (current_loss_streak_1x2 if mode == "1X2" else current_loss_streak_gg)
        profit = st.get("totalProfit", 0.0)
        en = "🟢 RUNNING" if st.get("botEnabled") else "🔴 STOPPED"
        msg = f"📊 <b>LIVE STATUS</b>\n\n<b>Engine:</b> {en}\n<b>Strategy:</b> {mode}\n<b>Base Stake:</b> ₦{st.get('baseStake', 0)}\n<b>Net Profit:</b> {'+' if profit >= 0 else '-'}₦{abs(profit):,.2f}\n<b>Global Loss Streak:</b> {active_streak}"
        send_telegram_message(msg, req_chat_id)

threading.Thread(target=run_server, daemon=True).start()
threading.Thread(target=telegram_poller, daemon=True).start()

def team_shirt(team): return TEAM_SHIRT_COLORS.get(team, "👕")
def wait_for_page_ready(timeout=4):
    WebDriverWait(driver, timeout).until(lambda d: d.execute_script("return document.readyState") == "complete")
    time.sleep(0.3)
def switch_to_iframe_if_present(timeout=3):
    try: driver.switch_to.frame(WebDriverWait(driver, timeout).until(EC.presence_of_element_located((By.TAG_NAME, "iframe")))); return True
    except: return False
def wait_for_match_rows(timeout=2):
    try: WebDriverWait(driver, timeout).until(lambda d: len(d.find_elements(By.TAG_NAME, "tr")) >= 3); return True
    except: return False
def normalize_team_name(name): return re.sub(r'[^A-Za-z0-9]', '', name).strip().upper()
def normalize_week_key(wl):
    m = re.search(r'(\d+)', str(wl).strip())
    return f"WK{int(m.group(1))}" if m else re.sub(r'[^A-Za-z0-9]+', '', str(wl)).upper() or "N/A"
def teams_match(target, parsed):
    th, ta = normalize_team_name(target.get("home_team", "")), normalize_team_name(target.get("away_team", ""))
    ph, pa = normalize_team_name(parsed.get("home_team", "")), normalize_team_name(parsed.get("away_team", ""))
    if not th or not ta or not ph or not pa: return False
    return (th == ph and ta == pa) or (th == pa and ta == ph)
def get_result_from_score(h, a): return "HOME" if h > a else "AWAY" if a > h else "DRAW"
def calculate_total_goals(score_str):
    try: h, a = map(int, score_str.replace(" ", "").split("-")); return h + a
    except: return 0

def get_current_stats():
    try:
        conn_hist = sqlite3.connect(DB_PATH, timeout=20)
        c_hist = conn_hist.cursor()
        history = c_hist.execute("SELECT result_1x2, result_ou, result_gg FROM weekly_accumulators ORDER BY id ASC").fetchall()
        conn_hist.close()
        tw = len(history)
        if tw == 0: return None
        wr_1x2 = round((sum(1 for r in history if r[0] == 'WIN') / tw) * 100, 2)
        wr_ou = round((sum(1 for r in history if r[1] == 'WIN') / tw) * 100, 2)
        wr_gg = round((sum(1 for r in history if r[2] == 'WIN') / tw) * 100, 2)
        c1, m1, c2, m2, c3, m3 = 0, 0, 0, 0, 0, 0
        for r in history:
            c1 = c1 + 1 if r[0] == 'LOSS' else 0; m1 = max(m1, c1)
            c2 = c2 + 1 if r[1] == 'LOSS' else 0; m2 = max(m2, c2)
            c3 = c3 + 1 if r[2] == 'LOSS' else 0; m3 = max(m3, c3)
        return {"wr_1x2": wr_1x2, "ml_1x2": m1, "wr_ou": wr_ou, "ml_ou": m2, "wr_gg": wr_gg, "ml_gg": m3}
    except Exception: return None

def safe_request(url, payload, max_retries=3):
    for _ in range(max_retries):
        try: return requests.post(url, json=payload, timeout=15).json()
        except: time.sleep(5)
    return {}

def safe_google_export(week, shortlisted_targets, stats, all_targets, max_retries=3):
    for attempt in range(max_retries):
        try:
            scope = ["https://spreadsheets.google.com/feeds", 'https://www.googleapis.com/auth/spreadsheets', "https://www.googleapis.com/auth/drive"]
            creds = ServiceAccountCredentials.from_json_keyfile_name(str(GOOGLE_CREDENTIALS_FILE), scope)
            client = gspread.authorize(creds)
            sheet1 = client.open("VirtualFootballResults").worksheet("Sheet1")
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            rows1 = []
            for t in shortlisted_targets:
                rows1.append([
                    ts, week, t["home_team"], t["away_team"], 
                    t["prediction"] if t.get("is_1x2_target") else "-", 
                    "OVER 2.5" if t.get("is_ou_target") else "-", 
                    t.get("prediction_gg", "-") if t.get("is_gg_target") else "-", 
                    t["home_odds"], t["draw_odds"], t["away_odds"], 
                    t.get("over_15_odds", 0.0), t.get("gg_odds", 0.0), t.get("ng_odds", 0.0), 
                    t.get("final_score", "0 - 0"), 
                    t.get("status", "WRONG") if t.get("is_1x2_target") else "-", 
                    t.get("ou_status", "WRONG") if t.get("is_ou_target") else "-", 
                    t.get("gg_status", "WRONG") if t.get("is_gg_target") else "-", 
                    stats.get("acca_1x2", "N/A"), stats.get("acca_ou", "N/A"), stats.get("acca_gg", "N/A"), 
                    f"{stats.get('win_rate_1x2', 0)}%", stats.get("max_streak_1x2", 0), 
                    f"{stats.get('win_rate_ou', 0)}%", stats.get("max_streak_ou", 0), 
                    f"{stats.get('win_rate_gg', 0)}%", stats.get("max_streak_gg", 0)
                ])
            if rows1: sheet1.append_rows(rows1)
            return
        except Exception as e: time.sleep(5)

def build_shortlist_message(week, matches, stats=None):
    lines = [f"<b>🤖 AI TARGETS | Week: {week}</b>\n"]
    lines.append("<b>🏆 1X2 HIGH-VALUE SINGLE</b>")
    s_m = [m for m in matches if m.get("is_1x2_target")]
    lines.append(f"1. {team_shirt(s_m[0]['home_team'])}{s_m[0]['home_team']} vs {team_shirt(s_m[0]['away_team'])}{s_m[0]['away_team']} — Pick: <b>{s_m[0]['prediction']}</b>" if s_m else "<i>None.</i>")
    
    # UPDATED FOR OVER 2.5
    lines.append("\n<b>⚽ OVER 2.5 SINGLE</b>")
    o_m = [m for m in matches if m.get("is_ou_target")]
    lines.append(f"1. {team_shirt(o_m[0]['home_team'])}{o_m[0]['home_team']} vs {team_shirt(o_m[0]['away_team'])}{o_m[0]['away_team']} — Pick: <b>Over 2.5</b>" if o_m else "<i>None.</i>")
    
    lines.append("\n<b>🎯 GG SINGLE</b>")
    g_m = [m for m in matches if m.get("is_gg_target")]
    lines.append(f"1. {team_shirt(g_m[0]['home_team'])}{g_m[0]['home_team']} vs {team_shirt(g_m[0]['away_team'])}{g_m[0]['away_team']} — Pick: <b>{g_m[0]['prediction_gg']}</b>" if g_m else "<i>None.</i>")
    
    if stats:
        lines.append("\n<b>📊 LIVE STRATEGY STATS</b>")
        lines.append(f"<b>1X2:</b> Win: {stats['wr_1x2']}% | Max Loss: {stats['ml_1x2']}")
        lines.append(f"<b>O/U:</b> Win: {stats['wr_ou']}% | Max Loss: {stats['ml_ou']}")
        lines.append(f"<b>GG:</b> Win: {stats['wr_gg']}% | Max Loss: {stats['ml_gg']}")
    lines.append("\n<b>Status:</b> 🟡 <b>PENDING</b>")
    return "\n".join(lines)

def send_or_update_shortlist(msg_id, week, matches):
    stats = get_current_stats()
    text = build_shortlist_message(week, matches, stats)
    if msg_id:
        data = safe_request(f"https://api.telegram.org/bot{TOKEN}/editMessageText", {"chat_id": CHAT_ID, "message_id": msg_id, "text": text, "parse_mode": "HTML"})
        if data and data.get("ok"): return msg_id
    return send_telegram_message(text)

def update_telegram_settlement(msg_id, week, matches):
    lines = [f"<b>🏁 RESULTS | Week: {week}</b>\n"]
    s_m = [m for m in matches if m.get("is_1x2_target")]
    if s_m: lines.append(f"{'✅' if s_m[0].get('status')=='CORRECT' else '❌'} {s_m[0]['home_team']} vs {s_m[0]['away_team']} ({s_m[0].get('final_score')}) — {s_m[0].get('prediction')}")
    
    # UPDATED FOR OVER 2.5
    lines.append("\n<b>⚽ OVER 2.5 RESULTS</b>")
    o_m = [m for m in matches if m.get("is_ou_target")]
    if o_m: lines.append(f"{'✅' if o_m[0].get('ou_status')=='CORRECT' else '❌'} {o_m[0]['home_team']} vs {o_m[0]['away_team']} ({o_m[0].get('final_score')})")
    
    lines.append("\n<b>🎯 GG SINGLE</b>")
    g_m = [m for m in matches if m.get("is_gg_target")]
    if g_m: lines.append(f"{'✅' if g_m[0].get('gg_status')=='CORRECT' else '❌'} {g_m[0]['home_team']} vs {g_m[0]['away_team']} ({g_m[0].get('final_score')}) — {g_m[0].get('prediction_gg')}")
    safe_request(f"https://api.telegram.org/bot{TOKEN}/editMessageText", {"chat_id": CHAT_ID, "message_id": msg_id, "text": "\n".join(lines), "parse_mode": "HTML"})

def get_live_scores_js():
    js = r"""const res=[];const hs=document.querySelectorAll('span[id^="goal_team_A_"]');for(const h of hs){try{const i=h.id.replace('goal_team_A_','');const a=document.getElementById('goal_team_B_'+i);if(!a)continue;const hc=parseInt(h.textContent.trim(),10);const ac=parseInt(a.textContent.trim(),10);if(isNaN(hc)||isNaN(ac))continue;const hr=h.closest('tr');const ar=a.closest('tr');const et=(r)=>{const tds=r.querySelectorAll('td');for(const td of tds){const txt=td.textContent.trim();if(/^[A-Z]{2,4}$/.test(txt))return txt;}return null;};const ht=et(hr);const at=et(ar);if(!ht||!at)continue;const mc=hr.closest('table').parentElement.parentElement||document.body;const f=/\b(FT|FINISHED|FULL\s*TIME|ENDED)\b/i.test(mc.textContent);res.push({home_team:ht,away_team:at,home_score:hc,away_score:ac,is_finished:f});}catch(e){}}return res;"""
    try: return driver.execute_script(js) or []
    except: return []

def extract_raw_odds_js():
    js = r"""const rows=document.querySelectorAll('tr');const res=[];for(const r of rows){if(r.offsetParent===null)continue;const c=r.querySelectorAll('input.checkbox_bets');if(c.length<3)continue;const ho=parseFloat(c[0].value);const doo=parseFloat(c[1].value);const ao=parseFloat(c[2].value);if(!(ho>0&&doo>0&&ao>0))continue;let tn=[];const b=r.querySelectorAll('td div.badge-market.w-30');for(const s of b){const t=s.textContent.trim();if(t&&t!=='-')tn.push(t);}if(tn.length<2){tn=[];const alt=r.querySelectorAll('td .badge-market');for(const s of alt){const t=s.textContent.trim();if(t&&t!=='-')tn.push(t);}}if(tn.length<2){tn=[];const d=r.querySelectorAll('div');for(const di of d){const t=di.textContent.trim();if(t.length>0&&t.length<=4&&t===t.toUpperCase()&&t!=='-')tn.push(t);}}if(tn.length>=2)res.push({home_team:tn[0],away_team:tn[1],home_odds:ho,draw_odds:doo,away_odds:ao});}return res;"""
    try: return driver.execute_script(js) or []
    except: return []

def extract_odds_js(market_size):
    js = f"""const rows=document.querySelectorAll('tr');const res=[];for(const r of rows){{if(r.offsetParent===null)continue;const c=r.querySelectorAll('input.checkbox_bets');if(c.length<{market_size})continue;let tn=[];const b=r.querySelectorAll('td div.badge-market.w-30');for(const s of b){{const t=s.textContent.trim();if(t&&t!=='-')tn.push(t);}}if(tn.length<2){{const alt=r.querySelectorAll('td .badge-market');for(const s of alt){{const t=s.textContent.trim();if(t&&t!=='-')tn.push(t);}}}}if(tn.length<2){{const d=r.querySelectorAll('div');for(const di of d){{const t=di.textContent.trim();if(t.length>0&&t.length<=4&&t===t.toUpperCase()&&t!=='-')tn.push(t);}}}}if(tn.length>=2){{res.push({{home_team:tn[0], away_team:tn[1], odd1: parseFloat(c[0].value), odd2: parseFloat(c[1].value), odd3: c.length>=3 ? parseFloat(c[2].value) : 0}});}}}}return res;"""
    try: return driver.execute_script(js) or []
    except: return []

def get_all_market_odds():
    m_1x2 = extract_raw_odds_js()
    
    # 1. Switch to Over/Under 2.5
    try: driver.execute_script("const el=document.getElementById('bet-select-market'); if(el){el.value='Over_Under_2_5'; el.dispatchEvent(new Event('change'));}")
    except: pass
    time.sleep(1.5)
    m_ou = extract_odds_js(2) # m_ou will now contain Over 2.5 odds
    
    # 2. Switch to GG/NG
    try: driver.execute_script("const el=document.getElementById('bet-select-market'); if(el){el.value='GoalGoal_NoGoal'; el.dispatchEvent(new Event('change'));}")
    except: pass
    time.sleep(1.5)
    m_gg = extract_odds_js(2) # m_gg will now contain GG/NG odds
    
    # Return to Main
    try: driver.execute_script("const el=document.getElementById('bet-select-market'); if(el){el.value='Match_Result'; el.dispatchEvent(new Event('change'));}")
    except: pass
    time.sleep(1.0)
    
    merged = {}
    for m in m_1x2:
        key = f"{m['home_team']}_{m['away_team']}"
        merged[key] = {
            "home_team": m['home_team'], "away_team": m['away_team'], 
            "home_odds": m['home_odds'], "draw_odds": m['draw_odds'], "away_odds": m['away_odds'], 
            "ou_25_odds": 0.0, "gg_odds": 0.0, "ng_odds": 0.0
        }
        
    for m in m_ou:
        key = f"{m['home_team']}_{m['away_team']}"
        if key in merged: merged[key]['ou_25_odds'] = m['odd1'] # Correctly mapping Over 2.5 odds
        
    for m in m_gg:
        key = f"{m['home_team']}_{m['away_team']}"
        if key in merged: 
            merged[key]['gg_odds'] = m['odd1']  # Correctly mapping GG odds
            merged[key]['ng_odds'] = m['odd2']  # Correctly mapping NG odds
            
    return list(merged.values())

def calculate_dynamic_form(team_name, db_cursor, window=3):
    db_cursor.execute("SELECT home_team, actual_result, live_score FROM matches WHERE (home_team = ? OR away_team = ?) AND match_status = 'SETTLED' ORDER BY id DESC LIMIT ?", (team_name, team_name, window))
    rows = db_cursor.fetchall()
    pts, gf, ga = 0, 0, 0
    for h_team, res, score in rows:
        try: hg, ag = map(int, score.replace(" ", "").split("-"))
        except: continue
        if team_name == h_team: pts += 3 if res == 'HOME' else (1 if res == 'DRAW' else 0); gf += hg; ga += ag
        else: pts += 3 if res == 'AWAY' else (1 if res == 'DRAW' else 0); gf += ag; ga += hg
    return pts, gf, ga

def predict_with_ai(raw_matches):
    scored = []
    seen = set()
    for m in raw_matches:
        ht, at = m["home_team"], m["away_team"]
        if (ht, at) in seen: continue
        seen.add((ht, at))
        ho, do, ao = float(m["home_odds"]), float(m["draw_odds"]), float(m["away_odds"])
        model_valid = True
        try: h_id = ai_encoder.transform([ht])[0]; a_id = ai_encoder.transform([at])[0]
        except ValueError: h_id, a_id = 0, 0; model_valid = False
        h_pts, h_gf, h_ga = calculate_dynamic_form(ht, cursor)
        a_pts, a_gf, a_ga = calculate_dynamic_form(at, cursor)
        pts_diff = h_pts - a_pts
        gd_diff = (h_gf - h_ga) - (a_gf - a_ga)
        features_1x2 = [[h_id, a_id, ho, do, ao, 1/ho, 1/do, 1/ao, (1/ho+1/do+1/ao), h_pts, a_pts, pts_diff, gd_diff]]
        features_gg = [[h_id, a_id, ho, do, ao, 1/ho, 1/do, 1/ao, (1/ho+1/do+1/ao), h_pts, a_pts, h_gf, h_ga, a_gf, a_ga, pts_diff, gd_diff]]
        try:
            pred_class = ai_model.predict(features_1x2)[0]; confidence = ai_model.predict_proba(features_1x2)[0][list(ai_model.classes_).index(pred_class)] * 100
            pred_class_gg = ai_model_gg.predict(features_gg)[0]; confidence_gg = ai_model_gg.predict_proba(features_gg)[0][list(ai_model_gg.classes_).index(pred_class_gg)] * 100
        except Exception:
            model_valid = False
            pred_class, confidence = "HOME", 33.3; pred_class_gg, confidence_gg = "NG", 50.0
        scored.append({
            "home_team": ht, "away_team": at, "home_odds": ho, "draw_odds": do, "away_odds": ao,
            "over_15_odds": m.get("over_15_odds", 0.0), "gg_odds": m.get("gg_odds", 0.0), "ng_odds": m.get("ng_odds", 0.0),
            "prediction": pred_class, "prediction_ou": "OVER 2.5", "ai_confidence": confidence,
            "prediction_gg": pred_class_gg, "ai_confidence_gg": confidence_gg, "model_valid": model_valid,
            "settled": False, "last_known_score": "0 - 0"
        })
    def get_pred_odds(m):
        if m["prediction"] == "HOME": return m["home_odds"]
        if m["prediction"] == "AWAY": return m["away_odds"]
        return m["draw_odds"]
    possible_singles = [m for m in scored if get_pred_odds(m) >= 1.70]
    best_1x2_single = sorted(possible_singles, key=lambda x: x["ai_confidence"], reverse=True)[:1]
    
    # 🔴 UPDATED: Grab ONLY the single best match for Over 2.5
    best_ou_single = sorted(scored, key=lambda x: x["ai_confidence"], reverse=True)[:1]
    
    # Only allow GG matches for the GG single strategy
    gg_only_matches = [m for m in scored if m["prediction_gg"] == "GG"]
    best_gg_single = sorted(gg_only_matches, key=lambda x: x["ai_confidence_gg"], reverse=True)[:1]
    
    return scored, best_1x2_single, best_ou_single, best_gg_single

DB_PATH.parent.mkdir(parents=True, exist_ok=True)
conn = sqlite3.connect(DB_PATH, timeout=20)
cursor = conn.cursor()
cursor.execute("CREATE TABLE IF NOT EXISTS matches (id INTEGER PRIMARY KEY AUTOINCREMENT, home_team TEXT, away_team TEXT, home_odds REAL, draw_odds REAL, away_odds REAL, prediction TEXT, confidence REAL, actual_result TEXT, prediction_status TEXT, timestamp TEXT, week TEXT, live_score TEXT, match_status TEXT, is_shortlisted INTEGER DEFAULT 0)")
cursor.execute("CREATE TABLE IF NOT EXISTS weekly_accumulators (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, week TEXT, result_1x2 TEXT, result_ou TEXT)")
cursor.execute("PRAGMA table_info(matches)")
existing_columns = [row[1] for row in cursor.fetchall()]
for col, col_type in [("website_markets", "TEXT"), ("website_round", "TEXT"), ("confidence_gg", "REAL"), ("prediction_ou", "TEXT"), ("prediction_ou_status", "TEXT"), ("prediction_gg", "TEXT"), ("over_15_odds", "REAL"), ("gg_odds", "REAL"), ("ng_odds", "REAL")]:
    if col not in existing_columns: cursor.execute(f"ALTER TABLE matches ADD COLUMN {col} {col_type}")
cursor.execute("PRAGMA table_info(weekly_accumulators)")
acc_cols = [row[1] for row in cursor.fetchall()]
if "result_gg" not in acc_cols: cursor.execute("ALTER TABLE weekly_accumulators ADD COLUMN result_gg TEXT")
conn.commit()

options = webdriver.ChromeOptions()
options.add_argument("--disable-gpu")
options.add_argument("--window-size=1280,720")
options.add_argument("--headless") 
options.add_argument("--no-sandbox") 
options.add_argument("--disable-dev-shm-usage")
driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
driver.get("https://vsmobile.bet9ja.com/bet9ja-mobile/login/?game=league&mode=premier")

shortlist_message_ids = {}
tracked_week = None
empty_page_counter = 0  

while True:
    try:
        if len(shortlist_message_ids) > 10: del shortlist_message_ids[list(shortlist_message_ids.keys())[0]]
        wait_for_page_ready(1); switch_to_iframe_if_present(1); wait_for_match_rows(1)
        current_week = "N/A"
        for elem in driver.find_elements(By.XPATH, "//*[contains(text(), 'Week')]"):
            match = re.search(r'Week\s*(\d+)', elem.text.strip(), re.IGNORECASE)
            if match: current_week = f"Wk {match.group(1)}"; break
        if current_week == "N/A": time.sleep(1); continue

        if tracked_week and current_week != tracked_week:
            print(f"\n🔄 UI FLIP: {tracked_week} ended. Processing data export...")
            current_ready_week = None 
            old_state = shortlist_message_ids.get(normalize_week_key(tracked_week))
            if old_state and not old_state.get("fully_settled"):
                shortlisted_targets = []
                for target in old_state.get("all_targets", []):
                    fs = target.get("last_known_score", "0 - 0"); ao = target.get("last_known_outcome", "DRAW")
                    target["final_score"] = fs; target["actual_outcome"] = ao
                    target["status"] = "CORRECT" if ao == target["prediction"] else "WRONG"
                    
                    # 🔴 UPDATED: Calculate >2 Goals for Over 2.5 validation
                    target["ou_status"] = "CORRECT" if calculate_total_goals(fs) > 2 else "WRONG"
                    
                    try: hg, ag = map(int, fs.replace(" ", "").split("-"))
                    except: hg, ag = 0, 0
                    actual_gg = "GG" if hg > 0 and ag > 0 else "NG"
                    target["gg_status"] = "CORRECT" if actual_gg == target.get("prediction_gg") else "WRONG"
                    target["settled"] = True
                    cursor.execute("UPDATE matches SET actual_result=?, prediction_status=?, prediction_ou_status=?, live_score=?, match_status=? WHERE week=? AND home_team=? AND away_team=? AND website_round=?", (ao, target["status"], target["ou_status"], fs, "SETTLED", tracked_week, target["home_team"], target["away_team"], old_state.get("website_round")))
                    if target.get("is_shortlisted"): shortlisted_targets.append(target)
                conn.commit()
                if old_state.get("message_id") and shortlisted_targets: update_telegram_settlement(old_state.get("message_id"), tracked_week, shortlisted_targets)
                
                # 🔴 UPDATED: Check ACCA success based on 1 match
                ou_matches = [t for t in shortlisted_targets if t.get("is_ou_target")]
                if len(ou_matches) == 1:
                    acca_ou = "WIN" if ou_matches[0].get("ou_status") == "CORRECT" else "LOSS"
                    if acca_ou == "WIN": current_loss_streak_ou = 0
                    else: current_loss_streak_ou += 1
                else: acca_ou = "N/A"
                
                single_matches = [t for t in shortlisted_targets if t.get("is_1x2_target")]
                if len(single_matches) == 1:
                    acca_1x2 = "WIN" if single_matches[0].get("status") == "CORRECT" else "LOSS"
                    if acca_1x2 == "WIN": current_loss_streak_1x2 = 0
                    else: current_loss_streak_1x2 += 1
                else: acca_1x2 = "N/A"
                
                gg_matches = [t for t in shortlisted_targets if t.get("is_gg_target")]
                if len(gg_matches) == 1:
                    acca_gg = "WIN" if gg_matches[0].get("gg_status") == "CORRECT" else "LOSS"
                    if acca_gg == "WIN": current_loss_streak_gg = 0
                    else: current_loss_streak_gg += 1
                else: acca_gg = "N/A"
                
                cursor.execute("INSERT INTO weekly_accumulators (timestamp, week, result_1x2, result_ou, result_gg) VALUES (?, ?, ?, ?, ?)", (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), tracked_week, acca_1x2, acca_ou, acca_gg))
                conn.commit()
                stats = get_current_stats()
                if stats:
                    stats_for_export = {"acca_1x2": acca_1x2, "acca_ou": acca_ou, "acca_gg": acca_gg, "win_rate_1x2": stats["wr_1x2"], "max_streak_1x2": stats["ml_1x2"], "win_rate_ou": stats["wr_ou"], "max_streak_ou": stats["ml_ou"], "win_rate_gg": stats["wr_gg"], "max_streak_gg": stats["ml_gg"]}
                    safe_google_export(tracked_week, shortlisted_targets, stats_for_export, old_state["all_targets"])
                old_state["fully_settled"] = True
        tracked_week = current_week

        try:
            new_ai = joblib.load(AI_MODEL_PATH); ai_model = new_ai['model']; ai_encoder = new_ai['encoder']
            new_ai_gg = joblib.load(AI_GG_MODEL_PATH); ai_model_gg = new_ai_gg['model']
        except Exception: pass
        
        fast_check = extract_raw_odds_js()
        if not fast_check:
            empty_page_counter += 1
            if empty_page_counter > 20:  
                print("⚠️ ZOMBIE STATE DETECTED: No odds found. Hard Resetting...")
                driver.get("https://vsmobile.bet9ja.com/bet9ja-mobile/login/?game=league&mode=premier")
                time.sleep(10); switch_to_iframe_if_present(5); empty_page_counter = 0
                continue 
        else: empty_page_counter = 0

        week_key = normalize_week_key(current_week)
        week_state = shortlist_message_ids.setdefault(week_key, {"message_id": None, "prediction_sent": False, "all_targets": [], "fully_settled": False})
        
        if not week_state["all_targets"]:
            raw_matches = get_all_market_odds()
            if raw_matches:
                scored, best_1x2_single, best_ou_single, best_gg_single = predict_with_ai(raw_matches)
                # Freeze website picks before any result is available. This does not
                # change the existing Telegram/extension strategies.
                website_round = uuid.uuid4().hex
                week_state["website_round"] = website_round
                valid = [m for m in scored if m.get("model_valid")]
                def rank(items, field, count):
                    return sorted(items, key=lambda m: (-float(m[field]), m["home_team"], m["away_team"]))[:count]
                selected_win = rank([m for m in valid if m["prediction"] in {"HOME", "AWAY"} and float(m[{"HOME": "home_odds", "AWAY": "away_odds"}[m["prediction"]]]) > 1.70], "ai_confidence", 1)
                selected_gg = rank([m for m in valid if m["prediction_gg"] == "GG"], "ai_confidence_gg", 1)
                selected_ng = rank([m for m in valid if m["prediction_gg"] == "NG"], "ai_confidence_gg", 1)
                selected_over = rank([m for m in valid if m["prediction_gg"] == "GG" and m["ai_confidence_gg"] >= 60], "ai_confidence_gg", 2)
                if len(selected_over) != 2:
                    selected_over = []
                for m in scored:
                    m["website_markets"] = [key for key, group in [("over", selected_over), ("gg", selected_gg), ("ng", selected_ng), ("win", selected_win)] if m in group]
                current_live_targets = []
                for m in scored:
                    m["is_1x2_target"] = m in best_1x2_single; m["is_ou_target"] = m in best_ou_single; m["is_gg_target"] = m in best_gg_single
                    m["is_shortlisted"] = m["is_1x2_target"] or m["is_ou_target"] or m["is_gg_target"]
                    if m["is_shortlisted"]: current_live_targets.append(m)
                    week_state["all_targets"].append(m)
                    try: cursor.execute("INSERT INTO matches (home_team, away_team, home_odds, draw_odds, away_odds, over_15_odds, gg_odds, ng_odds, prediction, prediction_ou, prediction_gg, timestamp, week, live_score, match_status, is_shortlisted, confidence, confidence_gg, website_round, website_markets) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (m["home_team"], m["away_team"], m["home_odds"], m["draw_odds"], m["away_odds"], m["over_15_odds"], m["gg_odds"], m["ng_odds"], m["prediction"], "OVER 2.5", m["prediction_gg"], datetime.now().strftime("%Y-%m-%d %H:%M:%S"), current_week, "0 - 0", "UPCOMING", m["is_shortlisted"], m["ai_confidence"], m["ai_confidence_gg"] if m.get("model_valid") else None, website_round, json.dumps(m["website_markets"])))
                    except Exception: pass
                conn.commit()

        if week_state["all_targets"] and not week_state["prediction_sent"]:
            targets_to_send = [t for t in week_state["all_targets"] if t.get("is_shortlisted")]
            msg_id = send_or_update_shortlist(week_state.get("message_id"), current_week, targets_to_send)
            week_state.update({"message_id": msg_id, "prediction_sent": True}); current_ready_week = current_week  
            print(f"✨ AI Sent Signals for {current_week} to Telegram.")

        for parsed in get_live_scores_js():
            for target in week_state["all_targets"]:
                if teams_match(target, parsed):
                    cs = f"{parsed['home_score']} - {parsed['away_score']}"
                    target["last_known_score"] = cs
                    target["last_known_outcome"] = get_result_from_score(parsed['home_score'], parsed['away_score'])
                    if target.get("is_shortlisted"): print(f"✅ AI Tracking: {target['home_team']} vs {target['away_team']} | {cs}")
                    if parsed.get("is_finished"): target["final_score"] = target["last_known_score"]
        time.sleep(0.5)
    except Exception as e:
        print(f"🔴 Main Loop Error: {e}")
        time.sleep(10)
        try: driver.refresh(); time.sleep(10); switch_to_iframe_if_present(5)
        except: pass
