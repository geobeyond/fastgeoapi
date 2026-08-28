"""The endpoints an editor calls.

Four, and the order inside `save` is the whole point: a document is
checked **before** anything is written. Refusing after writing would
leave the store holding a configuration that cannot start, one webhook
call away from taking the service down — an editor that did that would
be worse than none, because it would have carried the operator
confidently into the failure.

"Checked" is validation, not a build: a dry run costs seconds against a
remote dataset, and making every save wait for one would teach people to
route around it. So it stays a separate endpoint, and `save` answers
with what it did and did not check rather than letting "saved" be read
as "verified".

They answer JSON and are useful without a browser: the CLI calls them,
so can curl, and so can a check in CI on a configuration before it is
merged.
"""

from __future__ import annotations

from dataclasses import asdict

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from app.editor.inspect import Outcome, dry_run, validate_effective, validate_source


def _read(source: str) -> str:
    """Read the configuration document as bytes, decode as written."""
    from app.provider.storage import StorageBridge, load_store, split_source

    base, key = split_source(source)
    return StorageBridge(load_store(base)).read(key).decode("utf-8")


def _write(source: str, text: str) -> None:
    from app.provider.storage import StorageBridge, load_store, split_source

    base, key = split_source(source)
    StorageBridge(load_store(base)).write(key, text.encode("utf-8"))


async def _document_of(request: Request) -> str:
    payload = await request.json()
    document = payload.get("document")
    if not isinstance(document, str):
        raise ValueError("the request must carry a 'document' string")
    return document


def build_routes(source: str) -> list[Route]:
    """The editor's routes, bound to one configuration document."""

    async def get_config(request: Request) -> JSONResponse:
        """The document as written — placeholders and all.

        Deliberately not the effective form: this is what an operator
        edits, and resolving it here would silently invite them to save
        a document with the substitutions baked in.
        """
        return JSONResponse({"source": source, "document": _read(source)})

    async def validate(request: Request) -> JSONResponse:
        try:
            document = await _document_of(request)
        except ValueError as e:
            return JSONResponse({"message": str(e)}, status_code=400)
        return JSONResponse(
            {
                "source": asdict(validate_source(document)),
                "effective": asdict(validate_effective(document)),
            }
        )

    async def preview(request: Request) -> JSONResponse:
        """Build it for real and report what stood up.

        The outcome carries the variables it resolved: this says "it
        builds here", never "it will work there", and hiding the
        difference would invite reading a green as a guarantee it cannot
        give.
        """
        try:
            document = await _document_of(request)
        except ValueError as e:
            return JSONResponse({"message": str(e)}, status_code=400)
        return JSONResponse(asdict(dry_run(document)))

    async def save(request: Request) -> JSONResponse:
        try:
            document = await _document_of(request)
        except ValueError as e:
            return JSONResponse({"message": str(e)}, status_code=400)

        # Checked before written, never after: a refusal that follows a
        # write is no refusal at all — the store would be left holding a
        # configuration that cannot start, one webhook call away from
        # taking the service down.
        #
        # What is NOT done here is a dry run. It costs seconds against a
        # remote dataset, and an editor that made every save wait would
        # teach people to route around it. It stays its own endpoint, and
        # the answer says plainly what was checked rather than letting
        # "saved" be read as "verified".
        for outcome in (validate_source(document), validate_effective(document)):
            checked: Outcome = outcome
            if not checked.ok:
                return JSONResponse(
                    {"message": "the document was not saved", "problems": checked.problems},
                    status_code=422,
                )

        _write(source, document)
        return JSONResponse(
            {
                "saved": True,
                # Writing and putting into service are two gestures
                # (ADR-0008): this one only wrote.
                "activated": False,
                "checked": ["source", "effective"],
                "not_checked": ["dry-run: ask /editor/dry-run before relying on this"],
                "source": source,
            }
        )

    return [
        Route("/editor/config", get_config, methods=["GET"]),
        Route("/editor/config", save, methods=["PUT"]),
        Route("/editor/validate", validate, methods=["POST"]),
        Route("/editor/dry-run", preview, methods=["POST"]),
    ]
