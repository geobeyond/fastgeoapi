"""Render the screenshots of the configuration editor guide, driving the real editor.

An offline tool for the documentation, not part of the package. It starts
the editor exactly as ``fastgeoapi config edit --augmented`` does — same
application, same token, same page — on a throwaway copy of a
configuration, then drives a browser through the four screens the guide
describes and saves what the browser paints.

Screenshots taken by hand drift from the software; these are regenerated
from the same code the guide documents.

Run it from the repository root, with Playwright borrowed for the run
rather than added to the project:

    uv run --with playwright python scripts/editor_tutorial_screenshots.py

It uses the Chrome already installed on the machine
(``channel="chrome"``); pass ``--chromium`` to use Playwright's own
browser instead, which needs ``playwright install chromium`` once.

Relative data paths inside the configuration are resolved from the
working directory, which is why this is run from the repository root:
the sample configuration points at ``tests/data``.
"""

from __future__ import annotations

import argparse
import os
import shutil
import socket
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "images" / "editor"
SOURCE = ROOT / "pygeoapi-config.yml"
# The document is parameterised, and a dry run resolves the placeholders
# from the environment it runs in. An operator has these in a `.env`;
# without them the screenshots would show a report about unset variables
# rather than about the configuration.
ENVIRONMENT = {
    # A value for the screenshot, not an address anything binds to: the
    # editor itself is on loopback and refuses to be anywhere else.
    "HOST": "0.0.0.0",  # ruff: ignore[hardcoded-bind-all-interfaces]  # nosec B104
    "PORT": "5000",
    "PYGEOAPI_BASEURL": "http://localhost:5000",
    "FASTGEOAPI_CONTEXT": "/geoapi",
}


def free_port() -> int:
    """Ask the kernel for a port nobody is listening on."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def serve(source: Path, port: int) -> str:
    """Start the editor in a background thread and return its session token."""
    import uvicorn

    from app.editor.app import build_authoring_app

    editor = build_authoring_app(host="127.0.0.1", source=str(source), augmented=True)
    server = uvicorn.Server(
        uvicorn.Config(editor, host="127.0.0.1", port=port, log_level="warning")
    )
    threading.Thread(target=server.run, daemon=True).start()
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if getattr(server, "started", False):
            return str(editor.state.editor_token)
        time.sleep(0.1)
    sys.exit("the editor did not come up within 30s")


def shoot(target, name: str) -> None:
    """Save what a page or an element paints, at the scale the docs use."""
    path = OUT / f"{name}.png"
    target.screenshot(path=str(path))
    print(f"{path.relative_to(ROOT)}: {path.stat().st_size // 1024} KB")


def main() -> None:
    """Start the editor on a copy of the configuration and photograph it."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--chromium",
        action="store_true",
        help="use Playwright's own Chromium instead of the installed Chrome",
    )
    args = parser.parse_args()

    # ty: Playwright is borrowed for the run, not a dependency of the project.
    from playwright.sync_api import sync_playwright  # ty: ignore[unresolved-import]

    OUT.mkdir(parents=True, exist_ok=True)
    os.environ.update(ENVIRONMENT)
    # A working copy, named relatively so the header reads as a path
    # rather than as somebody's home directory. Nothing here writes to
    # the repository's own document.
    workdir = Path(".cache", "editor-screenshots")
    workdir.mkdir(parents=True, exist_ok=True)
    source = workdir / "pygeoapi-config.yml"
    shutil.copy(SOURCE, source)

    port = free_port()
    token = serve(source, port)
    base = f"http://127.0.0.1:{port}"

    with sync_playwright() as playwright:
        launch = {"headless": True}
        if not args.chromium:
            launch["channel"] = "chrome"
        browser = playwright.chromium.launch(**launch)
        page = browser.new_page(
            viewport={"width": 1180, "height": 900},
            device_scale_factor=2,
            # The page follows the system preference; the documentation
            # reads in light by default, and a fixed choice also keeps
            # these images the same from one machine to the next.
            color_scheme="light",
        )
        page.goto(base, wait_until="networkidle")

        # 1. The gate. The field is a password box, so the token is dots.
        page.fill("#token", token)
        shoot(page.locator("main"), "00-token")

        # 2. The form, built from the schema the editor serves.
        page.click("button:has-text('Open')")
        page.wait_for_selector("button:has-text('Dry run')", timeout=30_000)
        page.wait_for_timeout(500)
        shoot(page, "01-form")

        # 3. The same document as text, editable rather than a preview.
        #    Scrolled past the licence header this configuration opens
        #    with, to the resources — the part of a document somebody
        #    actually comes here to change.
        page.click("button:has-text('YAML')")
        page.wait_for_timeout(800)
        # The editor only renders the lines it shows, so paging down is
        # both the scroll and the test that we arrived; setting a scroll
        # offset from outside is undone by its own measuring pass.
        page.locator(".cm-content").click()
        for _ in range(10):
            if page.locator(".cm-line", has_text="providers:").count():
                break
            page.keyboard.press("PageDown")
            page.wait_for_timeout(200)
        else:
            sys.exit("the text view never reached the resources")
        # The editor renders a little beyond what it shows, so the line
        # that ended the loop is off the bottom: one more page brings the
        # collections into view.
        page.keyboard.press("PageDown")
        page.wait_for_timeout(400)
        shoot(page, "02-yaml")

        # 4. What only fastgeoapi can answer: it builds, and this is what
        #    it would mount and offer. It really reads one item from each
        #    collection, so it takes a while.
        page.click("button:has-text('Dry run')")
        card = page.locator("div.rounded-xl.border").filter(has_text="Dry run").last
        card.wait_for(state="visible", timeout=180_000)
        page.wait_for_timeout(1_500)
        # The tool list is folded away by default; the whole point of
        # `--augmented` is that it can be read, so open it.
        summary = card.locator("summary")
        if summary.count():
            summary.first.click()
            page.wait_for_timeout(400)
        card.scroll_into_view_if_needed()
        page.wait_for_timeout(500)
        shoot(card, "03-dry-run")

        browser.close()


if __name__ == "__main__":
    main()
