// Where the extension reaches the virtual football server. The domain is used first; the
// server IP is a fallback for when the domain cannot be reached (DNS not set up yet, or a
// certificate problem). While on the fallback, the domain is retried every minute.
const VIRTUAL_API_BASES = ['https://prediction.emmyfxchart.com/virtual-api', 'https://159.65.25.30/virtual-api'];
const VIRTUAL_API_RETRY_PRIMARY_MS = 60 * 1000;
let virtualApiIndex = 0;
let virtualApiFallbackSince = 0;

function virtualApiBase() { return VIRTUAL_API_BASES[virtualApiIndex]; }

// fetch() against the working base. Only a network failure (no response at all) moves on to
// the next base; any HTTP response, including an error status, is returned to the caller.
async function virtualApiFetch(path, options = {}, now = Date.now()) {
    if (virtualApiIndex !== 0 && now - virtualApiFallbackSince >= VIRTUAL_API_RETRY_PRIMARY_MS) virtualApiIndex = 0;
    let lastError;
    for (let attempt = 0; attempt < VIRTUAL_API_BASES.length; attempt++) {
        const index = (virtualApiIndex + attempt) % VIRTUAL_API_BASES.length;
        try {
            const response = await fetch(`${VIRTUAL_API_BASES[index]}${path}`, options);
            if (index !== virtualApiIndex) {
                virtualApiIndex = index;
                if (index !== 0) virtualApiFallbackSince = now;
            }
            return response;
        } catch (error) { lastError = error; }
    }
    throw lastError;
}

if (typeof module !== 'undefined') module.exports = { VIRTUAL_API_BASES, virtualApiFetch, virtualApiBase };
