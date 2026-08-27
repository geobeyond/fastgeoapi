"""Stable names for the generated pygeoapi configuration models.

The models in `_generated.py` are derived from pygeoapi's own JSON
Schema, and the generator names collisions **by position**: `Provider`,
`Provider1`, `Provider2`. Which of those is the *data* provider is
decided by nothing more than where it sits in the schema — so a
reordering upstream would rename things without renaming anything. The
import would still resolve and the model would still validate, against
the wrong shape.

This module is the only place allowed to know those positional names.
Everything else imports from here, so a regeneration that moves them is
a change to one file with tests on it, instead of a silent change of
meaning spread across the codebase.

Regenerate with `nox -s models`; `tests/test_config_models_facade.py`
checks that each alias still points at a model with the expected fields.
"""

from app.pygeoapi.config_models._generated import (
    Provider1 as ProviderDefinition,  # the DATA provider — `Provider` is the organisation
)
from app.pygeoapi.config_models._generated import (
    PygeoapiConfigurationSchema as PygeoapiConfig,
)
from app.pygeoapi.config_models._generated import (
    Resources as ResourceDefinition,
)
from app.pygeoapi.config_models._generated import (
    Server as ServerConfig,
)

__all__ = [
    "ProviderDefinition",
    "PygeoapiConfig",
    "ResourceDefinition",
    "ServerConfig",
]
