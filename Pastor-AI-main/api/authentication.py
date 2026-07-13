from rest_framework.authentication import TokenAuthentication


class BearerTokenAuthentication(TokenAuthentication):
    """Accept Authorization: Bearer <token> (Flutter AuthService / ApiClient)."""

    keyword = "Bearer"
