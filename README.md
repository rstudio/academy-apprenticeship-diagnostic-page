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
| R Courses | `webr.r-wasm.org` | webR runtime | `R.wasm` (12 MB compressed) for the pinned webR version, validated as WebAssembly |
| R Courses | `repo.r-wasm.org` | webR R packages | `Rcpp` `.tgz` (~2 MB), verified intact |
| R Courses | `rstudio.r-universe.dev` | R packages absent from repo.r-wasm.org | `PACKAGES` index |
| R Courses | `r2.ropensci.org` | where R Universe `.tgz` downloads actually redirect to | derived: `learnr` `.tgz` (~1.4 MB), verified against the index's SHA-256 |
| Python Courses | `cdn.jsdelivr.net` | Pyodide runtime | `pyodide.asm.wasm` (~3.4 MB compressed) for the pinned Pyodide version, validated as WebAssembly |
| Python Courses | `cdn.jsdelivr.net` | Python standard library | `python_stdlib.zip` (~2.5 MB), checked for a complete zip directory |
| Python Courses | `cdn.jsdelivr.net` | Pyodide package index | `pyodide-lock.json` |
| Python Courses | `cdn.jsdelivr.net` | Pyodide distribution packages (pandas, numpy, matplotlib…) | derived: `numpy` wheel (~3 MB), verified against the lock file's SHA-256 |
| Python Courses | `pypi.org` | packages absent from the Pyodide distribution | JSON API for a pinned `plotnine` release |
| Python Courses | `files.pythonhosted.org` | where `micropip` downloads wheels from | derived: `plotnine` wheel (~1.6 MB), verified against the PyPI size and SHA-256 |
| Third-Party | `widget.usersnap.com` | Feedback widget | widget loader |
| Third-Party | `resources.usersnap.com` | Feedback resources | derived image |

Additionally checks **WebSocket** connectivity (`wss://echo.websocket.org/`), which is required for interactive Shiny components.

## Architecture

Python Shiny app with client-side JavaScript checks, so results reflect the learner's actual network. Each check downloads a **real asset the tutorials depend on** — not the bare origin — and asserts on the response.

Five probe methods:

- **`cors`** — `fetch()` the asset and require `response.ok`. Every host checked this way either sends `Access-Control-Allow-Origin` (webR and Pyodide read those bytes cross-origin, so they must) or is same-origin.
- **`image`** — load the asset as an `<img>`, for the few hosts that send no CORS headers. The status code is unreadable, but a proxy that substitutes an HTML block page for the image fails to decode, so `onerror` still catches the block.
- **`runiverse_index`** — try several R versions under `/bin/emscripten/contrib/` and take the first non-empty `PACKAGES`, since which one is populated moves with webR's R release.
- **`package`** — `fetch()` a full-size package (an R `.tgz` or a Python wheel) and check it arrived intact. It must start with gzip's or zip's magic bytes, then match the SHA-256 (and size, where given) published by its index: R Universe `PACKAGES`, Pyodide's lock file, or the PyPI JSON API. repo.r-wasm.org's index is too large to fetch for one hash, so its archive is fully decompressed instead, which checks gzip's own CRC-32.
- **`runtime`** — the same download check for the webR and Pyodide runtime files, which no index publishes a hash for. A `.wasm` must pass `WebAssembly.validate`, which walks every section and function body. A `.zip` must end in an end-of-central-directory record whose central directory ends exactly where the record starts, so a truncated file fails.

Package and runtime probes time out after 60 seconds and every other check after 12. Each check reports **why** it failed (`HTTP 403`, `Blocked`, `Timed Out`, `Not a package file`, `Not a runtime file`, `Download corrupted`) rather than just that it did. The reason is shown in the UI and included in **Copy Results**. When a package or runtime check fails, the **Actions Required** section also tells IT to allow file downloads (`.wasm`, `.tgz`, `.gz`, `.whl`, `.zip`) from those domains, not just to allowlist them.

A full run downloads about 26 MB: the runtimes and one real package per host. A first visit to an R case-study tutorial downloads about 110 MB, so a network that can't manage this can't run tutorials either.

> [!IMPORTANT]
> Do **not** go back to probing the smallest package in an index (R or Python), probing a small file in place of a runtime, or treating a `200` as proof that a file arrived. Web filters can block or alter downloads by file type or size. A learner's network did exactly that: the page showed all green, because a 16 KB package got through, while their graded tutorials failed with `shared object 'Rcpp.so' not found`. The archive-level tests (`test_block_page_served_as_package_reported_as_error`, `test_damaged_package_reported_as_error`, `test_r_universe_download_checked_against_index_hash`, `test_python_wheel_checked_against_published_hash`, `test_runtime_download_checked_for_integrity`) guard this.

> [!IMPORTANT]
> Do **not** reintroduce `mode: 'no-cors'`. An opaque response resolves for *any* HTTP status, so the original version of this page reported a green check mark for 403, 407 (proxy authentication required) and 502 alike. A learner whose corporate proxy was blocking a package host saw all-green and was told their network was fine. `test_http_403_with_cors_reported_as_error` guards this.

### Derived probes

`r2.ropensci.org`, the Pyodide packages on `cdn.jsdelivr.net`, `files.pythonhosted.org` and `resources.usersnap.com` serve the bytes we care about under content-hashed or versioned paths that rotate whenever a package or asset is rebuilt. Pinning a URL would eventually 404 and report a failure the learner does not have, so those probe URLs are discovered from the parent check's response body (the R Universe `PACKAGES` index, Pyodide's lock file, the PyPI JSON API, and the Usersnap widget loader respectively). Each package index also publishes the package's hash, so the derived package checks verify the download too. If the parent is unreachable the derived check reports `Not tested` — and its domain is still listed for allowlisting, because a blocked parent almost always means both hosts need it.

### Pins to keep in sync

Two versions here must match the pins in the Quarto Live extension's `live.lua` in [academyTutorials](https://github.com/rstudio/academyTutorials):

- the webR version in the `webr_runtime` probe must match `baseUrl`
- the Pyodide version in the `pyodide_runtime`, `python_stdlib` and `cdn_jsdelivr` probes must match `indexURL`

When either is bumped there, bump it here. Otherwise this page checks files that tutorials no longer load. The other pinned files (`Rcpp` in repo.r-wasm.org's 4.5 tree and the `plotnine` release on PyPI) never change, so they need no upkeep. If one disappears, `test_all_checks_succeed_on_open_network` fails.

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
