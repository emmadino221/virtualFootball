// Domain first, IP fallback on network failure, and back to the domain after a minute.
const assert = require('assert');
const path = require('path');
const calls = [];
let domainUp = false;
global.fetch = async url => {
    calls.push(url);
    if (url.startsWith('https://prediction.emmyfxchart.com') && !domainUp) throw new TypeError('Failed to fetch');
    return { ok: true, status: url.endsWith('/bad') ? 401 : 200, url };
};
const { virtualApiFetch, virtualApiBase } = require(path.join(__dirname, '..', 'bet_auto_extension', 'api-base.js'));
(async () => {
    let t = 1_000_000;
    const r1 = await virtualApiFetch('/get_bets', {}, t);
    assert.equal(r1.url, 'https://159.65.25.30/virtual-api/get_bets');       // domain down: IP used
    assert.equal(virtualApiBase(), 'https://159.65.25.30/virtual-api');
    calls.length = 0; await virtualApiFetch('/sync', {}, t + 3000);
    assert.deepEqual(calls, ['https://159.65.25.30/virtual-api/sync']);       // stays on the IP, no extra attempt
    const r401 = await virtualApiFetch('/bad', {}, t + 4000);
    assert.equal(r401.status, 401);                                          // an HTTP error is returned, not retried
    domainUp = true; calls.length = 0;
    await virtualApiFetch('/sync', {}, t + 61_000);                          // after a minute the domain is tried again
    assert.deepEqual(calls, ['https://prediction.emmyfxchart.com/virtual-api/sync']);
    assert.equal(virtualApiBase(), 'https://prediction.emmyfxchart.com/virtual-api');
    domainUp = false; global.fetch = async () => { throw new TypeError('offline'); };
    await assert.rejects(virtualApiFetch('/sync', {}, t + 62_000), /offline/);  // both down: the error reaches the caller
    console.log('API BASE TESTS PASSED');
})().catch(e => { console.error(e); process.exit(1); });
