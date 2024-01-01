class AuthenticationException(Exception):
    """This is being raised for exceptions within the auth flow."""

    pass


class Oauth2Exception(AuthenticationException):
    """Oauth2 authentication flow exception."""

    pass
