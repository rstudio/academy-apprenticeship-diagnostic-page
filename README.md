# Academy Apprenticeship Diagnostic Page

A network diagnostic tool for Posit Academy Apprenticeship learners. Tests whether the user's network can reach all domains required for Academy tutorials to function.

Deployed publicly (no login required) so learners with network issues — and their IT teams — can diagnose connectivity problems.

## Domain Checks

| Category | Domain | Purpose | Probe |
|----------|--------|---------|-------|
| Core | `pub.academy.posit.team` | Academy tutorial site | same-origin asset |
| Core | `key.academy.posit.team` | Keycloak sign-in | OIDC discovery document |
| Core | `login.posit.cloud` | Authentication | image |
| Core | `github.com` | Repository cloning | image |
| R Courses | `webr.r-wasm.org` | webR runtime | `webr.mjs` |
| R Courses | `repo.r-wasm.org` | webR R packages | `Rcpp` `.tgz` (~2 MB), verified intact |
| R Courses | `rstudio.r-universe.dev` | R packages absent from repo.r-wasm.org | `PACKAGES` index |
| R Courses | `r2.ropensci.org` | where R Universe `.tgz` downloads actually redirect to | derived: `learnr` `.tgz` (~1.4 MB), verified against the index's SHA-256 |
| Python Courses | `cdn.jsdelivr.net` | Pyodide runtime | Pyodide `package.json` |
| Python Courses | `pypi.org` | packages absent from the Pyodide distribution | JSON API |
| Python Courses | `files.pythonhosted.org` | where `micropip` downloads wheels from | derived |
| Third-Party | `widget.usersnap.com` | Feedback widget | widget loader |
| Third-Party | `resources.usersnap.com` | Feedback resources | derived image |

Additionally checks **WebSocket** connectivity (`wss://echo.websocket.org/`), which is required for interactive Shiny components.

## Architecture

Python Shiny app with client-side JavaScript checks, so results reflect the learner's actual network. Each check downloads a **real asset the tutorials depend on** — not the bare origin — and asserts on the response.

Four probe methods:

- **`cors`** — `fetch()` the asset and require `response.ok`. Every host checked this way either sends `Access-Control-Allow-Origin` (webR and Pyodide read those bytes cross-origin, so they must) or is same-origin.
- **`image`** — load the asset as an `<img>`, for the few hosts that send no CORS headers. The status code is unreadable, but a proxy that substitutes an HTML block page for the image fails to decode, so `onerror` still catches the block.
- **`runiverse_index`** — try several R versions under `/bin/emscripten/contrib/` and take the first non-empty `PACKAGES`, since which one is populated moves with webR's R release.
- **`package`** — `fetch()` a full-size R package archive and check it arrived intact: it must start with gzip's magic bytes, and then either match the size and SHA-256 published in the index (R Universe) or fully decompress, which checks gzip's own CRC-32 (repo.r-wasm.org, whose index is too large to fetch for one hash).

Package probes time out after 30 seconds and every other check after 12. Each check reports **why** it failed (`HTTP 403`, `Blocked`, `Timed Out`, `Not a package file`, `Download corrupted`) rather than just that it did. The reason is shown in the UI and included in **Copy Results**. When a package check fails, the **Actions Required** section also tells IT to allow `.tgz`/`.gz` file downloads from those domains, not just to allowlist them.

> [!IMPORTANT]
> Do **not** go back to probing the smallest package in an index, or to treating a `200` as proof that a package arrived. Web filters can block or alter downloads by file type or size. A learner's network did exactly that: the page showed all green, because a 16 KB package got through, while their graded tutorials failed with `shared object 'Rcpp.so' not found`. The archive-level tests (`test_block_page_served_as_package_reported_as_error`, `test_damaged_package_reported_as_error`, `test_r_universe_download_checked_against_index_hash`) guard this.

> [!IMPORTANT]
> Do **not** reintroduce `mode: 'no-cors'`. An opaque response resolves for *any* HTTP status, so the original version of this page reported a green check mark for 403, 407 (proxy authentication required) and 502 alike. A learner whose corporate proxy was blocking a package host saw all-green and was told their network was fine. `test_http_403_with_cors_reported_as_error` guards this.

### Derived probes

`r2.ropensci.org`, `files.pythonhosted.org` and `resources.usersnap.com` serve the bytes we care about under content-hashed paths that rotate whenever a package or asset is rebuilt. Pinning a URL would eventually 404 and report a failure the learner does not have, so those probe URLs are discovered from the parent check's response body (the R Universe `PACKAGES` index, the PyPI JSON API, and the Usersnap widget loader respectively). If the parent is unreachable the derived check reports `Not tested` — and its domain is still listed for allowlisting, because a blocked parent almost always means both hosts need it.

Originally based on [posit-dev/cape-workshop-diagnostic-page](https://github.com/posit-dev/cape-workshop-diagnostic-page).

## Local Development

```bash
pip install -r requirements.txt
shiny run app.py
```

The app will be available at http://127.0.0.1:8000.

## Testing

```bash
pip install pytest pytest-playwright
playwright install
pytest test_app.py -v
```

The suite requires network access. Alongside the happy path it simulates each realistic failure mode — HTTP 403/502 from a proxy, an HTML block page served in place of an image or a package, a truncated or modified package archive, a stalled connection, a DNS-level block, and a derived check whose parent is unreachable — and asserts that each one turns the row red (or amber) and names the domain in the allowlist instructions.

`test_all_checks_succeed_on_open_network` is what keeps the probe URLs honest: if a pinned asset 404s or a derivation stops working, that test fails instead of the page quietly reporting a problem the learner does not have.

## Deployment

Deployed to [Posit Connect](https://pub.academy.posit.team) via GitHub Actions. The content is configured as publicly accessible (no login required).
