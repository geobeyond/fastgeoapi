"""Test JWKS token validation for audience and issuer claims.

These tests verify that the JWKSAuthentication class properly validates
JWT claims according to OAuth2/JWT security best practices (RFC 7519, RFC 9700).

The tests use self-signed JWTs with a test RSA key pair to simulate
various token validation scenarios without requiring an external IdP.
"""

import time
from unittest.mock import AsyncMock, patch

import pytest
from authlib.jose import JsonWebKey, jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.auth.auth_jwks import JWKSAuthentication, JWKSConfig
from app.auth.exceptions import Oauth2Error


# Generate a test RSA key pair for signing JWTs
def generate_test_keypair():
    """Generate an RSA key pair for testing."""
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    public_key = private_key.public_key()
    return private_key, public_key


def create_jwks_from_public_key(public_key):
    """Create a JWKS from a public key."""
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    jwk = JsonWebKey.import_key(public_pem, {"kty": "RSA", "use": "sig", "alg": "RS256"})
    return {"keys": [jwk.as_dict()]}


def create_test_token(private_key, claims: dict) -> str:
    """Create a signed JWT with the given claims."""
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    header = {"alg": "RS256", "typ": "JWT"}
    token = jwt.encode(header, claims, private_pem)
    return token.decode("utf-8") if isinstance(token, bytes) else token


# Fixtures
@pytest.fixture
def test_keypair():
    """Provide a test RSA key pair."""
    return generate_test_keypair()


@pytest.fixture
def jwks_config():
    """Provide a JWKS configuration with validation settings."""
    return JWKSConfig(
        jwks_uri="https://test-idp.example.com/.well-known/jwks.json",
        expected_audience="https://api.example.com",
        expected_issuer="https://test-idp.example.com",
    )


@pytest.fixture
def jwks_config_no_validation():
    """Provide a JWKS configuration without audience/issuer validation."""
    return JWKSConfig(
        jwks_uri="https://test-idp.example.com/.well-known/jwks.json",
    )


@pytest.fixture
def jwks_auth(jwks_config):
    """Provide a JWKSAuthentication instance with validation enabled."""
    return JWKSAuthentication(jwks_config)


@pytest.fixture
def jwks_auth_no_validation(jwks_config_no_validation):
    """Provide a JWKSAuthentication instance without validation."""
    return JWKSAuthentication(jwks_config_no_validation)


@pytest.fixture
def valid_claims():
    """Provide valid JWT claims."""
    import uuid

    now = int(time.time())
    return {
        "iss": "https://test-idp.example.com",
        "aud": "https://api.example.com",
        "sub": "user123",
        "exp": now + 3600,
        "iat": now,
        "nbf": now,
        "jti": str(uuid.uuid4()),  # Required by OAuth2Claim model
    }


class TestAudienceValidation:
    """Tests for audience (aud) claim validation."""

    @pytest.mark.asyncio
    async def test_valid_audience_accepted(self, test_keypair, jwks_auth, valid_claims):
        """Token with correct audience should be accepted."""
        private_key, public_key = test_keypair
        jwks = create_jwks_from_public_key(public_key)
        token = create_test_token(private_key, valid_claims)

        with patch.object(jwks_auth, "get_jwks", new_callable=AsyncMock) as mock_jwks:
            mock_jwks.return_value = JsonWebKey.import_key_set(jwks)
            claims = await jwks_auth.decode_token(token)
            assert claims["aud"] == "https://api.example.com"

    @pytest.mark.asyncio
    async def test_wrong_audience_rejected(self, test_keypair, jwks_auth, valid_claims):
        """Token with wrong audience should be rejected."""
        private_key, public_key = test_keypair
        jwks = create_jwks_from_public_key(public_key)

        # Modify claims to have wrong audience
        wrong_claims = valid_claims.copy()
        wrong_claims["aud"] = "https://other-api.example.com"
        token = create_test_token(private_key, wrong_claims)

        with patch.object(jwks_auth, "get_jwks", new_callable=AsyncMock) as mock_jwks:
            mock_jwks.return_value = JsonWebKey.import_key_set(jwks)
            with pytest.raises(Oauth2Error, match=r"[Aa]udience"):
                await jwks_auth.decode_token(token)

    @pytest.mark.asyncio
    async def test_missing_audience_rejected(self, test_keypair, jwks_auth, valid_claims):
        """Token without audience claim should be rejected when validation is enabled."""
        private_key, public_key = test_keypair
        jwks = create_jwks_from_public_key(public_key)

        # Remove audience from claims
        no_aud_claims = valid_claims.copy()
        del no_aud_claims["aud"]
        token = create_test_token(private_key, no_aud_claims)

        with patch.object(jwks_auth, "get_jwks", new_callable=AsyncMock) as mock_jwks:
            mock_jwks.return_value = JsonWebKey.import_key_set(jwks)
            with pytest.raises(Oauth2Error, match=r"[Aa]udience"):
                await jwks_auth.decode_token(token)

    @pytest.mark.asyncio
    async def test_audience_array_with_valid_value(self, test_keypair, jwks_auth, valid_claims):
        """Token with audience as array containing valid value should be accepted."""
        private_key, public_key = test_keypair
        jwks = create_jwks_from_public_key(public_key)

        # Set audience as array
        array_aud_claims = valid_claims.copy()
        array_aud_claims["aud"] = [
            "https://api.example.com",
            "https://other.example.com",
        ]
        token = create_test_token(private_key, array_aud_claims)

        with patch.object(jwks_auth, "get_jwks", new_callable=AsyncMock) as mock_jwks:
            mock_jwks.return_value = JsonWebKey.import_key_set(jwks)
            claims = await jwks_auth.decode_token(token)
            assert "https://api.example.com" in claims["aud"]

    @pytest.mark.asyncio
    async def test_audience_array_without_valid_value(self, test_keypair, jwks_auth, valid_claims):
        """Token with audience array not containing valid value should be rejected."""
        private_key, public_key = test_keypair
        jwks = create_jwks_from_public_key(public_key)

        # Set audience as array without valid value
        wrong_array_claims = valid_claims.copy()
        wrong_array_claims["aud"] = [
            "https://other1.example.com",
            "https://other2.example.com",
        ]
        token = create_test_token(private_key, wrong_array_claims)

        with patch.object(jwks_auth, "get_jwks", new_callable=AsyncMock) as mock_jwks:
            mock_jwks.return_value = JsonWebKey.import_key_set(jwks)
            with pytest.raises(Oauth2Error, match=r"[Aa]udience"):
                await jwks_auth.decode_token(token)


class TestIssuerValidation:
    """Tests for issuer (iss) claim validation."""

    @pytest.mark.asyncio
    async def test_valid_issuer_accepted(self, test_keypair, jwks_auth, valid_claims):
        """Token with correct issuer should be accepted."""
        private_key, public_key = test_keypair
        jwks = create_jwks_from_public_key(public_key)
        token = create_test_token(private_key, valid_claims)

        with patch.object(jwks_auth, "get_jwks", new_callable=AsyncMock) as mock_jwks:
            mock_jwks.return_value = JsonWebKey.import_key_set(jwks)
            claims = await jwks_auth.decode_token(token)
            assert claims["iss"] == "https://test-idp.example.com"

    @pytest.mark.asyncio
    async def test_wrong_issuer_rejected(self, test_keypair, jwks_auth, valid_claims):
        """Token with wrong issuer should be rejected."""
        private_key, public_key = test_keypair
        jwks = create_jwks_from_public_key(public_key)

        # Modify claims to have wrong issuer
        wrong_claims = valid_claims.copy()
        wrong_claims["iss"] = "https://malicious-idp.example.com"
        token = create_test_token(private_key, wrong_claims)

        with patch.object(jwks_auth, "get_jwks", new_callable=AsyncMock) as mock_jwks:
            mock_jwks.return_value = JsonWebKey.import_key_set(jwks)
            with pytest.raises(Oauth2Error, match=r"[Ii]ssuer"):
                await jwks_auth.decode_token(token)

    @pytest.mark.asyncio
    async def test_missing_issuer_rejected(self, test_keypair, jwks_auth, valid_claims):
        """Token without issuer claim should be rejected when validation is enabled."""
        private_key, public_key = test_keypair
        jwks = create_jwks_from_public_key(public_key)

        # Remove issuer from claims
        no_iss_claims = valid_claims.copy()
        del no_iss_claims["iss"]
        token = create_test_token(private_key, no_iss_claims)

        with patch.object(jwks_auth, "get_jwks", new_callable=AsyncMock) as mock_jwks:
            mock_jwks.return_value = JsonWebKey.import_key_set(jwks)
            with pytest.raises(Oauth2Error, match=r"[Ii]ssuer"):
                await jwks_auth.decode_token(token)


class TestBackwardCompatibility:
    """Tests to ensure backward compatibility when validation is not configured."""

    @pytest.mark.asyncio
    async def test_no_validation_accepts_any_audience(
        self, test_keypair, jwks_auth_no_validation, valid_claims
    ):
        """Without validation config, any audience should be accepted."""
        private_key, public_key = test_keypair
        jwks = create_jwks_from_public_key(public_key)

        # Use different audience
        claims = valid_claims.copy()
        claims["aud"] = "https://any-api.example.com"
        token = create_test_token(private_key, claims)

        with patch.object(jwks_auth_no_validation, "get_jwks", new_callable=AsyncMock) as mock_jwks:
            mock_jwks.return_value = JsonWebKey.import_key_set(jwks)
            result = await jwks_auth_no_validation.decode_token(token)
            assert result["aud"] == "https://any-api.example.com"

    @pytest.mark.asyncio
    async def test_no_validation_accepts_any_issuer(
        self, test_keypair, jwks_auth_no_validation, valid_claims
    ):
        """Without validation config, any issuer should be accepted."""
        private_key, public_key = test_keypair
        jwks = create_jwks_from_public_key(public_key)

        # Use different issuer
        claims = valid_claims.copy()
        claims["iss"] = "https://any-issuer.example.com"
        token = create_test_token(private_key, claims)

        with patch.object(jwks_auth_no_validation, "get_jwks", new_callable=AsyncMock) as mock_jwks:
            mock_jwks.return_value = JsonWebKey.import_key_set(jwks)
            result = await jwks_auth_no_validation.decode_token(token)
            assert result["iss"] == "https://any-issuer.example.com"


class TestCognitoCompatibility:
    """Tests for AWS Cognito compatibility (client_id fallback for aud)."""

    @pytest.mark.asyncio
    async def test_cognito_client_id_used_as_audience(
        self, test_keypair, jwks_auth_no_validation, valid_claims
    ):
        """Cognito tokens with client_id should use it as audience fallback."""
        private_key, public_key = test_keypair
        jwks = create_jwks_from_public_key(public_key)

        # Cognito-style token: no aud, but has client_id
        cognito_claims = valid_claims.copy()
        del cognito_claims["aud"]
        cognito_claims["client_id"] = "cognito-client-123"
        token = create_test_token(private_key, cognito_claims)

        with patch.object(jwks_auth_no_validation, "get_jwks", new_callable=AsyncMock) as mock_jwks:
            mock_jwks.return_value = JsonWebKey.import_key_set(jwks)
            result = await jwks_auth_no_validation.decode_token(token)
            # client_id should be used as aud fallback
            assert result.get("aud") == "cognito-client-123"

    @pytest.mark.asyncio
    async def test_cognito_client_id_validated_as_audience(self, test_keypair, valid_claims):
        """When validation is enabled, Cognito client_id should be validated as audience."""
        private_key, public_key = test_keypair
        jwks = create_jwks_from_public_key(public_key)

        # Config expecting the cognito client_id as audience
        config = JWKSConfig(
            jwks_uri="https://test-idp.example.com/.well-known/jwks.json",
            expected_audience="cognito-client-123",
            expected_issuer="https://test-idp.example.com",
        )
        auth = JWKSAuthentication(config)

        # Cognito-style token
        cognito_claims = valid_claims.copy()
        del cognito_claims["aud"]
        cognito_claims["client_id"] = "cognito-client-123"
        token = create_test_token(private_key, cognito_claims)

        with patch.object(auth, "get_jwks", new_callable=AsyncMock) as mock_jwks:
            mock_jwks.return_value = JsonWebKey.import_key_set(jwks)
            result = await auth.decode_token(token)
            assert result.get("aud") == "cognito-client-123"
