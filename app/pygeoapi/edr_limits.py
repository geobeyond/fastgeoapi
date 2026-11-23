"""The server's limit on the values of an EDR answer.

The server's limit comes from the settings. A collection's provider may
lower it, never raise it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.interfaces.providers import EdrLimits

if TYPE_CHECKING:
    from app.config.app import DevConfig, ProdConfig

# The default of FASTGEOAPI_EDR_MAX_VALUES, for when fastgeoapi's settings
# cannot be built.
_DEFAULT_SERVER_EDR_MAX_VALUES = 1_000_000


def get_server_edr_limit(settings: DevConfig | ProdConfig | None) -> int:
    """Get the server's largest answer from fastgeoapi's settings.

    Parameters
    ----------
    settings
        fastgeoapi's settings; None takes those of the running server, or
        their defaults when they cannot be built.

    Returns
    -------
    int
        The most values one EDR query may return.
    """
    if settings is None:
        # Imported here: building the settings needs a configured fastgeoapi,
        # and the document is also built by tools that only have pygeoapi.
        try:
            from app.config.app import configuration
        except (ImportError, ValueError):
            return _DEFAULT_SERVER_EDR_MAX_VALUES
        if configuration is None:
            return _DEFAULT_SERVER_EDR_MAX_VALUES
        settings = configuration
    return settings.FASTGEOAPI_EDR_MAX_VALUES


def clamp_edr_limit(provider_limits: EdrLimits, max_values: int) -> int:
    """Clamp a provider's limit to the server's.

    Parameters
    ----------
    provider_limits
        The limit the collection's provider declares.
    max_values
        The server's limit.

    Returns
    -------
    int
        The smaller of the two; the server's when the provider sets none.
    """
    if provider_limits.max_values is None:
        return max_values
    return min(provider_limits.max_values, max_values)
