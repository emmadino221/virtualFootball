// Domain first; IP fallback on network failure or a "not here" status; back to the domain after a minute.
const assert = require('assert');
const path = require('path');
const calls = [];
let domain = 'down';   // 'down' | '404' | 'up' | '401'
global.fetch = async url => {
    calls.push(url);
    if (url.startsWith('https://predictions.emmyfxchart.com')) {
        if (domain === 'down') throw new TypeError('Failed to fetch');
        if (domain === '404') return { ok: false, status: 404, url };
        if (domain === '401') return { ok: false, status: 401, url };
    }
    return { ok: true, status: url.endsWith('/bad') ? 401 : 200, url };
};
const { virtualApiFetch, virtualApiBase } = require(path.join(__dirname, '..', 'bet_auto_extension', 'api-base.js'));
const IP = 'https://159.65.25.30/virtual-api', DOMAIN = 'https://predictions.emmyfxchart.com/virtual-api';
(async () => {
    let t = 1_000_000;
    assert.equal((await virtualApiFetch('/get_bets', {}, t)).url, `${IP}/get_bets`);   // domain down: IP used
    calls.length = 0; await virtualApiFetch('/sync', {}, t + 3000);
    assert.deepEqual(calls, [`${IP}/sync`]);                                           // stays on the IP
    assert.equal((await virtualApiFetch('/bad', {}, t + 4000)).status, 401);           // 401 from the IP is returned

    // Domain answers 404 (its nginx has no /virtual-api/ yet): still falls back to the IP.
    domain = '404'; calls.length = 0;
    const r = await virtualApiFetch('/sync', {}, t + 61_000);
    assert.deepEqual(calls, [`${DOMAIN}/sync`, `${IP}/sync`]);
    assert.equal(r.status, 200);
    assert.equal(virtualApiBase(), IP);

    // Domain fixed: switches back after a minute and stays there.
    domain = 'up'; calls.length = 0;
    await virtualApiFetch('/sync', {}, t + 122_000);
    assert.deepEqual(calls, [`${DOMAIN}/sync`]);
    assert.equal(virtualApiBase(), DOMAIN);

    // A wrong licence key on the domain is a real answer: no fallback.
    domain = '401'; calls.length = 0;
    assert.equal((await virtualApiFetch('/sync', {}, t + 123_000)).status, 401);
    assert.deepEqual(calls, [`${DOMAIN}/sync`]);

    // Both addresses answer 404: the response comes back instead of an exception.
    global.fetch = async url => ({ ok: false, status: 404, url });
    assert.equal((await virtualApiFetch('/sync', {}, t + 124_000)).status, 404);
    // Both unreachable: the network error reaches the caller.
    global.fetch = async () => { throw new TypeError('offline'); };
    await assert.rejects(virtualApiFetch('/sync', {}, t + 125_000), /offline/);
    console.log('API BASE TESTS PASSED');
})().catch(e => { console.error(e); process.exit(1); });
