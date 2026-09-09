const TIMEOUT_MS = 12000;

// Checks whose response body another check derives its probe URL from.
const PARENT_IDS = new Set(
    CONFIG.checks.filter(c => c.derived_from).map(c => c.derived_from)
);

// Versions to try for the R Universe emscripten index. Only one is populated at
// any time (it tracks webR's R release) and the others answer 200 with an empty
// body, so the client picks the first non-empty one rather than pinning a number
// that would silently start reporting failure after webR upgrades R.
const RUNIVERSE_VERSIONS = ['4.8', '4.7', '4.6', '4.5'];

// Some hosts serve the bytes we care about under content-hashed paths that rotate
// whenever a package is rebuilt. Rather than pin a URL that will eventually 404
// and report a false failure, derive it from the parent check's response body.
const DERIVERS = {
    // R Universe .tgz downloads 302-redirect to r2.ropensci.org/{sha256}, and the
    // PACKAGES index publishes both the size and the hash. Use the smallest
    // package so the probe stays a few tens of KB.
    r2_ropensci: (body) => {
        let best = null;
        for (const record of body.split(/\n\s*\n/)) {
            const size = /^Filesize:\s*(\d+)/m.exec(record);
            const sha = /^SHA256:\s*([0-9a-f]{64})/m.exec(record);
            if (!size || !sha) continue;
            const bytes = parseInt(size[1], 10);
            if (!best || bytes < best.bytes) best = { bytes: bytes, sha: sha[1] };
        }
        return best ? 'https://r2.ropensci.org/' + best.sha : null;
    },

    // micropip resolves a package through the PyPI JSON API, then downloads the
    // wheel from files.pythonhosted.org. Pick the smallest distribution file.
    pythonhosted: (body) => {
        const urls = (JSON.parse(body).urls || [])
            .filter(u => u.url && u.url.indexOf('files.pythonhosted.org') !== -1)
            .sort((a, b) => (a.size || 0) - (b.size || 0));
        return urls.length ? urls[0].url : null;
    },

    // The Usersnap widget loader script names the image assets it will pull from
    // resources.usersnap.com.
    usersnap_resources: (body) => {
        const match = /https:\/\/resources\.usersnap\.com\/[^"'\s)]+\.png[^"'\s)]*/.exec(body);
        return match ? match[0] : null;
    },
};

$(document).on('shiny:connected', function (event) {
    checkWebSocketConnectivity();
    checkConnectivity();
});

function copyDiagnosticResults() {
    const lines = [];

    // Walk headings and rows together in document order so the copied text keeps
    // its grouping — support needs to see which category a failure is in.
    document.querySelectorAll('.category-heading, .status-item').forEach(el => {
        if (el.classList.contains('category-heading')) {
            const heading = el.innerText.trim();
            if (heading) lines.push('', heading);
            return;
        }

        const icon = el.querySelector('.status-icon');
        const text = el.querySelector('.status-text');
        const value = el.querySelector('.status-value');

        if (text) {
            const label = text.innerText.trim();
            const statusText = icon ? icon.innerText.trim() : '';
            const valueText = value ? value.innerText.trim() : '';
            const parts = [label];
            if (statusText) parts.push(statusText);
            if (valueText) parts.push(valueText);
            lines.push(parts.join(' | '));
        }
    });

    const result = lines.join('\n').trim();

    // Also include the "Actions Required" allowlist instructions, if present,
    // so support emails arrive with the remediation steps attached. Kept as a
    // separate section (blank-line separated) from the status checklist.
    let fullText = result;
    const instructions = document.querySelector('.instructions-container');
    if (instructions) {
        const instructionLines = [];
        instructions.querySelectorAll('h3, p.instructions, li').forEach(el => {
            const t = el.innerText.trim();
            if (t) instructionLines.push(t);
        });
        if (instructionLines.length) {
            fullText = result + '\n\n' + instructionLines.join('\n');
        }
    }

    navigator.clipboard.writeText(fullText).then(() => {
        const btn = document.getElementById('copy-results-btn');
        if (btn) {
            const original = btn.innerText;
            btn.innerText = 'Copied!';
            btn.classList.add('copy-btn-success');
            setTimeout(() => {
                btn.innerText = original;
                btn.classList.remove('copy-btn-success');
            }, 2000);
        }
    }).catch(err => {
        console.error('Failed to copy:', err);
    });
}

function checkWebSocketConnectivity() {
    Shiny.setInputValue('websocket_status', 'checking');

    try {
        const ws = new WebSocket(CONFIG.websocketEchoServer);

        const timeout = setTimeout(() => {
            ws.close();
            Shiny.setInputValue('websocket_status', 'error');
            console.error('WebSocket connection timed out');
        }, 5000);

        ws.onopen = () => {
            clearTimeout(timeout);
            ws.close();
            Shiny.setInputValue('websocket_status', 'success');
            console.log('WebSocket connection successful');
        };

        ws.onerror = (error) => {
            clearTimeout(timeout);
            Shiny.setInputValue('websocket_status', 'error');
            console.error('WebSocket connection error:', error);
        };

    } catch (error) {
        Shiny.setInputValue('websocket_status', 'error');
        console.error('WebSocket exception:', error);
    }
}

function reportCheck(id, status, detail) {
    Shiny.setInputValue(id + '_status', status);
    Shiny.setInputValue(id + '_detail', detail || '');
}

// Only needed for image probes: fetch() gets `cache: 'no-store'`, but an <img>
// has no such option and a cached hit would prove nothing about the network.
function addCacheBust(url) {
    return url + (url.indexOf('?') === -1 ? '?' : '&') + 'diagnostic=' + Date.now();
}

/**
 * Fetch a real asset and assert on the response.
 *
 * This deliberately does NOT use `mode: 'no-cors'`. An opaque response resolves
 * for any HTTP status, so the previous version of this page reported a green
 * check mark for 403, 407 (proxy auth required) and 502 alike — exactly the
 * statuses a corporate proxy returns when it is blocking the host. Every domain
 * checked here either sends Access-Control-Allow-Origin or is same-origin, so
 * the status code is readable.
 */
async function probeCors(url, wantBody) {
    const controller = new AbortController();
    let timedOut = false;
    const timer = setTimeout(() => {
        timedOut = true;
        controller.abort();
    }, TIMEOUT_MS);

    try {
        const res = await fetch(url, {
            mode: 'cors',
            cache: 'no-store',
            signal: controller.signal,
        });

        if (!res.ok) {
            return { status: 'error', detail: 'HTTP ' + res.status };
        }

        // Drain the body either way: a proxy can answer 200 and then stall, and
        // that should not read as success.
        if (wantBody) {
            return { status: 'success', detail: '', body: await res.text() };
        }
        await res.arrayBuffer();
        return { status: 'success', detail: '' };
    } catch (error) {
        if (timedOut) {
            return { status: 'warning', detail: 'Timed Out' };
        }
        console.error('Probe failed for ' + url + ':', error);
        return { status: 'error', detail: 'Blocked' };
    } finally {
        clearTimeout(timer);
    }
}

/**
 * Load an asset as an image.
 *
 * For the handful of hosts that send no CORS headers we cannot read a status
 * code. Decoding still catches the realistic failure: a proxy that answers with
 * an HTML block page instead of the image fails to decode and fires onerror.
 */
function probeImage(url) {
    return new Promise((resolve) => {
        const img = new Image();
        const timer = setTimeout(() => {
            img.onload = img.onerror = null;
            img.src = '';
            resolve({ status: 'warning', detail: 'Timed Out' });
        }, TIMEOUT_MS);

        img.onload = () => {
            clearTimeout(timer);
            resolve({ status: 'success', detail: '' });
        };
        img.onerror = () => {
            clearTimeout(timer);
            console.error('Image probe failed for ' + url);
            resolve({ status: 'error', detail: 'Blocked' });
        };

        img.src = addCacheBust(url);
    });
}

async function probeRuniverseIndex(baseUrl) {
    let sawReachable = false;
    let lastFailure = { status: 'error', detail: 'Blocked' };

    for (const version of RUNIVERSE_VERSIONS) {
        const result = await probeCors(baseUrl + '/' + version + '/PACKAGES', true);
        if (result.status === 'success') {
            sawReachable = true;
            if (result.body && result.body.trim()) {
                return result;
            }
        } else {
            lastFailure = result;
        }
    }

    // Reachable but every index was empty: the host is fine, but there is no
    // package to derive an r2.ropensci.org probe from.
    return sawReachable ? { status: 'success', detail: '' } : lastFailure;
}

function runProbe(check, url) {
    if (check.method === 'runiverse_index') {
        return probeRuniverseIndex(url);
    }
    if (check.method === 'image') {
        return probeImage(url);
    }
    return probeCors(url, PARENT_IDS.has(check.id));
}

async function checkConnectivity() {
    const checks = CONFIG.checks;

    checks.forEach(check => reportCheck(check.id, 'checking', ''));

    // Independent checks run in parallel; each derived one waits only on the
    // parent whose response body names its URL, so a single slow host doesn't
    // hold up unrelated rows.
    const direct = checks.filter(c => !c.derived_from);
    const derived = checks.filter(c => c.derived_from);

    const pending = {};
    direct.forEach(check => {
        pending[check.id] = runProbe(check, check.probe).then(result => {
            reportCheck(check.id, result.status, result.detail);
            return result;
        });
    });

    const derivedRuns = derived.map(async (check) => {
        const parent = await pending[check.derived_from];
        const deriver = DERIVERS[check.id];
        let url = null;

        if (parent && parent.status === 'success' && parent.body && deriver) {
            try {
                url = deriver(parent.body);
            } catch (error) {
                console.error('Could not derive a probe URL for ' + check.id + ':', error);
            }
        }

        if (!url) {
            // Say so rather than guessing. If the parent host is blocked this
            // host almost certainly needs allowlisting too, and "!" keeps it in
            // the list of domains to send to IT.
            reportCheck(check.id, 'warning', 'Not tested');
            return;
        }

        const result = await runProbe(check, url);
        reportCheck(check.id, result.status, result.detail);
    });

    await Promise.all(Object.values(pending).concat(derivedRuns));
}
