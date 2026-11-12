"""Render the harness in headless Chromium (Playwright) and save screenshots.

    python3 tools/screenshot-harness/shoot.py main=lang=pl&scenario=main
    python3 tools/screenshot-harness/shoot.py dialog=scenario=reading,split,reading

Each shot is `name=<page query>[,<action>...]`. Actions: `reading` opens the
reading dialog and fills it in, `submit` sends it (to the stub in stubs.js;
nothing here talks to eBOK). `split` shoots the light and dark theme on
separate pages and joins them, which a page with an open modal dialog needs.
README images go to docs/images/.
"""

import base64
import mimetypes
from pathlib import Path
import sys

from playwright.sync_api import sync_playwright

HERE = Path(__file__).parent
ROOT = HERE / "out"
DOCS = HERE.parent.parent.parent / "docs" / "images"
README_SHOTS = {
    "card-default": "lang=pl&scenario=main",
    "card-states": "lang=pl&scenario=states",
    "card-layouts": "lang=pl&scenario=layouts",
    "card-reading": "lang=pl&scenario=reading,split,reading",
}

ACTIONS = {
    "reading": """async () => {
        for (const card of document.querySelectorAll('myorlen-ebok-card')) {
            const root = card.shadowRoot;
            root.querySelector('button.add-reading')?.click();
            await card.updateComplete;
            const dialog = root.querySelector('dialog.sheet');
            if (!dialog) continue;
            const input = dialog.querySelector('input[inputmode]');
            input.value = '57';
            input.dispatchEvent(new InputEvent('input'));
            await card.updateComplete;
            dialog.querySelectorAll('input[type=checkbox]').forEach((box) => box.click());
            await card.updateComplete;
        }
    }""",
    "submit": """async () => {
        for (const card of document.querySelectorAll('myorlen-ebok-card')) {
            card.shadowRoot.querySelector('dialog.sheet form')?.requestSubmit();
            await new Promise((r) => setTimeout(r, 200));
        }
    }""",
}


def serve(route):
    path = ROOT / route.request.url.split("harness.local/", 1)[1].split("?", 1)[0]
    if not path.is_file():
        route.fulfill(status=404)
        return
    content_type = mimetypes.guess_type(path.name)[0] or "application/javascript"
    route.fulfill(body=path.read_bytes(), content_type=content_type)


def shoot(browser, name: str, query: str, actions: list[str], full_page: bool) -> bytes:
    page = browser.new_page(viewport={"width": 1100, "height": 900}, device_scale_factor=2)
    page.on("console", lambda m: m.type in ("error", "warning") and print(name, m.text))
    page.on(
        "console", lambda m: m.text.startswith(("callService", "toast")) and print(name, m.text)
    )
    page.on("pageerror", lambda e: print(name, "PAGEERROR", e))
    page.route("http://harness.local/**", serve)
    page.goto(f"http://harness.local/index.html?{query}")
    page.wait_for_timeout(600)
    if full_page:
        # Fit the viewport to the card, so the dialog is centred over it.
        box = page.locator("body").bounding_box()
        page.set_viewport_size({"width": int(box["width"]), "height": max(int(box["height"]), 640)})
        page.reload()
        page.wait_for_timeout(600)
    for action in actions:
        page.evaluate(ACTIONS[action])
        page.wait_for_timeout(400)
    image = page.screenshot() if full_page else page.locator("body").screenshot()
    page.close()
    return image


def join(browser, images: list[bytes]) -> bytes:
    """Put screenshots side by side, top-aligned."""
    # PNG header: width and height are the big-endian integers at bytes 16-24.
    sizes = [
        (int.from_bytes(image[16:20], "big"), int.from_bytes(image[20:24], "big"))
        for image in images
    ]
    page = browser.new_page(
        viewport={"width": sum(w for w, _ in sizes), "height": max(h for _, h in sizes)},
        device_scale_factor=1,
    )
    tags = "".join(
        f'<img style="display:block" src="data:image/png;base64,{base64.b64encode(image).decode()}">'
        for image in images
    )
    page.set_content(
        f'<body style="margin:0;display:flex;width:fit-content;align-items:flex-start;background:#111">{tags}</body>'
    )
    page.wait_for_timeout(200)
    image = page.locator("body").screenshot()
    page.close()
    return image


def main() -> None:
    shots = dict(arg.split("=", 1) for arg in sys.argv[1:])
    target = ROOT if shots else DOCS
    target.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for name, spec in (shots or README_SHOTS).items():
            query, *actions = spec.split(",")
            if "split" in actions:
                actions.remove("split")
                image = join(
                    browser,
                    [
                        shoot(browser, name, f"{query}&theme={theme}", actions, True)
                        for theme in ("light", "dark")
                    ],
                )
            else:
                image = shoot(browser, name, query, actions, False)
            (target / f"{name}.png").write_bytes(image)
        browser.close()


if __name__ == "__main__":
    main()
