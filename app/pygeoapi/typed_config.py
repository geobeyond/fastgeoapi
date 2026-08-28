"""A configuration read twice: as a document, and as a model.

pygeoapi is handed the document it was given — the same object, not a
copy, and never one rebuilt from the model. Our own code reads the
model, which is where types, completion and refactoring live.

Keeping both is what makes independence from pygeoapi *safe* rather than
aspirational. Independence means our code stops depending on the shape
of a `dict`; it does not mean we should be the ones reconstructing that
dict. A `model_validate` → `model_dump` round trip was measured and is
not faithful — 11 differences even with the most careful settings, three
of them turning `datetime` into `str` on extents pygeoapi does date
arithmetic with. Regenerating the document would not crash anything: it
would produce a server that starts, serves, and quietly disagrees with
its own configuration.

So the model may evolve freely — it is ours — while what reaches
pygeoapi is exactly what an operator wrote. On the day something else
serves the data, the model is already here and the document simply stops
being needed.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.pygeoapi.config_models import PygeoapiConfig
from app.pygeoapi.factory import normalize_config


@dataclass(frozen=True)
class TypedConfiguration:
    """A configuration document beside its typed view.

    Attributes
    ----------
    document
        What was loaded, unchanged. This is what pygeoapi receives.
    model
        The same configuration, typed, for our own code to read.
    """

    document: dict
    model: PygeoapiConfig

    @classmethod
    def of(cls, document: dict) -> TypedConfiguration:
        """Validate a configuration document and pair it with its model.

        `normalize_config` is called first, so the refusal stage 1
        introduced cannot be bypassed by coming through here: a document
        that would not build must not become a typed configuration
        either. It also fills the defaults the runtime assumes, and it
        does so **in place** — which is deliberate, because the object
        handed on is the one that was given.
        """
        normalize_config(document)
        return cls(document=document, model=PygeoapiConfig.model_validate(document))
