"""Authentication exceptions module."""


class AuthenticationError(Exception):
    """This is being raised for exceptions within the auth flow."""

    pass


class Oauth2Error(AuthenticationError):
    """Oauth2 authentication flow exception."""

    pass
