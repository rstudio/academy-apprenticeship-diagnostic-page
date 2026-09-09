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
| R Courses | `repo.r-wasm.org` | webR R packages | a small `.tgz` |
| R Courses | `rstudio.r-universe.dev` | R packages absent from repo.r-wasm.org | `PACKAGES` index |
| R Courses | `r2.ropensci.org` | where R Universe `.tgz` downloads actually redirect to | derived |
| Python Courses | `cdn.jsdelivr.net` | Pyodide runtime | Pyodide `package.json` |
| Python Courses | `pypi.org` | packages absent from the Pyodide distribution | JSON API |
| Python Courses | `files.pythonhosted.org` | where `micropip` downloads wheels from | derived |
| Third-Party | `widget.usersnap.com` | Feedback widget | widget loader |
| Third-Party | `resources.usersnap.com` | Feedback resources | derived image |

Additionally checks **WebSocket** connectivity (`wss://echo.websocket.org/`), which is required for interactive Shiny components.

## Architecture

Python Shiny app with client-side JavaScript checks, so results reflect the learner's actual network. Each check downloads a **real asset the tutorials depend on** — not the bare origin — and asserts on the response.

Three probe methods:

- **`cors`** — `fetch()` the asset and require `response.ok`. Every host checked this way either sends `Access-Control-Allow-Origin` (webR and Pyodide read those bytes cross-origin, so they must) or is same-origin.
- **`image`** — load the asset as an `<img>`, for the few hosts that send no CORS headers. The status code is unreadable, but a proxy that substitutes an HTML block page for the image fails to decode, so `onerror` still catches the block.
- **`runiverse_index`** — try several R versions under `/bin/emscripten/contrib/` and take the first non-empty `PACKAGES`, since which one is populated moves with webR's R release.

Every check times out after 12 seconds and reports **why** it failed (`HTTP 403`, `Blocked`, `Timed Out`) rather than just that it did — the reason is shown in the UI and included in **Copy Results**.

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

The suite requires network access. Alongside the happy path it simulates each realistic failure mode — HTTP 403/502 from a proxy, an HTML block page served in place of an image, a stalled connection, a DNS-level block, and a derived check whose parent is unreachable — and asserts that each one turns the row red (or amber) and names the domain in the allowlist instructions.

`test_all_checks_succeed_on_open_network` is what keeps the probe URLs honest: if a pinned asset 404s or a derivation stops working, that test fails instead of the page quietly reporting a problem the learner does not have.

## Deployment

Deployed to [Posit Connect](https://pub.academy.posit.team) via GitHub Actions. The content is configured as publicly accessible (no login required).
