from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.utils import timezone
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from .authentication import CookieJWTAuthentication
from .serializers import LoginSerializer, SignupSerializer, UserPublicSerializer

User = get_user_model()

# The refresh cookie is only sent to /auth/ endpoints, never to the rest of the API
REFRESH_COOKIE_PATH = "/auth/"
INVALID_LOGIN = "Invalid email or password."


def _seconds(delta):
    return int(delta.total_seconds())


def set_access_cookie(response, access_token):
    response.set_cookie(
        settings.JWT_ACCESS_COOKIE,
        str(access_token),
        max_age=_seconds(settings.SIMPLE_JWT["ACCESS_TOKEN_LIFETIME"]),
        httponly=True,  # JavaScript cannot read it
        secure=settings.JWT_COOKIE_SECURE,  # HTTPS only outside development
        samesite=settings.JWT_COOKIE_SAMESITE,  # not sent on cross-site posts
        path="/",
    )


def set_refresh_cookie(response, refresh_token):
    response.set_cookie(
        settings.JWT_REFRESH_COOKIE,
        str(refresh_token),
        max_age=_seconds(settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"]),
        httponly=True,
        secure=settings.JWT_COOKIE_SECURE,
        samesite=settings.JWT_COOKIE_SAMESITE,
        path=REFRESH_COOKIE_PATH,
    )


class SignupView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = SignupSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(UserPublicSerializer(user).data, status=201)


class UserLoginView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Returns None for wrong password, unknown email and inactive users
        user = authenticate(
            request,
            username=serializer.validated_data["email"],
            password=serializer.validated_data["password"],
        )
        # Admins cannot use the user login. Same generic message, nothing leaks.
        if user is None or user.role != User.Role.USER:
            return Response({"detail": INVALID_LOGIN}, status=401)

        user.last_login = timezone.now()
        user.save(update_fields=["last_login"])

        refresh = RefreshToken.for_user(user)  # holds the user id, never the password
        response = Response({"user": UserPublicSerializer(user).data})
        set_access_cookie(response, refresh.access_token)
        set_refresh_cookie(response, refresh)
        return response


class RefreshView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        raw = request.COOKIES.get(settings.JWT_REFRESH_COOKIE)
        if not raw:
            return Response({"detail": "Not authenticated."}, status=401)
        try:
            refresh = RefreshToken(raw)  # checks signature, expiry and token type
            user = User.objects.get(pk=refresh["user_id"])
        except (TokenError, User.DoesNotExist, KeyError, ValueError):
            return Response({"detail": "Session expired. Please log in again."}, status=401)
        if not user.is_active or user.role != User.Role.USER:
            return Response({"detail": "Session expired. Please log in again."}, status=401)

        response = Response({"detail": "Token refreshed."})
        set_access_cookie(response, refresh.access_token)
        return response


class LogoutView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]  # works even when the access token already expired

    def post(self, request):
        response = Response({"detail": "Logged out."})
        response.delete_cookie(
            settings.JWT_ACCESS_COOKIE, path="/", samesite=settings.JWT_COOKIE_SAMESITE
        )
        response.delete_cookie(
            settings.JWT_REFRESH_COOKIE,
            path=REFRESH_COOKIE_PATH,
            samesite=settings.JWT_COOKIE_SAMESITE,
        )
        return response


class MeView(APIView):
    """Who am I? The frontend uses this to know if the user is logged in."""

    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(UserPublicSerializer(request.user).data)