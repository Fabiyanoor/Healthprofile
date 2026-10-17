from django.conf import settings
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication


class CookieJWTAuthentication(JWTAuthentication):
    """
    User authentication: reads the JWT access token from an HttpOnly cookie.
    Admin accounts are rejected here on purpose. Admins use sessions only,
    so a JWT can never open an admin account.
    """

    def authenticate(self, request):
        raw_token = request.COOKIES.get(settings.JWT_ACCESS_COOKIE)
        if not raw_token:
            return None  # no cookie: the request stays anonymous

        # Raises InvalidToken for expired, tampered or wrong-type tokens
        validated_token = self.get_validated_token(raw_token)
        # Raises AuthenticationFailed if the user is missing or inactive
        user = self.get_user(validated_token)

        # The role comes from the database, never from the token
        if user.role != user.Role.USER:
            raise AuthenticationFailed("This account cannot use user tokens.", code="wrong_role")

        return user, validated_token