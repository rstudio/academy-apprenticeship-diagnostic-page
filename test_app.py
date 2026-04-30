import pytest
import subprocess
import time
import signal
from playwright.sync_api import Page, expect


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
    assert "Content Delivery (webR / Quarto Live)" in texts
    assert "Third-Party Services" in texts
    assert "WebSocket Connectivity" in texts


def test_all_diagnostic_items_present(page: Page, shiny_app):
    """Test that all diagnostic items are displayed."""
    page.goto(shiny_app)
    page.wait_for_selector(".status-item", timeout=5000)

    # 9 domain checks + 1 WebSocket + 1 Current Time = 11
    status_items = page.locator(".status-item")
    expect(status_items).to_have_count(11)

    expect(page.locator("text=Academy Tutorials")).to_be_visible()
    expect(page.locator("text=Authentication")).to_be_visible()
    expect(page.locator("text=GitHub (repo cloning)")).to_be_visible()
    expect(page.locator("text=webR Runtime")).to_be_visible()
    expect(page.locator("text=webR Packages")).to_be_visible()
    expect(page.locator("text=CDN (jsdelivr)")).to_be_visible()
    expect(page.locator("text=R Universe Packages")).to_be_visible()
    expect(page.locator("text=Feedback Widget")).to_be_visible()
    expect(page.locator("text=Feedback Resources")).to_be_visible()
    expect(page.locator("text=WebSockets Available")).to_be_visible()
    expect(page.locator("text=Current Time")).to_be_visible()


def test_client_side_checks_execute(page: Page, shiny_app):
    """Test that client-side connectivity checks execute."""
    page.goto(shiny_app)
    time.sleep(3)

    academy_item = page.locator(".status-item").filter(has_text="Academy Tutorials")
    academy_icon = academy_item.locator(".status-icon")
    academy_class = academy_icon.get_attribute("class")
    assert academy_class is not None
    assert any(
        s in academy_class
        for s in ["status-success", "status-error", "status-warning"]
    ), f"Academy check should have resolved, got: {academy_class}"

    github_item = page.locator(".status-item").filter(has_text="GitHub (repo cloning)")
    github_icon = github_item.locator(".status-icon")
    github_class = github_icon.get_attribute("class")
    assert github_class is not None
    assert any(
        s in github_class
        for s in ["status-success", "status-error", "status-warning"]
    ), f"GitHub check should have resolved, got: {github_class}"


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


def test_domain_blocked(page: Page, shiny_app):
    """Test that blocking a domain shows an error status."""
    page.route("**/*github.com/**", lambda route: route.abort())
    page.goto(shiny_app)
    time.sleep(3)

    github_item = page.locator(".status-item").filter(
        has_text="GitHub (repo cloning)"
    )
    github_icon = github_item.locator(".status-icon")
    github_class = github_icon.get_attribute("class")
    assert github_class is not None
    assert "status-error" in github_class, (
        f"GitHub should show error when blocked, got: {github_class}"
    )


def test_success_scenario(page: Page, shiny_app):
    """Test that checks pass in a normal network environment."""
    page.goto(shiny_app)
    time.sleep(3)

    success_icons = page.locator(".status-icon.status-success")
    count = success_icons.count()
    assert count >= 1, f"Expected at least 1 successful check, got {count}"


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
