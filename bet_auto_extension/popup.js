document.addEventListener('DOMContentLoaded', () => {
    const serverStatus = document.getElementById('server-status');
    const botStatus = document.getElementById('bot-status');
    const toggleBtn = document.getElementById('toggle-btn');
    const saveBtn = document.getElementById('save-btn');
    const profitDisplay = document.getElementById('profit-display');
    const resetBtn = document.getElementById('reset-btn');
    const alertMsg = document.getElementById('alert-msg');
    
    const inputs = {
        licenseKey: document.getElementById('license-key'),
        baseStake: document.getElementById('base-stake'),
        takeProfit: document.getElementById('tp-limit'),
        stopLoss: document.getElementById('sl-limit'),
        maxLossStreak: document.getElementById('max-streak-limit'),
        chatId: document.getElementById('chat-id-input'),
        bettingMode: document.getElementById('betting-mode')
    };
    
    let isRunning = false;

    chrome.storage.local.get(['botEnabled', 'licenseKey', 'baseStake', 'takeProfit', 'stopLoss', 'maxLossStreak', 'chatId', 'totalProfit', 'bettingMode'], (res) => {
        isRunning = !!res.botEnabled;
        if (res.licenseKey !== undefined) inputs.licenseKey.value = res.licenseKey;
        if (res.baseStake !== undefined) inputs.baseStake.value = res.baseStake;
        if (res.takeProfit !== undefined) inputs.takeProfit.value = res.takeProfit;
        if (res.stopLoss !== undefined) inputs.stopLoss.value = res.stopLoss;
        if (res.maxLossStreak !== undefined) inputs.maxLossStreak.value = res.maxLossStreak;
        if (res.chatId !== undefined) inputs.chatId.value = res.chatId;
        if (res.bettingMode !== undefined) inputs.bettingMode.value = res.bettingMode;
        
        updateProfitUI(res.totalProfit || 0);
        updateUI();
    });

    function showAlert(msg, isError = false) {
        alertMsg.textContent = msg;
        alertMsg.style.color = isError ? "#ef4444" : "#10b981";
        setTimeout(() => { alertMsg.textContent = ""; }, 4000);
    }

    saveBtn.addEventListener('click', () => {
        const conf = {
            licenseKey: inputs.licenseKey.value.trim(),
            baseStake: parseFloat(inputs.baseStake.value),
            takeProfit: parseFloat(inputs.takeProfit.value),
            stopLoss: parseFloat(inputs.stopLoss.value),
            maxLossStreak: parseInt(inputs.maxLossStreak.value),
            chatId: inputs.chatId.value.trim(),
            bettingMode: inputs.bettingMode.value
        };

        if (!conf.licenseKey) {
            showAlert("⚠️ License Key is required.", true);
            return;
        }

        if (isNaN(conf.baseStake) || isNaN(conf.takeProfit) || isNaN(conf.stopLoss) || isNaN(conf.maxLossStreak)) {
            showAlert("⚠️ Please fill in all numeric fields correctly.", true);
            return;
        }

        chrome.storage.local.set(conf, () => {
            showAlert("✅ Configuration Saved!");
        });
    });

    resetBtn.addEventListener('click', () => {
        chrome.storage.local.set({ 
            totalProfit: 0, pendingBet: null, winStreak: 0, maxWinStreak: 0, 
            maxLossStreakRec: 0, localLossStreak: 0,
            licenseKey: '', baseStake: '', takeProfit: '', stopLoss: '', maxLossStreak: ''
        });
        
        inputs.licenseKey.value = '';
        inputs.baseStake.value = '';
        inputs.takeProfit.value = '';
        inputs.stopLoss.value = '';
        inputs.maxLossStreak.value = '';
        
        updateProfitUI(0);
        showAlert("🔄 System Reset. All fields cleared.");
    });

    toggleBtn.addEventListener('click', () => {
        if (!isRunning) {
            const lk = inputs.licenseKey.value;
            const bs = inputs.baseStake.value;
            const tp = inputs.takeProfit.value;
            const sl = inputs.stopLoss.value;
            const mls = inputs.maxLossStreak.value;

            if (!lk || !bs || !tp || !sl || !mls) {
                showAlert("⚠️ Please fill out all fields and click SAVE before starting.", true);
                return; 
            }
            chrome.storage.local.set({ botEnabled: true, localLossStreak: 0 });
        } else {
            chrome.storage.local.set({ botEnabled: false });
        }
    });

    function updateProfitUI(amount) {
        profitDisplay.textContent = amount >= 0 ? `+₦${amount.toFixed(2)}` : `-₦${Math.abs(amount).toFixed(2)}`;
        profitDisplay.style.color = amount > 0 ? '#10b981' : amount < 0 ? '#ef4444' : '#f59e0b';
    }

    function updateUI() {
        if (isRunning) {
            toggleBtn.innerHTML = "⏹ STOP AUTO-BET";
            toggleBtn.className = "btn btn-stop";
            botStatus.textContent = "Bot: ARMED 🟢";
        } else {
            toggleBtn.innerHTML = "▶ ENABLE AUTO-BET";
            toggleBtn.className = "btn btn-start";
            botStatus.textContent = "Bot: OFF 🔴";
        }
    }

    setInterval(async () => {
        chrome.storage.local.get(['totalProfit', 'botEnabled', 'licenseKey'], async (res) => {
            updateProfitUI(res.totalProfit || 0);
            if (isRunning !== !!res.botEnabled) {
                isRunning = !!res.botEnabled;
                updateUI();
            }

            try {
                const response = await fetch('http://78.47.19.148:5000/get_bets', {
                    headers: { 'X-License-Key': res.licenseKey || '' }
                });
                
                if (response.status === 401) {
                    serverStatus.textContent = "🔴 Invalid License Key";
                    serverStatus.style.color = "#ef4444";
                } else {
                    serverStatus.textContent = "🟢 Server Linked & Authenticated";
                    serverStatus.style.color = "#10b981";
                }
            } catch (e) {
                serverStatus.textContent = "🔴 Server Offline";
                serverStatus.style.color = "#ef4444";
            }
        });
    }, 2000);
});