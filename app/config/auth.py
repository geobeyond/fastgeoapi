"""Authn and Authz module."""
from app.config.app import configuration as cfg
from app.auth.auth_jwks import JWKSConfig
from app.auth.auth_jwks import JWKSAuthentication
from app.auth.oidc import OIDCProvider
from fastapi_opa import OPAConfig
from fastapi_opa.auth import OIDCAuthentication
from fastapi_opa.auth import OIDCConfig


# The hostname of your Open Policy Agent instance
opa_host = cfg.OPA_URL
# In this example we use OIDC authentication flow (using Keycloak)
if cfg.OPA_ENABLED:
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
    auth_config = OPAConfig(authentication=oidc_auth, opa_host=opa_host)
elif cfg.JWKS_ENABLED:
    jwks_config = JWKSConfig(jwks_uri=cfg.OIDC_JWKS_ENDPOINT)
    jwks_auth = JWKSAuthentication(jwks_config)
    auth_config = OIDCProvider(authentication=jwks_auth)
