"""Copy the JSON Schemas rashid ships into the reader's core.

Usage: python scripts/sync_schemas.py --commit <sha>

The files are written unchanged under ``fastgeoapi_portolan/catalog/schemas/``
with the layout of ``src/rashid/_schemas/``, and ``SOURCE`` records where and
when they came from. Run it again with a newer commit to refresh them.
"""

from __future__ import annotations

import argparse
import json
import shutil
import urllib.request
from pathlib import Path

REPOSITORY = "portolan-sdi/rashid"
PREFIX = "src/rashid/_schemas/"
TARGET = Path(__file__).parent.parent / "fastgeoapi_portolan" / "catalog" / "schemas"
KEEP = {"__init__.py"}

NOTICE = """These JSON Schemas are copied unchanged from rashid, the Portolan validator
(https://github.com/portolan-sdi/rashid, Apache-2.0). rashid copies them from
the STAC specification, the STAC extensions and the Portolan specification,
each under the license of its own project.
"""


def _get(url: str) -> bytes:
    # The URLs are GitHub API and raw content URLs built from a fixed repository.
    request = urllib.request.Request(  # ruff: ignore[suspicious-url-open-usage] # nosec B310
        url, headers={"User-Agent": "fastgeoapi-portolan"}
    )
    with urllib.request.urlopen(request, timeout=60) as response:  # ruff: ignore[suspicious-url-open-usage] # nosec B310
        return response.read()


def main() -> None:
    """Replace the copied schemas with those of rashid at ``--commit``."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", required=True)
    commit = parser.parse_args().commit

    api = f"https://api.github.com/repos/{REPOSITORY}"
    tree = json.loads(_get(f"{api}/git/trees/{commit}?recursive=1"))
    date = json.loads(_get(f"{api}/commits/{commit}"))["commit"]["committer"]["date"]
    paths = [
        entry["path"]
        for entry in tree["tree"]
        if entry["type"] == "blob" and entry["path"].startswith(PREFIX)
    ]

    for child in TARGET.iterdir():
        if child.name in KEEP:
            continue
        shutil.rmtree(child) if child.is_dir() else child.unlink()
    for path in paths:
        target = TARGET / path.removeprefix(PREFIX)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(_get(f"https://raw.githubusercontent.com/{REPOSITORY}/{commit}/{path}"))
    (TARGET / "SOURCE").write_text(
        f"https://github.com/{REPOSITORY}\ncommit {commit}\ndate {date}\ndirectory {PREFIX}\n",
        encoding="utf-8",
    )
    (TARGET / "NOTICE").write_text(NOTICE, encoding="utf-8")
    print(f"{len(paths)} files from {REPOSITORY}@{commit[:8]}")


if __name__ == "__main__":
    main()
