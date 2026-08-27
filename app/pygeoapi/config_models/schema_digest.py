"""Identity of the schema the models were generated from.

Written by `scripts/generate_config_models.py`; do not edit by hand.

pygeoapi's schema carries no version — its `$id` points at master — so
content is the only identity available. `tests/test_config_models_drift.py`
compares this against the installed schema and goes red when they part.
"""

from pathlib import Path

#: sha256 of the schema at generation time.
SCHEMA_SHA256 = "5caa10cd9032873aa22c13621fe2bc531b142e24ff6817a551eaeee5e001bfd5"

#: pygeoapi version that shipped it, for the changelog entry.
PYGEOAPI_VERSION = "0.24.0"

#: The copy kept beside the models, so a change can be diffed.
SCHEMA_PATH = Path(__file__).parent / "pygeoapi-config-schema.yml"
