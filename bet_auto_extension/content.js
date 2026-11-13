let isBusy = false;
const MARTINGALE_MULTIPLIER = 2.54; 
const SELECTORS = {
    currentWeek: "#leagueWeekNumber",                
    tableRow: "tr",                                  
    stakeInput: "#inputAmount",                      
    placeBetBtn: "#button_bet",                      
    confirmBetBtn: "#button_bet_ticket",             
    closeTicketBtn: "#button_sent-ticket-close"      
};

// 🔴 CHANGE THIS IP ADDRESS TO MATCH WHERE YOUR PYTHON SCRIPT IS RUNNING
const API_BASE_URL = 'https://159.65.25.30/virtual-api';

const POLLING_INTERVAL_MS = 3000;
// A loss is only recovered by the next stake when the odds are at least M / (M - 1).
const MIN_ODDS = 1.65;
const PENDING_TIMEOUT_MS = 15 * 60 * 1000;
const WEEK_LOCK_MS = 10 * 60 * 1000;
const RESULT_KEYS = { 'OU': 'ou', '1X2': '1x2', 'GG': 'gg' };

function createOverlay() {
    const overlay = document.createElement('div');
    overlay.id = 'bet-automation-overlay';
    overlay.innerHTML = `
        <div class="overlay-header">
            <div class="overlay-title">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="margin-right: 6px; color: #38bdf8;"><circle cx="12" cy="12" r="10"></circle><circle cx="12" cy="12" r="6"></circle><circle cx="12" cy="12" r="2"></circle></svg>
                AI-Sniper 
                <span id="overlay-running-profit">₦0.00</span>
            </div>
            <div class="overlay-controls">
                <button id="overlay-minimize">−</button>
                <button id="overlay-close">✕</button>
            </div>
        </div>
        <div class="overlay-content">
            <div class="panel status-panel">
                <div class="flex-row">
                    <span class="label">Status:</span>
                    <span class="status-badge" id="status-text">Initializing...</span>
                </div>
                <div class="flex-row mt-1">
                    <span class="label">Current Week:</span>
                    <span class="week-text" id="week-text">-</span>
                </div>
            </div>
            
            <div class="panel matches-panel">
                <div class="panel-title">Active Targets</div>
                <div class="matches-list" id="matches-list">
                    <div style="opacity:0.5; font-size:0.9em; text-align:center; padding:10px 0;">No active targets</div>
                </div>
            </div>

            <div class="panel log-panel">
                <div class="panel-title">Activity Log</div>
                <div id="stats-log"></div>
            </div>

            <div class="panel finance-panel">
                <div class="fin-row"><span>Total Odds:</span> <span id="overlay-odds" class="highlight-text">0.00</span></div>
                <div class="fin-row"><span>Next Stake:</span> <span id="overlay-stake" class="highlight-text">₦0.00</span></div>
                <div class="fin-row return-row"><span>Est. Return:</span> <span id="overlay-return" class="success-text">₦0.00</span></div>
            </div>
        </div>
    `;

    const style = document.createElement('style');
    style.textContent = `
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
        
        #bet-automation-overlay { 
            position: fixed; bottom: 20px; right: 20px; 
            width: 340px; min-width: 260px; max-width: 600px;
            height: 480px; min-height: 300px; max-height: 80vh;
            background: rgba(15, 23, 42, 0.95); 
            backdrop-filter: blur(10px);
            border-radius: 12px; 
            box-shadow: 0 25px 50px -12px rgba(0,0,0,0.5), 0 0 0 1px rgba(255,255,255,0.1); 
            z-index: 999999; color: #f8fafc; 
            display: flex; flex-direction: column; 
            resize: both; overflow: hidden;
            font-family: 'Inter', system-ui, sans-serif;
            container-type: inline-size;
            container-name: overlay;
        }

        #bet-automation-overlay.minimized .overlay-content { display: none; }
        
        /* 🔴 FLUID TYPOGRAPHY BASED ON CONTAINER WIDTH */
        #bet-automation-overlay * { font-size: clamp(10px, 3.5cqi, 14px); box-sizing: border-box; }
        
        .overlay-header { 
            background: rgba(0, 0, 0, 0.3); padding: 12px 16px; 
            display: flex; justify-content: space-between; align-items: center; 
            border-bottom: 1px solid rgba(255, 255, 255, 0.05); 
            cursor: grab; flex-shrink: 0;
        }
        .overlay-header:active { cursor: grabbing; }
        .overlay-title { font-weight: 700; display: flex; align-items: center; font-size: 1.1em; letter-spacing: -0.02em; }
        
        #overlay-running-profit { 
            margin-left: 10px; padding: 2px 8px; border-radius: 999px; 
            background: rgba(34, 197, 94, 0.2); color: #4ade80; 
            font-size: 0.85em; font-weight: 600; border: 1px solid rgba(34, 197, 94, 0.3);
        }

        .overlay-controls { display: flex; gap: 8px; }
        .overlay-controls button { 
            background: rgba(255, 255, 255, 0.1); border: none; color: white; 
            width: 24px; height: 24px; border-radius: 6px; cursor: pointer; 
            display: flex; align-items: center; justify-content: center; 
            transition: all 0.2s; 
        }
        .overlay-controls button:hover { background: rgba(255, 255, 255, 0.2); }

        .overlay-content { 
            flex: 1; overflow-y: auto; padding: 12px; 
            display: flex; flex-direction: column; gap: 10px; 
        }
        
        /* Custom Scrollbar */
        .overlay-content::-webkit-scrollbar { width: 4px; }
        .overlay-content::-webkit-scrollbar-track { background: transparent; }
        .overlay-content::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.2); border-radius: 4px; }

        .panel { 
            background: rgba(255, 255, 255, 0.03); 
            border: 1px solid rgba(255, 255, 255, 0.05); 
            border-radius: 8px; padding: 10px; 
        }
        
        .panel-title { font-size: 0.75em; text-transform: uppercase; letter-spacing: 0.05em; color: #94a3b8; font-weight: 600; margin-bottom: 8px; }
        
        .flex-row { display: flex; justify-content: space-between; align-items: center; }
        .mt-1 { margin-top: 6px; }
        .label { color: #94a3b8; font-weight: 500; }
        
        .status-badge { padding: 2px 8px; border-radius: 6px; font-weight: 600; background: rgba(56, 189, 248, 0.15); color: #38bdf8; }
        .week-text { font-weight: 700; color: #facc15; }
        
        .matches-panel { flex-grow: 1; display: flex; flex-direction: column; }
        .matches-list { display: flex; flex-direction: column; gap: 6px; overflow-y: auto; }
        .match-item { 
            background: rgba(0, 0, 0, 0.2); padding: 8px 10px; border-radius: 6px; 
            border-left: 3px solid #38bdf8; display: flex; justify-content: space-between; 
            align-items: center; animation: slideIn 0.3s ease;
        }
        @keyframes slideIn { from { opacity: 0; transform: translateX(-5px); } to { opacity: 1; transform: translateX(0); } }
        
        .log-panel { max-height: 80px; overflow-y: auto; background: rgba(0,0,0,0.3); }
        #stats-log { display: flex; flex-direction: column; gap: 4px; }
        .log-entry { font-family: 'Courier New', Courier, monospace; font-size: 0.85em; color: #cbd5e1; border-bottom: 1px solid rgba(255,255,255,0.05); padding-bottom: 4px; }
        .log-entry:last-child { border-bottom: none; }

        .finance-panel { background: rgba(15, 23, 42, 0.8); border: 1px solid rgba(56, 189, 248, 0.2); }
        .fin-row { display: flex; justify-content: space-between; margin-bottom: 4px; align-items: center; }
        .fin-row:last-child { margin-bottom: 0; }
        .highlight-text { font-weight: 600; color: #e2e8f0; }
        .return-row { margin-top: 8px; padding-top: 8px; border-top: 1px dashed rgba(255,255,255,0.1); }
        .success-text { color: #4ade80; font-weight: 700; font-size: 1.1em !important; }
    `;
    document.head.appendChild(style);
    document.body.appendChild(overlay);
    
    makeElementDraggable(overlay);
    
    // 🔴 ResizeObserver for Fluid Typography
    const ro = new ResizeObserver(entries => {
        for (let entry of entries) {
            // Forces the browser to recalculate the container size variables
            entry.target.style.setProperty('--overlay-width', entry.contentRect.width + 'px');
        }
    });
    ro.observe(overlay);

    document.getElementById('overlay-minimize').addEventListener('click', () => { overlay.classList.toggle('minimized'); });
    document.getElementById('overlay-close').addEventListener('click', () => { overlay.style.display = 'none'; });
    
    return overlay;
}

function makeElementDraggable(element) {
    let pos1 = 0, pos2 = 0, pos3 = 0, pos4 = 0;
    const header = element.querySelector('.overlay-header');
    header.onmousedown = (e) => {
        e.preventDefault();
        pos3 = e.clientX; pos4 = e.clientY;
        document.onmouseup = () => { document.onmouseup = null; document.onmousemove = null; };
        document.onmousemove = (e) => {
            e.preventDefault();
            pos1 = pos3 - e.clientX; pos2 = pos4 - e.clientY;
            pos3 = e.clientX; pos4 = e.clientY;
            element.style.top = (element.offsetTop - pos2) + "px";
            element.style.left = (element.offsetLeft - pos1) + "px";
            element.style.bottom = 'auto'; element.style.right = 'auto';
        };
    };
}

// UI Update Helpers
function updateOverlayStatus(text, type = 'info') {
    try {
        const statusEl = document.getElementById('status-text');
        if (statusEl) {
            statusEl.textContent = text;
            statusEl.style.color = type === 'success' ? '#4ade80' : type === 'error' ? '#f87171' : '#38bdf8';
            statusEl.style.background = type === 'success' ? 'rgba(74, 222, 128, 0.15)' : type === 'error' ? 'rgba(248, 113, 113, 0.15)' : 'rgba(56, 189, 248, 0.15)';
        }
    } catch (e) { }
}

function updateOverlayWeek(week) { try { const weekEl = document.getElementById('week-text'); if (weekEl) weekEl.textContent = week; } catch (e) { } }

function updateOverlayTotalProfit(amount) {
    try {
        const profitEl = document.getElementById('overlay-running-profit');
        if (profitEl) {
            profitEl.textContent = amount >= 0 ? `+₦${amount.toFixed(2)}` : `-₦${Math.abs(amount).toFixed(2)}`;
            profitEl.style.color = amount >= 0 ? '#4ade80' : '#f87171';
            profitEl.style.background = amount >= 0 ? 'rgba(34, 197, 94, 0.15)' : 'rgba(239, 68, 68, 0.15)';
            profitEl.style.borderColor = amount >= 0 ? 'rgba(34, 197, 94, 0.3)' : 'rgba(239, 68, 68, 0.3)';
        }
    } catch (e) {}
}

function addMatchToOverlay(home, away, odds, status = 'success') {
    try {
        const matchList = document.getElementById('matches-list');
        if (!matchList) return;
        if(matchList.innerHTML.includes("No active targets")) matchList.innerHTML = ''; // Clear placeholder
        
        const matchItem = document.createElement('div');
        matchItem.className = 'match-item';
        matchItem.style.borderLeftColor = status === 'success' ? '#4ade80' : '#f87171';
        matchItem.innerHTML = `
            <span style="font-weight: 500;">${home} v ${away}</span> 
            <span style="color:#facc15; font-weight:700;">${odds}</span>
        `;
        matchList.appendChild(matchItem);
        while (matchList.children.length > 5) matchList.removeChild(matchList.firstChild);
    } catch (e) { }
}

function updateFinancials(odds, stake, expectedReturn, pureProfit) {
    try {
        document.getElementById('overlay-odds').textContent = odds;
        document.getElementById('overlay-stake').textContent = `₦${stake}`;
        document.getElementById('overlay-return').innerHTML = `₦${expectedReturn} <span style="font-size:0.8em; opacity:0.7; font-weight:400; margin-left:4px;">(+₦${pureProfit})</span>`;
    } catch (e) { }
}

function addLogEntry(text) {
    try {
        const logEl = document.getElementById('stats-log');
        if (!logEl) return;
        const entry = document.createElement('div');
        entry.className = 'log-entry';
        entry.textContent = `> ${text}`;
        logEl.insertBefore(entry, logEl.firstChild);
        while (logEl.children.length > 5) logEl.removeChild(logEl.lastChild);
    } catch (e) { }
}

// System Init
window.addEventListener('load', () => {
    createOverlay();
    updateOverlayStatus('Ready', 'info');
    chrome.storage.local.get(['totalProfit'], (res) => updateOverlayTotalProfit(res.totalProfit || 0));
});

function getIframeDoc() {
    const iframe = document.querySelector('iframe');
    return iframe ? iframe.contentDocument : document;
}

async function fetchAIData() {
    const empty = { ok: false, targets: [], mode: 'OU', readyWeek: null, roundId: null, results: [], serverSupported: true };
    try {
        const st = await chrome.storage.local.get(['botEnabled', 'baseStake', 'takeProfit', 'stopLoss', 'totalProfit', 'bettingMode', 'licenseKey', 'chatId']);
        const currentMode = st.bettingMode || 'OU';

        const response = await fetch(`${API_BASE_URL}/sync`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-License-Key': st.licenseKey || ''
            },
            body: JSON.stringify({
                botEnabled: !!st.botEnabled,
                baseStake: st.baseStake || 100,
                takeProfit: st.takeProfit || 0,
                stopLoss: st.stopLoss || 0,
                totalProfit: st.totalProfit || 0,
                bettingMode: currentMode,
                chatId: st.chatId || ''
            })
        });

        if (response.status === 401) {
            if (st.botEnabled) await triggerCircuitBreaker("Invalid License!");
            return empty;
        }
        if (!response.ok) return empty;

        const data = await response.json();

        if (data.commands && data.commands.length > 0) {
            for (const cmd of data.commands) {
                if (cmd.type === 'STOP') {
                    await chrome.storage.local.set({ botEnabled: false });
                    updateOverlayStatus('🛑 STOPPED', 'error');
                    addLogEntry('Remote: Kill-Switch Activated');
                } else if (cmd.type === 'START') {
                    await chrome.storage.local.set({ botEnabled: true, localLossStreak: 0 });
                    updateOverlayStatus('🟢 RUNNING', 'success');
                    addLogEntry('Remote: Bot Started');
                } else if (cmd.type === 'STAKE') {
                    await chrome.storage.local.set({ baseStake: cmd.value });
                    addLogEntry(`Remote: Stake ₦${cmd.value}`);
                } else if (cmd.type === 'TP') {
                    await chrome.storage.local.set({ takeProfit: cmd.value });
                    addLogEntry(`Remote: TP +₦${cmd.value}`);
                } else if (cmd.type === 'SL') {
                    await chrome.storage.local.set({ stopLoss: cmd.value });
                    addLogEntry(`Remote: SL -₦${cmd.value}`);
                } else if (cmd.type === 'RESET') {
                    await chrome.storage.local.set({ totalProfit: 0, pendingBet: null, winStreak: 0, maxWinStreak: 0, maxLossStreakRec: 0, localLossStreak: 0 });
                    updateOverlayTotalProfit(0);
                    addLogEntry('Remote: System Wiped');
                } else if (cmd.type === 'MODE') {
                    await chrome.storage.local.set({ bettingMode: cmd.value });
                    addLogEntry(`Remote: Mode -> ${cmd.value}`);
                }
            }
        }

        const reCheck = await chrome.storage.local.get(['bettingMode']);
        const finalMode = reCheck.bettingMode || 'OU';

        let activeTargets = [];
        if (finalMode === 'OU') activeTargets = data.targets_ou;
        else if (finalMode === '1X2') activeTargets = data.targets_1x2;
        else if (finalMode === 'GG') activeTargets = data.targets_gg;

        return {
            ok: true,
            targets: activeTargets || [],
            mode: finalMode,
            readyWeek: data.ready_week || null,
            roundId: data.round_id || null,
            results: Array.isArray(data.results) ? data.results : [],
            // Older servers do not report rounds; without them a bet cannot be settled safely.
            serverSupported: 'round_id' in data && 'results' in data
        };
    } catch (error) { return empty; }
}

function normalizeWeek(weekStr) {
    const match = String(weekStr).match(/(\d+)/);
    return match ? match[1] : String(weekStr);
}

function simulateHumanClick(element) {
    if (!element) return false;
    element.style.border = "2px solid #38bdf8";
    element.dispatchEvent(new MouseEvent('click', { view: window, bubbles: true, cancelable: true }));
    element.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
    element.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
    return true;
}

const sleep = (ms) => new Promise(r => setTimeout(r, ms));
const isVisible = (element) => !!element && element.getClientRects().length > 0;

async function waitForVisible(doc, selector, timeoutMs) {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
        const element = doc.querySelector(selector);
        if (isVisible(element)) return element;
        await sleep(250);
    }
    return null;
}

async function triggerCircuitBreaker(reason) {
    await chrome.storage.local.set({ botEnabled: false });
    updateOverlayStatus(`STOPPED: ${reason}`, 'error');
    addLogEntry(`🛑 STOPPED: ${reason}`);
}

// Settles the bet this browser actually placed, using the result of the exact round it was
// placed on. Returns true while that result is still outstanding.
async function settlePendingBet(results) {
    const st = await chrome.storage.local.get(['pendingBet', 'totalProfit', 'winStreak', 'maxWinStreak', 'maxLossStreakRec', 'localLossStreak', 'chatId', 'licenseKey']);
    const bet = st.pendingBet;
    if (!bet) return false;

    const entry = bet.roundId ? results.find(r => r.round_id === bet.roundId) : null;
    const outcome = entry ? entry[RESULT_KEYS[bet.mode]] : null;

    if (outcome !== 'WIN' && outcome !== 'LOSS') {
        const waiting = !entry && bet.placedAt && Date.now() - bet.placedAt < PENDING_TIMEOUT_MS;
        if (waiting) return true;
        await chrome.storage.local.set({ pendingBet: null });
        addLogEntry(`Result unknown for ${bet.week || 'last bet'} - not counted, check Bet9ja`);
        return false;
    }

    let currentTotal = st.totalProfit || 0;
    let wStrk = st.winStreak || 0;
    let mWStrk = st.maxWinStreak || 0;
    let mLStrk = st.maxLossStreakRec || 0;
    let lossStreak = st.localLossStreak || 0;

    if (outcome === 'WIN') {
        currentTotal += bet.profit;
        addLogEntry(`WON: +₦${bet.profit.toFixed(2)}`);
        wStrk++;
        if (wStrk > mWStrk) mWStrk = wStrk;
        lossStreak = 0;
    } else {
        currentTotal -= bet.stake;
        addLogEntry(`LOST: -₦${bet.stake.toFixed(2)}`);
        wStrk = 0;
        lossStreak++;
        if (lossStreak > mLStrk) mLStrk = lossStreak;
    }

    await chrome.storage.local.set({
        totalProfit: currentTotal,
        pendingBet: null,
        winStreak: wStrk,
        maxWinStreak: mWStrk,
        maxLossStreakRec: mLStrk,
        localLossStreak: lossStreak
    });
    updateOverlayTotalProfit(currentTotal);

    if (st.chatId && st.licenseKey) {
        fetch(`${API_BASE_URL}/send_receipt`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-License-Key': st.licenseKey },
            body: JSON.stringify({ chat_id: st.chatId, result: outcome, stake: bet.stake, profit: bet.profit, net_profit: currentTotal, win_streak: wStrk, loss_streak: lossStreak, max_win_streak: mWStrk, max_loss_streak: mLStrk })
        }).catch(e => console.log("Telegram Receipt Error:", e));
    }
    return false;
}

// Remembered in storage so reloading the page cannot bet the same week twice.
async function markWeekHandled(week) {
    await chrome.storage.local.set({ lastBetMark: { week, at: Date.now() } });
}

function findSelection(row, target, mode) {
    if (mode === 'OU') {
        const element = row.querySelector("label[for*='Over_Under_2_5'][for$='_over2']");
        return element ? { element, tag: '>2.5' } : null;
    }
    if (mode === '1X2') {
        const inputs = row.querySelectorAll('input.checkbox_bets');
        if (inputs.length < 3) return null;
        const targetInput = target.prediction === "HOME" ? inputs[0] : target.prediction === "DRAW" ? inputs[1] : inputs[2];
        const element = targetInput ? row.querySelector(`label[for='${targetInput.id}']`) : null;
        return element ? { element, tag: target.prediction } : null;
    }
    if (mode === 'GG') {
        const element = row.querySelector("label[for$='_gg']");
        return element ? { element, tag: 'GG' } : null;
    }
    return null;
}

async function executeBets(payload) {
    if (!payload.ok) return;

    const stillPending = await settlePendingBet(payload.results);

    const storage = await chrome.storage.local.get(['botEnabled', 'baseStake', 'takeProfit', 'stopLoss', 'maxLossStreak', 'maxStake', 'totalProfit', 'localLossStreak', 'lastBetMark', 'licenseKey']);
    if (!storage.botEnabled) return;
    if (storage.baseStake === undefined || storage.baseStake === '' ||
        storage.maxLossStreak === undefined || storage.maxLossStreak === '' ||
        !storage.licenseKey) {
        await triggerCircuitBreaker("Setup Missing");
        return;
    }

    const conf = {
        baseStake: parseFloat(storage.baseStake),
        takeProfit: parseFloat(storage.takeProfit) || 0,
        stopLoss: Math.abs(parseFloat(storage.stopLoss)) || 0,
        maxLossStreak: parseInt(storage.maxLossStreak) || 0,
        maxStake: parseFloat(storage.maxStake) || 0
    };
    if (!(conf.baseStake > 0)) { await triggerCircuitBreaker("Invalid Base Stake"); return; }

    if (!payload.serverSupported) { updateOverlayStatus('Server update required', 'error'); return; }
    if (stillPending) { updateOverlayStatus('Bet placed - awaiting result', 'info'); return; }

    const currentTotal = storage.totalProfit || 0;
    const lossStreak = storage.localLossStreak || 0;
    if (conf.takeProfit > 0 && currentTotal >= conf.takeProfit) { await triggerCircuitBreaker(`Target Reached (+₦${conf.takeProfit})`); return; }
    if (conf.stopLoss > 0 && currentTotal <= -conf.stopLoss) { await triggerCircuitBreaker(`Stop Loss Hit (-₦${conf.stopLoss})`); return; }
    if (conf.maxLossStreak > 0 && lossStreak >= conf.maxLossStreak) { await triggerCircuitBreaker(`Max Loss Streak (${conf.maxLossStreak})`); return; }

    const doc = getIframeDoc();
    const weekEl = doc.querySelector(SELECTORS.currentWeek);
    if (!weekEl) return;
    const currentWeekStr = weekEl.innerText.trim();

    const mark = storage.lastBetMark;
    if (mark && mark.week === currentWeekStr && Date.now() - mark.at < WEEK_LOCK_MS) return;

    const targets = payload.targets;
    const targetMode = payload.mode;
    if (!payload.roundId || !payload.readyWeek || normalizeWeek(payload.readyWeek) !== normalizeWeek(currentWeekStr) || targets.length === 0) {
        updateOverlayStatus('Awaiting Signals...', 'info');
        return;
    }

    document.getElementById('matches-list').innerHTML = '';
    updateFinancials("0.00", "0.00", "0.00", "0.00");
    updateOverlayWeek(currentWeekStr);
    updateOverlayStatus(`Locking Targets [${targetMode}]`, 'success');

    let dataLoaded = false;
    for (let i = 0; i < 10; i++) {
        if (doc.querySelectorAll(SELECTORS.tableRow).length > 5) { dataLoaded = true; break; }
        await sleep(1000);
    }
    if (!dataLoaded) { updateOverlayStatus('Timeout', 'error'); return; }

    const marketValue = { 'OU': 'Over_Under_2_5', '1X2': 'Match_Result', 'GG': 'GoalGoal_NoGoal' }[targetMode];
    const selectMenu = doc.getElementById('bet-select-market');
    if (selectMenu && marketValue) { selectMenu.value = marketValue; selectMenu.dispatchEvent(new Event('change', { bubbles: true })); await sleep(2500); }

    let pick = null;
    for (const row of doc.querySelectorAll(SELECTORS.tableRow)) {
        const textContent = row.innerText.replace(/[^A-Za-z0-9]/g, '').toUpperCase();
        for (const target of targets) {
            if (!textContent.includes(target.home_team) || !textContent.includes(target.away_team)) continue;
            const selection = findSelection(row, target, targetMode);
            if (selection) { pick = { ...selection, target }; break; }
        }
        if (pick) break;
    }

    // From here the week is finished for this browser, whether or not a bet goes through.
    await markWeekHandled(currentWeekStr);

    if (!pick) {
        updateOverlayStatus('Mismatch: 0/1', 'error');
        addLogEntry('Error: Targets not found/Odds disabled');
        return;
    }

    const oddsValue = parseFloat(pick.element.innerText || pick.element.textContent);
    if (isNaN(oddsValue) || oddsValue < MIN_ODDS) {
        addMatchToOverlay(pick.target.home_team, pick.target.away_team, `[${pick.tag}] ${isNaN(oddsValue) ? '-' : oddsValue}`, 'error');
        updateOverlayStatus('Skipped: odds too low', 'info');
        addLogEntry(`Skipped ${currentWeekStr}: odds below ${MIN_ODDS}`);
        return;
    }

    const calculatedStake = conf.baseStake * Math.pow(MARTINGALE_MULTIPLIER, lossStreak);
    const finalStake = parseFloat(calculatedStake.toFixed(2));
    const expectedReturn = parseFloat((calculatedStake * oddsValue).toFixed(2));
    const pureProfit = parseFloat((expectedReturn - calculatedStake).toFixed(2));

    if (conf.maxStake > 0 && finalStake > conf.maxStake) { await triggerCircuitBreaker(`Next stake ₦${finalStake} is above Max Stake`); return; }
    if (conf.stopLoss > 0 && currentTotal - finalStake < -conf.stopLoss) { await triggerCircuitBreaker(`Next stake ₦${finalStake} would pass Stop Loss`); return; }

    updateOverlayStatus('Executing...', 'info');
    simulateHumanClick(pick.element);
    addMatchToOverlay(pick.target.home_team, pick.target.away_team, `[${pick.tag}] ${oddsValue}`, 'success');
    await sleep(2000);

    updateFinancials(oddsValue.toFixed(2), finalStake.toFixed(2), expectedReturn.toFixed(2), pureProfit.toFixed(2));
    updateOverlayStatus(`Placing Bet`, 'info');
    addLogEntry(`Stake Math: ₦${conf.baseStake} x ${MARTINGALE_MULTIPLIER}^${lossStreak}`);

    const stakeInput = doc.querySelector(SELECTORS.stakeInput);
    const betBtn = doc.querySelector(SELECTORS.placeBetBtn);
    if (!stakeInput || !betBtn) { await triggerCircuitBreaker('Bet slip not found - no bet placed'); return; }

    stakeInput.value = finalStake;
    stakeInput.dispatchEvent(new Event('input', { bubbles: true }));
    await sleep(1000);
    simulateHumanClick(betBtn);

    const confirmBtn = await waitForVisible(doc, SELECTORS.confirmBetBtn, 5000);
    if (!confirmBtn) { await triggerCircuitBreaker('Confirm button missing - no bet placed'); return; }
    simulateHumanClick(confirmBtn);

    // Only count the bet once Bet9ja shows the sent-ticket dialog.
    const closeBtn = await waitForVisible(doc, SELECTORS.closeTicketBtn, 8000);
    if (!closeBtn) {
        await triggerCircuitBreaker('Bet not confirmed - check your Bet9ja bet history');
        return;
    }

    await chrome.storage.local.set({ pendingBet: { stake: finalStake, profit: pureProfit, week: currentWeekStr, roundId: payload.roundId, mode: targetMode, placedAt: Date.now() } });
    updateOverlayStatus('Bet Confirmed ✅', 'success');
    addLogEntry(`Placed: ₦${finalStake.toFixed(2)}`);
    simulateHumanClick(closeBtn);
}

setInterval(async () => {
    if (isBusy) return;
    isBusy = true;
    try {
        const payload = await fetchAIData();
        await executeBets(payload);
    } catch (e) {
        addLogEntry('Error: ' + e.message);
    }
    isBusy = false;
}, POLLING_INTERVAL_MS);
