// Where the extension reaches the virtual football server. The domain is used first; the
// server IP is a fallback for when the domain cannot be reached (DNS not set up yet, or a
// certificate problem). While on the fallback, the domain is retried every minute.
const VIRTUAL_API_BASES = ['https://predictions.emmyfxchart.com/virtual-api', 'https://159.65.25.30/virtual-api'];
const VIRTUAL_API_RETRY_PRIMARY_MS = 60 * 1000;
let virtualApiIndex = 0;
let virtualApiFallbackSince = 0;

function virtualApiBase() { return VIRTUAL_API_BASES[virtualApiIndex]; }

// Statuses meaning "the virtual service is not behind this address": the route is not served
// there (404, e.g. the domain's nginx lacks /virtual-api/) or the proxy cannot reach it.
const VIRTUAL_API_NOT_HERE = new Set([404, 502, 503, 504]);

// fetch() against the working base. A network failure or a "not here" status moves on to the
// next base; any other response, such as 401 for a wrong licence key, goes to the caller.
async function virtualApiFetch(path, options = {}, now = Date.now()) {
    if (virtualApiIndex !== 0 && now - virtualApiFallbackSince >= VIRTUAL_API_RETRY_PRIMARY_MS) virtualApiIndex = 0;
    let lastError = null, lastResponse = null;
    for (let attempt = 0; attempt < VIRTUAL_API_BASES.length; attempt++) {
        const index = (virtualApiIndex + attempt) % VIRTUAL_API_BASES.length;
        try {
            const response = await fetch(`${VIRTUAL_API_BASES[index]}${path}`, options);
            if (VIRTUAL_API_NOT_HERE.has(response.status) && attempt < VIRTUAL_API_BASES.length - 1) { lastResponse = response; continue; }
            if (index !== virtualApiIndex) {
                virtualApiIndex = index;
                if (index !== 0) virtualApiFallbackSince = now;
            }
            return response;
        } catch (error) { lastError = error; }
    }
    if (lastResponse) return lastResponse;
    throw lastError;
}

if (typeof module !== 'undefined') module.exports = { VIRTUAL_API_BASES, virtualApiFetch, virtualApiBase };
