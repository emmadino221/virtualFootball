// Simulates the extension content script against a fake Bet9ja page and fake server payloads.
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');

const store = {};
let clock = 1_800_000_000_000;
const clicks = [];
const page = { week: 'Week 5', ticketVisible: true, overOdds: ['1.30', '1.35'], ggOdds: '1.90', ngOdds: '1.80', homeOdds: '2.10',
    options: ['Match_Result', 'Over_Under_1_5', 'Over_Under_2_5', 'GoalGoal_NoGoal'], namedLabels: true };

const el = (extra = {}) => ({ style: {}, innerText: '', textContent: '', innerHTML: '', children: [], classList: { toggle() {} },
    addEventListener() {}, appendChild() {}, insertBefore() {}, removeChild() {}, querySelector: () => el(), dispatchEvent() {}, getClientRects: () => [1], ...extra });

const select = el({ value: 'Match_Result', get options() { return []; } });
Object.defineProperty(select, 'options', { get: () => page.options.map(value => ({ value, textContent: value.replace(/_/g, ' ') })) });

function label(forId, name, odds) {
    const l = el({ getAttribute: () => forId, dispatchEvent(e) { if (e.type === 'click') clicks.push(name); } });
    Object.defineProperty(l, 'innerText', { get: odds });
    l.forId = forId;
    return l;
}
const ODD = { Match_Result: ['Home', 'Draw', 'Away'], GoalGoal_NoGoal: ['GG', 'NG'], Over_Under_1_5: ['Over', 'Under'] };
// Real page: one panel per tab, all in the DOM, only the active one visible.
function tabRow(index, home, away, m) {
    const shown = () => page.tabs && (page.tabStuck ? 'Match_Result' : page.activeTab) === m;
    const names = () => page.oddNames || ODD[m];
    const labs = () => ODD[m].map((o, i) => { const l = label(`${m}_${index}_${names()[i]}`, `${home}:${m}:${o}`, () => ['2.10', '1.90', '1.80'][i]); l.getClientRects = () => shown() ? [1] : []; l.oddid = names()[i]; return l; });
    return Object.defineProperty(el({
        querySelectorAll: sel => !page.tabs ? [] : sel === 'label[for]' ? labs() : sel === 'input.checkbox_bets' ? labs().map(l => ({ id: l.forId, dataset: { marketid: m, oddid: l.oddid } })) : [],
        querySelector: sel => { const k = sel.match(/^label\[for='(.+)'\]$/); return k && page.tabs ? labs().find(l => l.forId === k[1]) || null : null; }
    }), 'innerText', { get: () => page.tabs ? `${home} - ${away}` : '' });
}
function makeRow(index, home, away) {
    const labelsNow = () => {
        if (page.tabs) return [];
        const m = page.stuck ? 'GoalGoal_NoGoal' : select.value;
        if (m === 'Match_Result') return [label(`in${index}_0`, `${home}:HOME`, () => page.homeOdds), label(`in${index}_1`, `${home}:DRAW`, () => '3.20'), label(`in${index}_2`, `${home}:AWAY`, () => '3.40')];
        if (/Over_?Under/.test(m)) {
            const suffix = page.namedLabels ? ['_over1', '_under1'] : ['_a', '_b'];
            return [label(`${m}_${index}${suffix[0]}`, `${home}:${m}:OVER`, () => page.overOdds[index]), label(`${m}_${index}${suffix[1]}`, `${home}:UNDER`, () => '3.00')];
        }
        return [label(`m${index}_gg`, `${home}:GG`, () => page.ggOdds), label(`m${index}_ng`, `${home}:NG`, () => page.ngOdds)];
    };
    return el({
        innerText: `${home} v ${away}`,
        querySelectorAll: sel => sel === 'label[for]' ? labelsNow() : sel === 'input.checkbox_bets' ? labelsNow().map(l => ({ id: l.forId })) : [],
        querySelector: sel => { const m = sel.match(/^label\[for='(.+)'\]$/); return m ? labelsNow().find(l => l.forId === m[1]) || null : null; }
    });
}
const tabRows = Object.keys(ODD).flatMap(m => [tabRow(0, 'ASV', 'LEE', m), tabRow(1, 'TOT', 'EVE', m)]);
const rows = [makeRow(0, 'ASV', 'LEE'), makeRow(1, 'TOT', 'EVE'), el(), el(), el(), el(), ...tabRows];
const tabEl = v => { const a = mk('tab:' + v); const d = a.dispatchEvent; a.dispatchEvent = e => { if (e.type === 'click') { page.activeTab = v; clicks.push('tab:' + v); } }; a.parentElement = { getAttribute: () => String(!page.tabDead && page.activeTab === v) }; return a; };
rows.slice(2, 6).forEach(r => { r.querySelectorAll = () => []; r.querySelector = () => null; });

const stakeInput = el({ value: '' });
const mk = name => el({ dispatchEvent(e) { if (e.type === 'click') clicks.push(name); } });
const betBtn = mk('place'), confirmBtn = mk('confirm');
const closeBtn = el({ getClientRects: () => page.ticketVisible ? [1] : [], dispatchEvent(e) { if (e.type === 'click') clicks.push('close'); } });
const document = {
    createElement: () => el(), head: el(), body: el(),
    getElementById: id => id === 'bet-select-market' ? select : el(),
    querySelector: sel => { const t = sel.match(/^#tabs-list-market a\[data-value="(.+)"\]$/); if (t) return page.tabs && ODD[t[1]] ? tabEl(t[1]) : null; return docSel(sel); },
    querySelectorAll: sel => sel === 'tr' ? rows : []
};
const docSel = sel => ({ 'iframe': null, '#leagueWeekNumber': { innerText: page.week }, '#inputAmount': stakeInput, '#button_bet': betBtn,
        '#button_bet_ticket': confirmBtn, '#button_sent-ticket-close': closeBtn })[sel] || null;
const ctx = {
    console, document, window: { addEventListener() {} },
    chrome: { storage: { local: {
        get: async keys => Object.fromEntries(keys.filter(k => k in store).map(k => [k, store[k]])),
        set: async obj => { Object.assign(store, JSON.parse(JSON.stringify(obj))); }
    } } },
    fetch: async () => ({ ok: true, status: 200, json: async () => ({}) }),
    MouseEvent: class { constructor(type) { this.type = type; } }, Event: class { constructor(type) { this.type = type; } },
    ResizeObserver: class { observe() {} },
    setInterval() {}, setTimeout: (fn, ms) => { clock += ms; setImmediate(fn); },
    Date: class extends Date { static now() { return clock; } }
};
vm.createContext(ctx);
// Chrome loads api-base.js before content.js (manifest.json).
vm.runInContext(fs.readFileSync(require('path').join(require('path').dirname(process.argv[2]), 'api-base.js'), 'utf8'), ctx);
vm.runInContext(fs.readFileSync(process.argv[2], 'utf8') + '\nglobalThis.executeBets = executeBets;', ctx);

const A = { home_team: 'ASV', away_team: 'LEE', prediction: 'HOME' };
const B = { home_team: 'TOT', away_team: 'EVE', prediction: 'AWAY' };
let weekNo = 5;
const payload = (mode, roundId, targets, results = []) => ({ ok: true, serverSupported: true, mode, readyWeek: `Wk ${weekNo}`, roundId, results, targets });
const run = async p => { clicks.length = 0; await ctx.executeBets(p); return clicks.join(','); };
const nextWeek = () => { weekNo++; page.week = `Week ${weekNo}`; };
const BET = ',place,confirm,close';

(async () => {
    Object.assign(store, { botEnabled: true, baseStake: 100, takeProfit: 50000, stopLoss: 0, maxLossStreak: 9, licenseKey: 'k' });

    // Over 1.5 double: both legs of the website pair, on the 1.5 market, odds multiplied.
    assert.equal(await run(payload('OU', 'r1', [A, B])), 'ASV:Over_Under_1_5:OVER,TOT:Over_Under_1_5:OVER' + BET);
    assert.equal(store.pendingBet.mode, 'OU');
    assert.equal(store.pendingBet.profit, 76);            // 100 x (1.30 x 1.35 = 1.76 rounded) - 100
    assert.equal(await run(payload('OU', 'r1', [A, B])), '');   // no repeat on the same week

    // Next week open but the result has not arrived yet: wait, do not bet.
    nextWeek();
    assert.equal(await run(payload('GG', 'r2', [A])), '');
    assert.equal(store.pendingBet.roundId, 'r1');
    // Result arrives as a loss; the website published no Over pair this round -> no bet.
    assert.equal(await run(payload('OU', 'r2', [], [{ round_id: 'r1', ou: 'LOSS' }])), '');
    assert.equal(store.localLossStreak, 1);
    assert.equal(await run(payload('OU', 'r2', [A])), '');      // a single leg is never bet

    // Combined odds under the minimum -> skipped, nothing clicked.
    nextWeek(); page.overOdds = ['1.10', '1.15'];
    assert.equal(await run(payload('OU', 'r3', [A, B])), '');
    assert.equal(store.pendingBet, null);
    // With a lower Min Total Odds setting the same double is bet at the 2.54x stake.
    nextWeek(); store.minOdds = 1.4; page.overOdds = ['1.20', '1.25'];
    assert.equal(await run(payload('OU', 'r4', [A, B])), 'ASV:Over_Under_1_5:OVER,TOT:Over_Under_1_5:OVER' + BET);
    assert.equal(store.pendingBet.stake, 300);            // 100 + 100 lost / (1.50 - 1)
    assert.equal(store.pendingBet.profit, 150);           // the 100 lost + the 50 a base win makes at 1.50

    // Unknown result for the round (score not read): not counted, streak and total unchanged.
    nextWeek(); page.overOdds = ['1.30', '1.35'];
    const before = store.totalProfit;
    assert.equal(await run(payload('NG', 'r5', [A], [{ round_id: 'r4', ou: 'N/A' }])), 'ASV:NG' + BET);
    assert.equal(store.totalProfit, before);
    assert.equal(store.pendingBet.mode, 'NG');
    assert.equal(store.pendingBet.stake, 225);            // still 100 lost, odds now 1.80: 100 + 100 / 0.80

    // NG win, then GG and Win singles.
    nextWeek();
    assert.equal(await run(payload('GG', 'r6', [B], [{ round_id: 'r5', ng: 'WIN' }])), 'TOT:GG' + BET);
    assert.equal(store.localLossStreak, 0);
    assert.equal(store.streakLoss, 0);
    assert.equal(store.pendingBet.stake, 100);            // back to the base stake after a win
    nextWeek();
    assert.equal(await run(payload('1X2', 'r7', [B], [{ round_id: 'r6', gg: 'WIN' }])), 'TOT:AWAY' + BET);
    nextWeek();
    assert.equal(await run(payload('1X2', 'r8', [{ ...A, prediction: 'DRAW' }], [{ round_id: 'r7', '1x2': 'WIN' }])), ''); // draws are never bet

    // Labels without outcome names: fall back to position on a two-outcome row.
    nextWeek(); page.namedLabels = false;
    assert.equal(await run(payload('OU', 'r9', [A, B])), 'ASV:Over_Under_1_5:OVER,TOT:Over_Under_1_5:OVER' + BET);
    page.namedLabels = true;

    // The page did not switch market (rows still show GG/NG): the Over double is not bet on them.
    nextWeek(); page.stuck = true;
    assert.equal(await run(payload('OU', 'r9b', [A, B], [{ round_id: 'r9', ou: 'WIN' }])), '');
    page.stuck = false; nextWeek();
    assert.equal(await run(payload('OU', 'r9b', [A, B])), 'ASV:Over_Under_1_5:OVER,TOT:Over_Under_1_5:OVER' + BET);
    nextWeek();
    assert.equal(await run(payload('GG', 'r9c', [A], [{ round_id: 'r9b', ou: 'WIN' }])), 'ASV:GG' + BET);
    store.pendingBet = null;

    // Market named differently in the menu is still found by its text.
    nextWeek(); page.options = ['Match_Result', 'OverUnder15', 'Over_Under_2_5', 'GoalGoal_NoGoal'];
    assert.equal(await run(payload('OU', 'r10', [A, B], [{ round_id: 'r9', ou: 'WIN' }])), 'ASV:OverUnder15:OVER,TOT:OverUnder15:OVER' + BET);

    // Bet9ja has no Over 1.5 market at all: stop, never bet another market instead.
    nextWeek(); page.options = ['Match_Result', 'Over_Under_2_5', 'HomeAwayScores_Over_Under_1_5', 'GoalGoal_NoGoal'];
    assert.equal(await run(payload('OU', 'r11', [A, B], [{ round_id: 'r10', ou: 'WIN' }])), '');
    assert.equal(store.botEnabled, false);

    // Ticket dialog never appears: stop and record nothing.
    nextWeek(); page.options.push('Over_Under_1_5'); page.ticketVisible = false; store.botEnabled = true;
    assert.equal(await run(payload('GG', 'r12', [A])), 'ASV:GG,place,confirm');
    assert.equal(store.botEnabled, false);
    assert.equal(store.pendingBet, null);

    // Result never published (generator restarted mid-round): waits through the next week,
    // then drops the bet uncounted and carries on betting.
    nextWeek(); page.ticketVisible = true; store.botEnabled = true;
    assert.equal(await run(payload('GG', 'r12b', [A])), 'ASV:GG' + BET);
    const held = store.totalProfit;
    nextWeek();
    assert.equal(await run(payload('GG', 'r12c', [A])), '');
    nextWeek();
    assert.equal(await run(payload('GG', 'r12d', [A])), 'ASV:GG' + BET);
    assert.equal(store.pendingBet.roundId, 'r12d');
    assert.equal(store.totalProfit, held);
    store.pendingBet = null;

    // Market control without a readable option list: the known values are set directly.
    nextWeek(); const realOptions = page.options; page.options = [];
    assert.equal(await run(payload('1X2', 'r12e', [A])), 'ASV:HOME' + BET);
    store.pendingBet = null; nextWeek();
    assert.equal(await run(payload('OU', 'r12f', [A, B])), 'ASV:Over_Under_1_5:OVER,TOT:Over_Under_1_5:OVER' + BET);
    store.pendingBet = null; page.options = realOptions;

    // Over 2.5 single: chosen from the market menu, the Over button, one match, settled from "o25".
    nextWeek(); page.overOdds = ['1.80', '1.90'];
    assert.equal(await run(payload('O25', 'o1', [B])), 'TOT:Over_Under_2_5:OVER' + BET);
    assert.equal(store.pendingBet.mode, 'O25');
    assert.equal(select.value, 'Over_Under_2_5');
    nextWeek();
    assert.equal(await run(payload('O25', 'o2', [A], [{ round_id: 'o1', o25: 'WIN' }])), 'ASV:Over_Under_2_5:OVER' + BET);
    assert.equal(store.localLossStreak, 0);
    assert.equal(store.pendingBet.stake, 100);            // a win puts the stake back to base
    nextWeek();
    assert.equal(await run(payload('O25', 'o3', [], [{ round_id: 'o2', o25: 'LOSS' }])), '');   // no pick this round
    assert.equal(store.localLossStreak, 1);
    // The page has no Over 2.5 market: stop, never bet the 1.5 line instead.
    nextWeek(); page.options = realOptions.filter(option => option !== 'Over_Under_2_5');
    assert.equal(await run(payload('O25', 'o4', [A])), '');
    assert.equal(store.botEnabled, false);
    assert.equal(store.pendingBet, null);
    page.options = realOptions; page.overOdds = ['1.30', '1.35']; store.botEnabled = true;

    // Server without website picks: never bets.
    nextWeek(); page.ticketVisible = true; store.botEnabled = true;
    assert.equal(await run({ ...payload('GG', 'r13', [A]), serverSupported: false }), '');

    // Real Bet9ja layout: the three markets are tabs, the menu lists only the extra markets.
    page.tabs = true; page.activeTab = 'Match_Result'; store.botEnabled = true; store.pendingBet = null; store.minOdds = 0;
    page.options = ['Correct_Score', 'Double_Chance', 'Over_Under_2_5', 'HomeAwayScores_Over_Under_1_5', '1x2Scores_Over_Under_1_5'];
    nextWeek();
    assert.equal(await run(payload('1X2', 't1', [B])), 'TOT:Match_Result:Away' + BET);   // tab already open: no tab click
    store.pendingBet = null; nextWeek();
    assert.equal(await run(payload('NG', 't2', [A])), 'tab:GoalGoal_NoGoal,ASV:GoalGoal_NoGoal:NG' + BET);
    store.pendingBet = null; nextWeek();
    assert.equal(await run(payload('GG', 't3', [A])), 'ASV:GoalGoal_NoGoal:GG' + BET);
    store.pendingBet = null; nextWeek(); store.minOdds = 1.4;
    assert.equal(await run(payload('OU', 't4', [A, B])), 'tab:Over_Under_1_5,ASV:Over_Under_1_5:Over,TOT:Over_Under_1_5:Over' + BET);
    // Under 1.5 single: same tab as Over 1.5, the Under button, one match.
    store.pendingBet = null; nextWeek(); store.minOdds = 0;
    assert.equal(await run(payload('UN', 't4u', [B])), 'TOT:Over_Under_1_5:Under' + BET);
    assert.equal(store.pendingBet.mode, 'UN');
    store.pendingBet = null; nextWeek(); page.oddNames = ['a', 'b', 'c'];
    assert.equal(await run(payload('UN', 't4v', [A])), 'ASV:Over_Under_1_5:Under' + BET);
    page.oddNames = null;
    store.pendingBet = null; nextWeek(); store.minOdds = 0;
    assert.equal(await run(payload('1X2', 't5', [A])), 'tab:Match_Result,ASV:Match_Result:Home' + BET);
    // Outcome names the bot does not know: position on the tagged two-outcome row.
    store.pendingBet = null; nextWeek(); page.oddNames = ['a', 'b', 'c'];
    assert.equal(await run(payload('NG', 't6', [A])), 'tab:GoalGoal_NoGoal,ASV:GoalGoal_NoGoal:NG' + BET);
    page.oddNames = null;
    // Tab is marked selected but the table still shows Match Result: nothing is ticked.
    store.pendingBet = null; nextWeek(); page.tabStuck = true;
    assert.equal(await run(payload('OU', 't7', [A, B])), 'tab:Over_Under_1_5');
    page.tabStuck = false;
    // Tab never becomes selected: stop.
    nextWeek(); page.tabDead = true;
    assert.equal(await run(payload('GG', 't8', [A])), 'tab:GoalGoal_NoGoal');
    assert.equal(store.botEnabled, false);
    console.log('ALL SCENARIOS PASSED');
})().catch(e => { console.error(e); process.exit(1); });
