"""What the tests of the HTML pages share.

No ``app.*`` import in this module.
"""

import json
from pathlib import Path

MANIFEST = {
    "pages/style.css": {"file": "assets/style-4f2a.css", "src": "pages/style.css", "isEntry": True},
    "_config-9c1d.js": {"file": "assets/config-9c1d.js"},
    "pages/api-docs.ts": {
        "file": "assets/api-docs-77aa.js",
        "src": "pages/api-docs.ts",
        "isEntry": True,
        "imports": ["_config-9c1d.js"],
        "css": ["assets/api-docs-77aa.css"],
    },
    "pages/process-run.ts": {
        "file": "assets/process-run-1b3e.js",
        "src": "pages/process-run.ts",
        "isEntry": True,
        "imports": ["_config-9c1d.js"],
    },
    "pages/job-status.ts": {
        "file": "assets/job-status-5e60.js",
        "src": "pages/job-status.ts",
        "isEntry": True,
        "imports": ["_config-9c1d.js"],
    },
}
"""A manifest shaped as Vite writes it, for pages tested without a build."""


def fake_build(directory: Path) -> Path:
    """A compiled-assets directory: the manifest, and the stylesheet it names."""
    (directory / ".vite").mkdir(parents=True)
    (directory / ".vite" / "manifest.json").write_text(json.dumps(MANIFEST))
    (directory / "assets").mkdir()
    (directory / "assets" / "style-4f2a.css").write_text("body { margin: 0; }\n")
    return directory
