# Academy Apprenticeship Diagnostic Page

A network diagnostic tool for Posit Academy Apprenticeship learners. Tests whether the user's network can reach all domains required for Academy tutorials to function.

Deployed publicly (no login required) so learners with network issues — and their IT teams — can diagnose connectivity problems.

## Domain Checks

| Category | Domain | Purpose |
|----------|--------|---------|
| Core | `pub.academy.posit.team` | Academy tutorial site |
| Core | `login.posit.cloud` | Authentication |
| Core | `github.com` | Repository cloning |
| Content Delivery | `webr.r-wasm.org` | webR runtime |
| Content Delivery | `repo.r-wasm.org` | webR R packages |
| Content Delivery | `cdn.jsdelivr.net` | CDN for web dependencies |
| Content Delivery | `rstudio.r-universe.dev` | R packages |
| Third-Party | `widget.usersnap.com` | Feedback widget |
| Third-Party | `resources.usersnap.com` | Feedback resources |

Additionally checks **WebSocket** connectivity (`wss://echo.websocket.org/`), which is required for interactive Shiny components.

## Architecture

Python Shiny app with client-side JavaScript checks. All domain connectivity tests run in the learner's browser using `fetch()` with `mode: 'no-cors'`, ensuring results reflect their actual network conditions. The WebSocket check tests against a public echo server.

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

## Deployment

Deployed to [Posit Connect](https://pub.academy.posit.team) via GitHub Actions. The content is configured as publicly accessible (no login required).
