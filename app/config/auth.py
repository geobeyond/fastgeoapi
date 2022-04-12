"""Authn and Authz module"""
from fastapi_opa import OPAConfig
from fastapi_opa.auth import OIDCAuthentication
from fastapi_opa.auth import OIDCConfig

from app.config.app import configuration as cfg


# The hostname of your Open Policy Agent instance
opa_host = cfg.OPA_URL
# In this example we use OIDC authentication flow (using Keycloak)
oidc_config = OIDCConfig(
    well_known_endpoint=cfg.OIDC_WELL_KNOWN_ENDPOINT,
    # well known endpoint
    app_uri=cfg.APP_URI,  # host where this app is running
    # client id of your app configured in the identity provider
    client_id=cfg.OIDC_CLIENT_ID,
    # the client secret retrieved from your identity provider
    client_secret=cfg.OIDC_CLIENT_SECRET,
)
oidc_auth = OIDCAuthentication(oidc_config)
opa_config = OPAConfig(authentication=oidc_auth, opa_host=opa_host)