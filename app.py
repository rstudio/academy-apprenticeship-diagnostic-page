from shiny import App, reactive, render, ui
from shiny.types import SilentException
import datetime
import json
from pathlib import Path

www_dir = Path(__file__).parent / "www"

WEBSOCKET_ECHO_SERVER = "wss://echo.websocket.org/"

# Each check probes a *real asset* the tutorials actually download, not the bare
# origin, and asserts on the response. Two probe methods are used:
#
#   "cors"  - fetch() the asset and require response.ok. Only works on hosts that
#             send Access-Control-Allow-Origin (all of ours do, because webR and
#             Pyodide read these bytes cross-origin) or that are same-origin.
#   "image" - load the asset as an <img>. For hosts without CORS we cannot read a
#             status code, but a proxy that swaps the asset for an HTML block page
#             will fail to decode, so onerror still catches the block.
#
# "derived_from" checks discover their probe URL from the parent check's response
# body. Those hosts serve content under hashed or versioned paths that rotate, so
# pinning a URL would eventually 404 and report a false failure.
CHECKS = [
    # Core Academy Platform
    {
        # Relative on purpose: this app is served from pub.academy.posit.team, so
        # a same-origin fetch needs no CORS headers (Connect sends none) and the
        # check still exercises the host that serves every tutorial.
        "id": "pub_academy",
        "domain": "pub.academy.posit.team",
        "probe": "logo.svg",
        "method": "cors",
        "label": "Academy Tutorials",
        "category": "core",
    },
    {
        "id": "keycloak",
        "domain": "key.academy.posit.team",
        "probe": "https://key.academy.posit.team/realms/master/.well-known/openid-configuration",
        "method": "cors",
        "label": "Academy Sign-In",
        "category": "core",
    },
    {
        "id": "login_posit_cloud",
        "domain": "login.posit.cloud",
        "probe": "https://login.posit.cloud/static/cloud/images/gitHubLogo.svg",
        "method": "image",
        "label": "Authentication",
        "category": "core",
    },
    {
        "id": "github",
        "domain": "github.com",
        "probe": "https://github.com/favicon.ico",
        "method": "image",
        "label": "GitHub (repo cloning)",
        "category": "core",
    },
    # Content Delivery - R courses (webR / Quarto Live)
    {
        "id": "webr_runtime",
        "domain": "webr.r-wasm.org",
        "probe": "https://webr.r-wasm.org/latest/webr.mjs",
        "method": "cors",
        "label": "webR Runtime",
        "category": "content_r",
    },
    {
        "id": "webr_packages",
        "domain": "repo.r-wasm.org",
        "probe": "https://repo.r-wasm.org/bin/emscripten/contrib/4.5/pkgconfig_2.0.3.tgz",
        "method": "cors",
        "label": "webR Packages",
        "category": "content_r",
    },
    {
        # The client appends /{R version}/PACKAGES and tries several versions,
        # because which contrib version is populated moves with webR's R release.
        "id": "r_universe",
        "domain": "rstudio.r-universe.dev",
        "probe": "https://rstudio.r-universe.dev/bin/emscripten/contrib",
        "method": "runiverse_index",
        "label": "R Universe Package Index",
        "category": "content_r",
    },
    {
        # The .tgz URLs on rstudio.r-universe.dev 302-redirect here, so this is
        # where the package bytes (including the 30 MB academyDatasets) come from.
        # Allowlisting r-universe without this host makes tutorials hang forever.
        "id": "r2_ropensci",
        "domain": "r2.ropensci.org",
        "method": "cors",
        "derived_from": "r_universe",
        "label": "R Universe Package Downloads",
        "category": "content_r",
    },
    # Content Delivery - Python courses (Pyodide)
    {
        "id": "cdn_jsdelivr",
        "domain": "cdn.jsdelivr.net",
        # Version matches the pin in the Quarto Live extension's pyodide loader.
        "probe": "https://cdn.jsdelivr.net/pyodide/v0.28.1/full/package.json",
        "method": "cors",
        "label": "Pyodide Runtime (CDN)",
        "category": "content_python",
    },
    {
        "id": "pypi",
        "domain": "pypi.org",
        "probe": "https://pypi.org/pypi/palmerpenguins/json",
        "method": "cors",
        "label": "Python Package Index",
        "category": "content_python",
    },
    {
        # micropip pulls wheels that are not in the Pyodide distribution
        # (gapminder, palmerpenguins, plotnine) from here.
        "id": "pythonhosted",
        "domain": "files.pythonhosted.org",
        "method": "cors",
        "derived_from": "pypi",
        "label": "Python Package Downloads",
        "category": "content_python",
    },
    # Third-Party Services
    {
        "id": "usersnap_widget",
        "domain": "widget.usersnap.com",
        "probe": "https://widget.usersnap.com/global/load/201822a1-3032-4808-b576-11dfd489fb46",
        "method": "cors",
        "label": "Feedback Widget",
        "category": "third_party",
    },
    {
        "id": "usersnap_resources",
        "domain": "resources.usersnap.com",
        "method": "image",
        "derived_from": "usersnap_widget",
        "label": "Feedback Resources",
        "category": "third_party",
    },
]

CATEGORIES = [
    {"id": "core", "title": "Core Academy Platform"},
    {"id": "content_r", "title": "R Courses (webR / Quarto Live)"},
    {"id": "content_python", "title": "Python Courses (Pyodide)"},
    {"id": "third_party", "title": "Third-Party Services"},
]

CLIENT_CONFIG = {
    "websocketEchoServer": WEBSOCKET_ECHO_SERVER,
    "checks": [
        {
            k: c[k]
            for k in ("id", "probe", "method", "derived_from", "domain")
            if k in c
        }
        for c in CHECKS
    ],
}

app_ui = ui.page_fillable(
    ui.tags.head(
        ui.include_css(www_dir / "styles.css"),
        ui.tags.link(rel="icon", type="image/png", href="favicon.png"),
        ui.tags.script(f"const CONFIG = {json.dumps(CLIENT_CONFIG)};"),
        ui.tags.script(src="script.js"),
    ),
    ui.div(
        ui.div(
            ui.tags.img(src="logo.svg", alt="Posit Academy", class_="header-logo"),
            ui.h1("Network Diagnostic", class_="header-title"),
            ui.p(
                "This page checks if your network can reach the services "
                "required by Posit Academy course sites. Please take a moment "
                "to confirm that every item below shows a green check mark.",
                class_="header-subtitle",
            ),
            ui.output_ui("status_items"),
            class_="main-container",
        )
    ),
)


def status_card(title, status, value_text=None):
    if status == "success":
        icon, status_class = "✓", "status-success"
        display_value = ""
    elif status == "warning":
        icon, status_class = "!", "status-warning"
        display_value = "Timed Out"
    elif status == "error":
        icon, status_class = "✗", "status-error"
        display_value = "Failed"
    else:
        icon, status_class = "...", "status-checking"
        display_value = "Checking..."

    if value_text is not None:
        display_value = value_text

    return ui.div(
        ui.div(icon, class_=f"status-icon {status_class}"),
        ui.span(title, class_="status-text"),
        ui.span(display_value, class_="status-value"),
        class_="status-item",
    )


def read_input(input, name, default=None):
    """Read an input, falling back to a default until the client reports in.

    Reading an input that hasn't been set raises SilentException, which aborts the
    whole render — so without this the page stays blank until *every* check has
    finished, instead of filling in as results arrive.
    """
    try:
        value = input[name]()
    except SilentException:
        return default
    return value if value else default


def server(input, output, session):
    @render.ui
    def status_items():
        reactive.invalidate_later(1)
        current_time = datetime.datetime.now().strftime("%H:%M:%S")

        ws_status = read_input(input, "websocket_status", "checking")
        ws_value = "Blocked" if ws_status == "error" else None

        failed_domains = []
        websocket_failed = ws_status not in ("success", "checking")

        ui_elements = []

        for cat in CATEGORIES:
            cat_checks = [c for c in CHECKS if c["category"] == cat["id"]]
            ui_elements.append(ui.h3(cat["title"], class_="category-heading"))

            for check in cat_checks:
                check_status = read_input(input, f"{check['id']}_status", "checking")
                # The client sends a short reason ("HTTP 403", "Timed Out",
                # "Blocked") so support emails say *how* a host failed, not just
                # that it did.
                detail = read_input(input, f"{check['id']}_detail")
                ui_elements.append(
                    status_card(check["label"], check_status, detail)
                )
                if check_status not in ("success", "checking"):
                    failed_domains.append(check["domain"])

        ui_elements.append(ui.h3("WebSocket Connectivity", class_="category-heading"))
        ui_elements.append(status_card("WebSockets Available", ws_status, ws_value))

        ui_elements.append(
            ui.div(
                ui.span("Current Time", class_="status-text"),
                ui.span(current_time, class_="status-value"),
                class_="status-item",
            )
        )

        ui_elements.append(
            ui.p(
                "If any items above do not show a green checkmark, please let "
                "our team know so we can troubleshoot together. Use the "
                '"Copy Results" button to copy the results of your diagnostic '
                "tests to your clipboard, then paste that text into an email to ",
                ui.tags.a("academy@posit.co", href="mailto:academy@posit.co"),
                ".",
                class_="footer-note",
            )
        )

        ui_elements.append(
            ui.div(
                ui.tags.button(
                    "Copy Results",
                    id="copy-results-btn",
                    onclick="copyDiagnosticResults()",
                    class_="copy-btn",
                ),
                class_="copy-btn-container",
            )
        )

        if failed_domains or websocket_failed:
            instruction_elements = []

            if failed_domains:
                instruction_elements.extend(
                    [
                        ui.p(
                            "Your IT department may need to allowlist the following "
                            "domains (HTTPS, port 443) for Posit Academy tutorials "
                            "to work correctly:",
                            class_="instructions",
                        ),
                        ui.tags.ul(
                            [ui.tags.li(d) for d in dict.fromkeys(failed_domains)],
                            class_="instructions",
                        ),
                    ]
                )

            if websocket_failed:
                instruction_elements.append(
                    ui.p(
                        "WebSocket connections appear to be blocked. Please ask "
                        "your IT department to allow WebSocket (WSS) traffic, "
                        "which is required for interactive tutorials.",
                        class_="instructions",
                    )
                )

            ui_elements.append(
                ui.div(
                    ui.br(),
                    ui.h3("⚠️  Actions Required", class_="header-title"),
                    *instruction_elements,
                    class_="instructions-container",
                )
            )

        return ui.div(*ui_elements)


app = App(app_ui, server, static_assets=www_dir)
