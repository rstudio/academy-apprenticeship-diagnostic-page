from shiny import App, reactive, render, ui
import datetime
from pathlib import Path

www_dir = Path(__file__).parent / "www"

WEBSOCKET_ECHO_SERVER = "wss://echo.websocket.org/"

CHECKS = [
    # Core Academy Platform
    {"id": "pub_academy", "url": "https://pub.academy.posit.team", "label": "Academy Tutorials", "category": "core"},
    {"id": "login_posit_cloud", "url": "https://login.posit.cloud", "label": "Authentication", "category": "core"},
    {"id": "github", "url": "https://github.com", "label": "GitHub (repo cloning)", "category": "core"},
    # Content Delivery (webR / Quarto Live)
    {"id": "webr_runtime", "url": "https://webr.r-wasm.org", "label": "webR Runtime", "category": "content"},
    {"id": "webr_packages", "url": "https://repo.r-wasm.org", "label": "webR Packages", "category": "content"},
    {"id": "cdn_jsdelivr", "url": "https://cdn.jsdelivr.net", "label": "CDN (jsdelivr)", "category": "content"},
    {"id": "r_universe", "url": "https://rstudio.r-universe.dev", "label": "R Universe Packages", "category": "content"},
    # Third-Party Services
    {"id": "usersnap_widget", "url": "https://widget.usersnap.com", "label": "Feedback Widget", "category": "third_party"},
    {"id": "usersnap_resources", "url": "https://resources.usersnap.com", "label": "Feedback Resources", "category": "third_party"},
    {"id": "wistia", "url": "https://fast.wistia.com", "label": "Video Content", "category": "third_party"},
    # Legacy (scheduled for removal)
    {"id": "posit_academy", "url": "https://posit.academy", "label": "Old Campsite Domain", "category": "legacy"},
    {"id": "rsacdn", "url": "https://rsacdn.link", "label": "Academy CDN", "category": "legacy"},
]

CATEGORIES = [
    {"id": "core", "title": "Core Academy Platform"},
    {"id": "content", "title": "Content Delivery (webR / Quarto Live)"},
    {"id": "third_party", "title": "Third-Party Services"},
    {"id": "legacy", "title": "Legacy (scheduled for removal)"},
]

app_ui = ui.page_fillable(
    ui.tags.head(
        ui.include_css(www_dir / "styles.css"),
        ui.tags.link(rel="icon", type="image/png", href="favicon.png"),
        ui.tags.script(f"""
            const CONFIG = {{
                websocketEchoServer: "{WEBSOCKET_ECHO_SERVER}",
                checks: {str([{"id": c["id"], "url": c["url"], "category": c["category"]} for c in CHECKS]).replace("'", '"')}
            }};
        """),
        ui.tags.script(src="script.js"),
    ),
    ui.div(
        ui.div(
            ui.tags.img(src="logo.svg", alt="Posit Academy", class_="header-logo"),
            ui.h1("Network Diagnostic", class_="header-title"),
            ui.p(
                "This page checks whether your network can reach the services "
                "required by Posit Academy tutorials. Please let us know if any "
                "items below do not show a green check mark.",
                class_="header-subtitle",
            ),
            ui.output_ui("status_items"),
            class_="main-container",
        )
    ),
)


def status_card(title, status, value_text=None, legacy=False):
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

    label_parts = [ui.span(title, class_="status-text")]
    if legacy:
        label_parts.append(ui.span("Legacy", class_="legacy-badge"))

    return ui.div(
        ui.div(icon, class_=f"status-icon {status_class}"),
        *label_parts,
        ui.span(display_value, class_="status-value"),
        class_="status-item",
    )


def server(input, output, session):
    @render.ui
    def status_items():
        reactive.invalidate_later(1)
        current_time = datetime.datetime.now().strftime("%H:%M:%S")

        ws_status = input.websocket_status() if input.websocket_status() else "checking"
        ws_value = "Blocked" if ws_status == "error" else None

        failed_domains = []
        websocket_failed = ws_status not in ("success", "checking")

        ui_elements = []

        for cat in CATEGORIES:
            cat_checks = [c for c in CHECKS if c["category"] == cat["id"]]
            ui_elements.append(ui.h3(cat["title"], class_="category-heading"))

            if cat["id"] == "legacy":
                ui_elements.append(
                    ui.p(
                        "These domains are being phased out but are still "
                        "required for now. Please allowlist them if they fail.",
                        class_="legacy-note",
                    )
                )

            for check in cat_checks:
                check_status = (
                    input[f"{check['id']}_status"]()
                    if input[f"{check['id']}_status"]()
                    else "checking"
                )
                ui_elements.append(
                    status_card(
                        check["label"],
                        check_status,
                        legacy=(cat["id"] == "legacy"),
                    )
                )
                if check_status not in ("success", "checking"):
                    failed_domains.append(check["url"])

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
                            [ui.tags.li(url) for url in failed_domains],
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
