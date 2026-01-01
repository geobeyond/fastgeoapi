"""Integration tests for OAuth2 authentication using pytest-iam.

These tests use pytest-iam to spin up a real OIDC server and test
the OAuth2 infrastructure including JWKS endpoint accessibility.

Note: Some advanced tests (token decoding, protected endpoints) are skipped
due to incompatibilities between pytest-iam 0.2.0 and Canaille 0.0.74.
The unit tests in test_jwks_token_validation.py cover the JWT validation logic.
"""

import pytest


@pytest.fixture
def iam_jwks_uri(iam_server):
    """Get the JWKS URI from the IAM server."""
    # Canaille exposes JWKS at /oauth/jwks.json
    base_url = iam_server.url.rstrip("/")
    return f"{base_url}/oauth/jwks.json"


@pytest.fixture
def iam_issuer(iam_server):
    """Get the issuer URL from the IAM server."""
    # Issuer is the base URL without trailing slash
    return iam_server.url.rstrip("/")


@pytest.fixture
def iam_openid_config_uri(iam_server):
    """Get the OpenID Connect discovery endpoint."""
    base_url = iam_server.url.rstrip("/")
    return f"{base_url}/.well-known/openid-configuration"


class TestIAMServerIntegration:
    """Test that pytest-iam server works correctly."""

    def test_iam_server_is_running(self, iam_server):
        """Verify IAM server is accessible."""
        assert iam_server.url is not None
        assert iam_server.url.startswith("http://")

    def test_jwks_endpoint_accessible(self, iam_server, iam_jwks_uri):
        """Verify JWKS endpoint is accessible and returns valid keys."""
        import httpx

        response = httpx.get(iam_jwks_uri)
        assert response.status_code == 200
        data = response.json()
        assert "keys" in data
        assert len(data["keys"]) > 0
        # Verify key structure - kty is required per RFC 7517
        key = data["keys"][0]
        assert "kty" in key  # Key type is required
        # Note: 'alg' and 'use' are optional per RFC 7517
        # Canaille may not include them, which is spec-compliant

    def test_openid_configuration_accessible(self, iam_server, iam_openid_config_uri):
        """Verify OpenID Connect discovery endpoint is accessible."""
        import httpx

        response = httpx.get(iam_openid_config_uri)
        assert response.status_code == 200
        data = response.json()
        # Verify required OIDC fields
        assert "issuer" in data
        assert "authorization_endpoint" in data
        assert "token_endpoint" in data
        assert "jwks_uri" in data

    def test_openid_config_jwks_uri_matches(self, iam_server, iam_jwks_uri, iam_openid_config_uri):
        """Verify JWKS URI in OpenID config matches expected endpoint."""
        import httpx

        response = httpx.get(iam_openid_config_uri)
        data = response.json()
        # The jwks_uri should point to the same endpoint
        assert data["jwks_uri"] == iam_jwks_uri


class TestJWKSKeyStructure:
    """Test JWKS key structure for JWT validation compatibility."""

    def test_jwks_contains_rsa_key(self, iam_server, iam_jwks_uri):
        """Verify JWKS contains RSA key suitable for JWT validation."""
        import httpx

        response = httpx.get(iam_jwks_uri)
        data = response.json()

        # Find RSA key
        rsa_keys = [k for k in data["keys"] if k.get("kty") == "RSA"]
        assert len(rsa_keys) > 0, "No RSA keys found in JWKS"

        rsa_key = rsa_keys[0]
        # RSA keys must have n (modulus) and e (exponent)
        assert "n" in rsa_key, "RSA key missing modulus (n)"
        assert "e" in rsa_key, "RSA key missing exponent (e)"

    def test_jwks_key_has_kid(self, iam_server, iam_jwks_uri):
        """Verify JWKS key has kid (key ID) for JWT key selection.

        Note: 'alg' is optional per RFC 7517, but 'kid' is commonly used
        for key selection during JWT validation.
        """
        import httpx

        response = httpx.get(iam_jwks_uri)
        data = response.json()

        # At least one key should have kid specified for key selection
        keys_with_kid = [k for k in data["keys"] if "kid" in k]
        assert len(keys_with_kid) > 0, "No keys with key ID (kid) specified"

        # Kid should be a non-empty string
        kid = keys_with_kid[0]["kid"]
        assert isinstance(kid, str) and len(kid) > 0, "Key ID should be non-empty string"


class TestIAMUserManagement:
    """Test user management in IAM server."""

    def test_create_user(self, iam_server):
        """Verify user can be created in IAM server."""
        import uuid

        from faker import Faker

        fake = Faker()
        with iam_server.app.app_context():
            user = iam_server.models.User(
                user_name=f"testuser-{uuid.uuid4().hex[:8]}",
                family_name=fake.last_name(),
                given_name=fake.first_name(),
                emails=[fake.email()],
                password="testpassword123",
            )
            iam_server.backend.save(user)

            assert user is not None
            assert user.user_name is not None
            assert user.id is not None

            # Cleanup
            iam_server.backend.delete(user)

    def test_user_has_required_attributes(self, iam_server):
        """Verify created user has attributes needed for JWT claims."""
        import uuid

        from faker import Faker

        fake = Faker()
        with iam_server.app.app_context():
            user = iam_server.models.User(
                user_name=f"testuser-{uuid.uuid4().hex[:8]}",
                family_name=fake.last_name(),
                given_name=fake.first_name(),
                emails=[fake.email()],
                password="testpassword123",
            )
            iam_server.backend.save(user)

            # These attributes are typically used in JWT claims
            assert hasattr(user, "user_name")
            assert hasattr(user, "emails")
            assert hasattr(user, "given_name")
            assert hasattr(user, "family_name")

            # Cleanup
            iam_server.backend.delete(user)
