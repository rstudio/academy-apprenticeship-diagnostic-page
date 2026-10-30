const TIMEOUT_MS = 12000;

// Package and runtime probes download real files on purpose (see probeDownload),
// up to 12 MB for webR's R.wasm, so give them longer before reporting a slow
// network as a timeout.
const DOWNLOAD_TIMEOUT_MS = 60000;

// The R Universe package the r2.ropensci.org check downloads. gradethis depends
// on it, so every graded tutorial fetches it, and at ~1.4 MB it is the size of
// the downloads that actually break rather than the smallest one in the index.
const R_UNIVERSE_PROBE_PACKAGE = 'learnr';

// The Pyodide distribution package the "Pyodide Packages" check downloads. Every
// pandas tutorial loads it (~3 MB).
const PYODIDE_PROBE_PACKAGE = 'numpy';

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
// Each deriver gets the parent's response body and URL and returns
// `{ url, expect }`, where `expect` is optional and is passed to probeDownload().
const DERIVERS = {
    // R Universe .tgz downloads 302-redirect to r2.ropensci.org/{sha256}, and the
    // PACKAGES index publishes both the size and the hash, so the download can
    // be verified byte for byte.
    r2_ropensci: (body) => {
        for (const record of body.split(/\n\s*\n/)) {
            const name = /^Package:\s*(\S+)/m.exec(record);
            if (!name || name[1] !== R_UNIVERSE_PROBE_PACKAGE) continue;
            const size = /^Filesize:\s*(\d+)/m.exec(record);
            const sha = /^SHA256:\s*([0-9a-f]{64})/m.exec(record);
            if (!size || !sha) return null;
            return {
                url: 'https://r2.ropensci.org/' + sha[1],
                expect: { bytes: parseInt(size[1], 10), sha256: sha[1] },
            };
        }
        return null;
    },

    // Pyodide's lock file names each distribution package's wheel, relative to
    // the lock file's own URL, with its SHA-256.
    pyodide_packages: (body, parentUrl) => {
        const pkg = (JSON.parse(body).packages || {})[PYODIDE_PROBE_PACKAGE];
        if (!pkg || !pkg.file_name || !pkg.sha256) return null;
        return {
            url: new URL(pkg.file_name, parentUrl).href,
            expect: { sha256: pkg.sha256 },
        };
    },

    // micropip resolves a package through the PyPI JSON API, then downloads the
    // wheel from files.pythonhosted.org. Probe the wheel, which is what micropip
    // installs, not the sdist.
    pythonhosted: (body) => {
        const wheel = (JSON.parse(body).urls || []).find(u =>
            u.packagetype === 'bdist_wheel' &&
            u.url && u.url.indexOf('https://files.pythonhosted.org/') === 0 &&
            u.digests && u.digests.sha256
        );
        if (!wheel) return null;
        return { url: wheel.url, expect: { bytes: wheel.size, sha256: wheel.digests.sha256 } };
    },

    // The Usersnap widget loader script names the image assets it will pull from
    // resources.usersnap.com.
    usersnap_resources: (body) => {
        const match = /https:\/\/resources\.usersnap\.com\/[^"'\s)]+\.png[^"'\s)]*/.exec(body);
        return match ? { url: match[0] } : null;
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
 *
 * `read` is 'text' or 'bytes' to return the body as `result.body`; otherwise the
 * body is drained and discarded.
 */
async function probeCors(url, read, timeoutMs) {
    const controller = new AbortController();
    let timedOut = false;
    const timer = setTimeout(() => {
        timedOut = true;
        controller.abort();
    }, timeoutMs || TIMEOUT_MS);

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
        if (read === 'text') {
            return { status: 'success', detail: '', body: await res.text() };
        }
        const bytes = await res.arrayBuffer();
        if (read === 'bytes') {
            return { status: 'success', detail: '', body: bytes };
        }
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
        const result = await probeCors(baseUrl + '/' + version + '/PACKAGES', 'text');
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

/**
 * Download a package or runtime file and check that it arrived intact.
 *
 * Reaching the host is not enough. A web filter can let small files through but
 * block larger ones, answer with its own block page, or strip files out of an
 * archive it scans. A file that arrives altered fails inside the tutorial with a
 * confusing error (a shared object "not found") while every reachability check
 * stays green. So verify the bytes against the published size and SHA-256 when
 * an index provides them, and otherwise against the file format's own
 * structure (see FORMATS).
 *
 * `wrongTypeDetail` is reported when the response is not the kind of file
 * expected at all, which is what a block page looks like.
 */
async function probeDownload(url, expect, wrongTypeDetail) {
    const result = await probeCors(url, 'bytes', DOWNLOAD_TIMEOUT_MS);
    if (result.status !== 'success') {
        return result;
    }

    const bytes = new Uint8Array(result.body);
    const format = FORMATS.find(f => f.magic.every((b, i) => bytes[i] === b));
    if (!format) {
        console.error('Download probe for ' + url + ' returned an unexpected file type');
        return { status: 'error', detail: wrongTypeDetail };
    }

    let intact;
    if (expect && expect.sha256) {
        intact = (expect.bytes === undefined || bytes.length === expect.bytes) &&
            (!window.crypto || !crypto.subtle || await sha256Hex(result.body) === expect.sha256);
    } else {
        intact = await format.intact(bytes);
    }
    if (!intact) {
        console.error('Download probe for ' + url + ' arrived altered or incomplete');
        return { status: 'error', detail: 'Download corrupted' };
    }
    return { status: 'success', detail: '' };
}

// The file types tutorials download, identified by their leading bytes, each
// with the best integrity check its format allows when no hash is published.
// A block page or other substitute matches none of them.
const FORMATS = [
    // R packages (.tgz).
    { magic: [0x1f, 0x8b], intact: gunzips },
    // Python wheels and the Python standard library (.whl, .zip).
    { magic: [0x50, 0x4b, 0x03, 0x04], intact: zipComplete },
    // The webR and Pyodide runtimes (.wasm).
    { magic: [0x00, 0x61, 0x73, 0x6d], intact: validWasm },
];

async function sha256Hex(buffer) {
    const digest = await crypto.subtle.digest('SHA-256', buffer);
    return Array.from(new Uint8Array(digest), b => b.toString(16).padStart(2, '0')).join('');
}

// Decompressing checks gzip's CRC-32 and length trailer, so a truncated or
// modified archive throws.
async function gunzips(bytes) {
    // Browsers too old to decompress can't run this check. Don't report a
    // failure we can't actually see.
    if (typeof DecompressionStream === 'undefined') {
        return true;
    }
    try {
        const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'));
        await new Response(stream).arrayBuffer();
        return true;
    } catch (error) {
        return false;
    }
}

// A zip ends with an end-of-central-directory record (22 bytes plus an optional
// comment of up to 64 KB) giving the central directory's offset and size, which
// must end exactly where the record starts. A truncated file has no record, and
// a padded or spliced one doesn't add up.
function zipComplete(bytes) {
    const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    const lowest = Math.max(0, bytes.length - 22 - 0xffff);
    for (let i = bytes.length - 22; i >= lowest; i--) {
        if (view.getUint32(i, true) !== 0x06054b50) continue;
        const size = view.getUint32(i + 12, true);
        const offset = view.getUint32(i + 16, true);
        // Zip64 moves the real values elsewhere. Don't fail what we can't read.
        if (size === 0xffffffff || offset === 0xffffffff) return true;
        return offset + size === i;
    }
    return false;
}

// Validation walks every section and function body, so a truncated or damaged
// module fails it.
function validWasm(bytes) {
    if (typeof WebAssembly === 'undefined') {
        return true;
    }
    return WebAssembly.validate(bytes);
}

function runProbe(check, url, expect) {
    if (check.method === 'runiverse_index') {
        return probeRuniverseIndex(url);
    }
    if (check.method === 'image') {
        return probeImage(url);
    }
    if (check.method === 'package') {
        return probeDownload(url, expect, 'Not a package file');
    }
    if (check.method === 'runtime') {
        return probeDownload(url, expect, 'Not a runtime file');
    }
    return probeCors(url, PARENT_IDS.has(check.id) ? 'text' : null);
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
        let target = null;

        if (parent && parent.status === 'success' && parent.body && deriver) {
            const parentUrl = checks.find(c => c.id === check.derived_from).probe;
            try {
                target = deriver(parent.body, new URL(parentUrl, location.href).href);
            } catch (error) {
                console.error('Could not derive a probe URL for ' + check.id + ':', error);
            }
        }

        if (!target) {
            // Say so rather than guessing. If the parent host is blocked this
            // host almost certainly needs allowlisting too, and "!" keeps it in
            // the list of domains to send to IT.
            reportCheck(check.id, 'warning', 'Not tested');
            return;
        }

        const result = await runProbe(check, target.url, target.expect);
        reportCheck(check.id, result.status, result.detail);
    });

    await Promise.all(Object.values(pending).concat(derivedRuns));
}
