"""Write the dark-scheme artwork from the light SVG sources.

The artwork declares its colours as custom properties with light
fallbacks — `fill="var(--fga-ink, #0A0C10)"` — so in principle the dark
variant is a variable swap and needs no second file.

Two things make a file necessary anyway. The theme embeds the logo with
`<img src>`, and an SVG loaded that way is a separate document the
page's properties never reach. Writing it into the page instead would
fix that, but the traced artwork is roughly 290 KB — the hatching is
vectorised stroke by stroke — and that much markup on every page is
worse than a second asset the browser caches once.

So the swap happens here, and the stylesheet picks the file. The SVG
stays the single source: this only substitutes values the artwork has
already named.

This replaced a script that derived the dark lockup by inverting the
PNG's achromatic pixels. That worked and could not tell a brand colour
from ink — an intermediate version of it repainted the navy gear green
and looked deliberate. Here there is nothing to infer.

    uv run python scripts/theme_logo.py
"""

from __future__ import annotations

import re

# The input is a file this script wrote a line earlier, not anything
# received: the parser is here to catch our own mistake — a stray "<" in
# a comment inside a style block once broke all four files at once — and
# never to read something untrusted.
# ruff: ignore[suspicious-xml-etree-import]
import xml.etree.ElementTree as ET  # nosec B405
from pathlib import Path

IMAGES = Path("docs/images")

SOURCES = ("symbol", "lockup-horizontal", "lockup-stacked", "glyph")

#: What each role becomes on a dark ground. `--fga-ink` is not ink
#: there, which is why the artwork names roles rather than colours.
DARK = {
    "fga-ink": "#F2F2F2",
    "fga-accent": "#7AB51D",
    "fga-surface": "#14171A",
    "fga-detail": "#7ACBEE",
}


def main() -> None:
    """Rewrite every dark variant from its light source."""
    for name in SOURCES:
        source = IMAGES / f"{name}.svg"
        text = source.read_text()
        substituted = 0
        for role, value in DARK.items():
            text, count = re.subn(rf"var\(--{role},\s*#[0-9A-Fa-f]+\)", value, text)
            substituted += count
        if not substituted:
            raise SystemExit(f"{source} declares no --fga-* colours: has the artwork changed?")

        # The standalone rule is meaningless once the values are baked in,
        # and on a light desktop it would fight them.
        text = re.sub(r"\s*<style>.*?</style>", "", text, flags=re.S)

        target = IMAGES / f"{name}-dark.svg"
        target.write_text(text)
        # A broken file must fail here, not in a browser. Same reasoning
        # as the import above: this reads what the line before wrote.
        # ruff: ignore[suspicious-xml-element-tree-usage]
        ET.parse(target)  # nosec B314
        print(f"{name}.svg -> {target.name}  ({substituted} colours)")


if __name__ == "__main__":
    main()
