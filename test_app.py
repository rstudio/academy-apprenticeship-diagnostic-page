import pytest
import subprocess
import time
import signal
from playwright.sync_api import Page, expect

# Longest a check can take before the client gives up (see TIMEOUT_MS in
# www/script.js), plus room for the 1s render tick.
CHECK_TIMEOUT_MS = 12000

ALL_CHECK_LABELS = [
    "Academy Tutorials",
    "Academy Sign-In",
    "Authentication",
    "GitHub (repo cloning)",
    "webR Runtime",
    "webR Packages",
    "R Universe Package Index",
    "R Universe Package Downloads",
    "Pyodide Runtime (CDN)",
    "Python Package Index",
    "Python Package Downloads",
    "Feedback Widget",
    "Feedback Resources",
]


@pytest.fixture(scope="module")
def shiny_app():
    """Start the Shiny app server for testing."""
    process = subprocess.Popen(
        ["shiny", "run", "app.py", "--port", "8001"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    time.sleep(3)
    yield "http://127.0.0.1:8001"
    process.send_signal(signal.SIGINT)
    process.wait(timeout=5)


def status_row(page: Page, label: str):
    return page.locator(".status-item").filter(has_text=label)


def wait_for_resolution(page: Page, label: str, timeout: int = CHECK_TIMEOUT_MS + 5000):
    """Wait until a check stops saying "Checking..." and return its icon class."""
    icon = status_row(page, label).locator(".status-icon")
    expect(icon).not_to_have_class("status-icon status-checking", timeout=timeout)
    return icon.get_attribute("class")


def status_value(page: Page, label: str) -> str:
    return status_row(page, label).locator(".status-value").text_content()


def test_page_loads(page: Page, shiny_app):
    """Test that the page loads successfully."""
    page.goto(shiny_app)
    expect(page.locator("h1")).to_have_text("Network Diagnostic")
    expect(page.locator(".header-subtitle")).to_contain_text(
        "services required by Posit Academy course sites"
    )
    expect(page.locator(".header-logo")).to_be_visible()


def test_category_headings_present(page: Page, shiny_app):
    """Test that all category group headings are displayed."""
    page.goto(shiny_app)
    page.wait_for_selector(".category-heading", timeout=5000)

    headings = page.locator(".category-heading")
    texts = [headings.nth(i).text_content() for i in range(headings.count())]

    assert "Core Academy Platform" in texts
    assert "R Courses (webR / Quarto Live)" in texts
    assert "Python Courses (Pyodide)" in texts
    assert "Third-Party Services" in texts
    assert "WebSocket Connectivity" in texts


def test_all_diagnostic_items_present(page: Page, shiny_app):
    """Test that all diagnostic items are displayed."""
    page.goto(shiny_app)
    page.wait_for_selector(".status-item", timeout=5000)

    # 13 domain checks + 1 WebSocket + 1 Current Time = 15
    status_items = page.locator(".status-item")
    expect(status_items).to_have_count(15)

    for label in ALL_CHECK_LABELS:
        expect(status_row(page, label)).to_be_visible()

    expect(page.locator("text=WebSockets Available")).to_be_visible()
    expect(page.locator("text=Current Time")).to_be_visible()


def test_client_side_checks_execute(page: Page, shiny_app):
    """Test that every client-side connectivity check resolves."""
    page.goto(shiny_app)

    for label in ALL_CHECK_LABELS:
        css_class = wait_for_resolution(page, label)
        assert css_class is not None
        assert any(
            s in css_class
            for s in ["status-success", "status-error", "status-warning"]
        ), f"{label} should have resolved, got: {css_class}"


def test_websocket_connection(page: Page, shiny_app):
    """Test that WebSocket connectivity check executes."""
    console_messages = []
    page.on(
        "console", lambda msg: console_messages.append(f"{msg.type}: {msg.text}")
    )

    page.goto(shiny_app)
    time.sleep(6)

    ws_item = page.locator(".status-item").filter(has_text="WebSockets Available")
    ws_icon = ws_item.locator(".status-icon")
    ws_class = ws_icon.get_attribute("class")
    assert ws_class is not None
    assert "status-success" in ws_class, (
        f"WebSocket should be available, got: {ws_class}"
    )


def test_time_updates_continuously(page: Page, shiny_app):
    """Test that the time display updates continuously."""
    page.goto(shiny_app)
    time.sleep(1)

    time_item = page.locator(".status-item").filter(has_text="Current Time")
    time_value = time_item.locator(".status-value")
    initial_time = time_value.text_content()

    time.sleep(2)
    updated_time = time_value.text_content()
    assert initial_time != updated_time, "Time should update continuously"


def test_copy_button_exists(page: Page, shiny_app):
    """Test that the Copy Results button is present."""
    page.goto(shiny_app)
    page.wait_for_selector("#copy-results-btn", timeout=5000)
    expect(page.locator("#copy-results-btn")).to_have_text("Copy Results")


def test_copy_results_includes_categories_and_rows(page: Page, shiny_app):
    """Test that copied results carry the category grouping and every check."""
    page.goto(shiny_app)
    for label in ALL_CHECK_LABELS:
        wait_for_resolution(page, label)

    copied = page.evaluate(
        """() => {
            const captured = [];
            const original = navigator.clipboard.writeText;
            navigator.clipboard.writeText = (t) => { captured.push(t); return Promise.resolve(); };
            copyDiagnosticResults();
            navigator.clipboard.writeText = original;
            return captured[0];
        }"""
    )

    assert "Core Academy Platform" in copied
    assert "R Courses (webR / Quarto Live)" in copied
    for label in ALL_CHECK_LABELS:
        assert label in copied, f"{label} missing from copied results"


def test_domain_blocked(page: Page, shiny_app):
    """Test that blocking a domain shows an error status."""
    page.route("**/*github.com/**", lambda route: route.abort())
    page.goto(shiny_app)

    github_class = wait_for_resolution(page, "GitHub (repo cloning)")
    assert "status-error" in github_class, (
        f"GitHub should show error when blocked, got: {github_class}"
    )


def test_http_403_with_cors_reported_as_error(page: Page, shiny_app):
    """A proxy answering 403 must go red, not green.

    Regression test for the original implementation, which used
    `fetch(url, {mode: 'no-cors'})` and reported success unconditionally. An
    opaque response resolves for any status, so 403/407/502 all rendered a green
    check mark and learners were told their network was fine.
    """
    page.route(
        "https://webr.r-wasm.org/**",
        lambda route: route.fulfill(
            status=403,
            content_type="text/html",
            headers={"access-control-allow-origin": "*"},
            body="<html><body>Blocked by corporate proxy</body></html>",
        ),
    )
    page.goto(shiny_app)

    webr_class = wait_for_resolution(page, "webR Runtime")
    assert "status-error" in webr_class, (
        f"webR Runtime should show error on HTTP 403, got: {webr_class}"
    )
    assert status_value(page, "webR Runtime") == "HTTP 403", (
        f"Expected the status code to be surfaced, got: "
        f"'{status_value(page, 'webR Runtime')}'"
    )


def test_http_502_reported_as_error(page: Page, shiny_app):
    """Any non-2xx status must go red, and must say why.

    Whether the browser can read the status (`HTTP 502`) or the CORS check hides
    it first (`Blocked`) depends on the response headers, and CDP-fulfilled
    responses don't reproduce a real proxy's headers faithfully — so accept
    either reason. What matters is that neither is a green check mark.
    """
    page.route(
        "https://repo.r-wasm.org/**",
        lambda route: route.fulfill(
            status=502,
            content_type="text/html",
            body="<html><body>Bad gateway</body></html>",
        ),
    )
    page.goto(shiny_app)

    css_class = wait_for_resolution(page, "webR Packages")
    assert "status-error" in css_class, (
        f"webR Packages should show error on HTTP 502, got: {css_class}"
    )
    assert status_value(page, "webR Packages") in ("HTTP 502", "Blocked")


def test_image_probe_detects_substituted_block_page(page: Page, shiny_app):
    """An HTML block page served in place of an image must fail the image probe."""
    page.route(
        "https://github.com/favicon.ico**",
        lambda route: route.fulfill(
            status=200,
            content_type="text/html",
            body="<html><body>This site is blocked</body></html>",
        ),
    )
    page.goto(shiny_app)

    css_class = wait_for_resolution(page, "GitHub (repo cloning)")
    assert "status-error" in css_class, (
        f"GitHub should show error when the image is swapped for HTML, "
        f"got: {css_class}"
    )


def test_stalled_request_reported_as_timeout(page: Page, shiny_app):
    """A host that accepts the connection and never answers must not hang forever."""
    # Never fulfil or abort: the request stays open until the client's own timeout.
    page.route("https://pypi.org/**", lambda route: None)
    page.goto(shiny_app)

    css_class = wait_for_resolution(page, "Python Package Index")
    assert "status-warning" in css_class, (
        f"A stalled host should time out to a warning, got: {css_class}"
    )
    assert status_value(page, "Python Package Index") == "Timed Out"


def test_derived_check_not_tested_when_parent_blocked(page: Page, shiny_app):
    """A derived check says so when it cannot discover its probe URL."""
    page.route("https://rstudio.r-universe.dev/**", lambda route: route.abort())
    page.goto(shiny_app)

    index_class = wait_for_resolution(page, "R Universe Package Index")
    assert "status-error" in index_class

    downloads_class = wait_for_resolution(page, "R Universe Package Downloads")
    assert "status-warning" in downloads_class, (
        f"r2.ropensci.org should report 'Not tested', got: {downloads_class}"
    )
    assert status_value(page, "R Universe Package Downloads") == "Not tested"


def test_failed_domain_listed_in_allowlist_instructions(page: Page, shiny_app):
    """A failing check must name its domain in the Actions Required list."""
    page.route("https://pypi.org/**", lambda route: route.abort())
    page.goto(shiny_app)

    wait_for_resolution(page, "Python Package Index")
    # The derived check can't run either, so its host should be listed too — wait
    # for it to report before reading the instructions.
    wait_for_resolution(page, "Python Package Downloads")
    page.wait_for_selector(".instructions-container", timeout=5000)

    instructions = page.locator(".instructions-container").text_content()
    assert "pypi.org" in instructions
    assert "files.pythonhosted.org" in instructions


def test_all_checks_succeed_on_open_network(page: Page, shiny_app):
    """On an unrestricted network every check — derived ones included — goes green.

    This is what makes the probe URLs trustworthy: if a pinned asset 404s or a
    derivation stops working, this test fails instead of the page quietly
    reporting a problem the learner does not have.
    """
    page.goto(shiny_app)

    for label in ALL_CHECK_LABELS:
        css_class = wait_for_resolution(page, label)
        assert "status-success" in css_class, (
            f"{label} should succeed on an open network, got: {css_class} "
            f"({status_value(page, label)!r})"
        )

    expect(page.locator(".instructions-container")).to_have_count(0)


def test_websocket_firewall_simulation(browser_type, shiny_app):
    """Test that WebSocket blocking is detected using DNS simulation."""
    args = ["--host-resolver-rules=MAP echo.websocket.org 127.0.0.1"]
    browser = browser_type.launch(args=args)
    context = browser.new_context()
    page = context.new_page()

    try:
        page.goto(shiny_app)
        time.sleep(6)

        ws_item = page.locator(".status-item").filter(has_text="WebSockets Available")
        ws_icon = ws_item.locator(".status-icon")
        ws_class = ws_icon.get_attribute("class")
        assert ws_class is not None
        assert "status-error" in ws_class, (
            f"WebSocket should show error when blocked, got: {ws_class}"
        )

        ws_value = ws_item.locator(".status-value")
        status_text = ws_value.text_content()
        assert status_text == "Blocked", f"Expected 'Blocked', got: '{status_text}'"
    finally:
        context.close()
        browser.close()


def test_dns_level_block_simulation(browser_type, shiny_app):
    """Test detection when a host does not resolve at all (DNS-level block)."""
    args = ["--host-resolver-rules=MAP r2.ropensci.org 127.0.0.1"]
    browser = browser_type.launch(args=args)
    context = browser.new_context()
    page = context.new_page()

    try:
        page.goto(shiny_app)

        css_class = wait_for_resolution(page, "R Universe Package Downloads")
        assert "status-success" not in css_class, (
            f"r2.ropensci.org should not pass when it cannot be reached, "
            f"got: {css_class}"
        )

        instructions = page.locator(".instructions-container")
        expect(instructions).to_contain_text("r2.ropensci.org")
    finally:
        context.close()
        browser.close()
