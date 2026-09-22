from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from rest_framework import permissions, status
from rest_framework.authentication import TokenAuthentication
from rest_framework.authtoken.models import Token
from rest_framework.response import Response
from rest_framework.views import APIView

from core.persist_db import dump_persistent_postgres

from .email_verification import (
    EmailVerificationError,
    issue_and_send_verification_code,
    verify_email_code,
)
from .gmail_send import email_delivery_mode
from .password_reset import (
    GENERIC_DETAIL,
    PasswordResetError,
    request_password_reset,
    reset_password,
)
from .serializers import (
    ChangeEmailSerializer,
    ChangeNameSerializer,
    ChangePasswordSerializer,
    ForgotPasswordSerializer,
    GoogleAuthSerializer,
    LoginSerializer,
    RegisterSerializer,
    ResetPasswordSerializer,
    UserSerializer,
)


class RegisterView(APIView):
    # Flutter web POSTs JSON without an X-CSRFToken. Default SessionAuthentication
    # would 403 whenever a Django session cookie is present (e.g. staff admin login).
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        token, _ = Token.objects.get_or_create(user=user)
        dump_persistent_postgres()
        return Response(
            {"token": token.key, "user": UserSerializer(user).data},
            status=status.HTTP_201_CREATED,
        )


class LoginView(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"].lower().strip()
        password = serializer.validated_data["password"]

        # username == email in our setup (see RegisterSerializer.create)
        user = authenticate(request, username=email, password=password)
        if user is None:
            return Response(
                {"detail": "Invalid email or password."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        token, _ = Token.objects.get_or_create(user=user)
        return Response({"token": token.key, "user": UserSerializer(user).data})


class AuthConfigView(APIView):
    """Public auth config for the Flutter client (Google client ID is not secret)."""

    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        client_id = getattr(settings, "GOOGLE_CLIENT_ID", "") or ""
        return Response(
            {
                "google_configured": bool(client_id),
                "google_client_id": client_id,
                "email_delivery": email_delivery_mode(),
            }
        )


class MeView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response({"user": UserSerializer(request.user).data})


class LogoutView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        # Deletes the token so it can no longer authenticate requests.
        Token.objects.filter(user=request.user).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ChangePasswordView(APIView):
    """Authenticated password change; requires the current password."""

    authentication_classes = [TokenAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        if not request.user.has_usable_password():
            return Response(
                {
                    "detail": (
                        "This account signed in with Google and has no password "
                        "to change."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = ChangePasswordSerializer(
            data=request.data,
            context={"user": request.user},
        )
        serializer.is_valid(raise_exception=True)
        current_password = serializer.validated_data["current_password"]
        new_password = serializer.validated_data["new_password"]

        if not request.user.check_password(current_password):
            return Response(
                {"detail": "Current password is incorrect."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if current_password == new_password:
            return Response(
                {"detail": "New password must be different from the current password."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        request.user.set_password(new_password)
        request.user.save(update_fields=["password"])
        dump_persistent_postgres()
        return Response({"ok": True, "detail": "Password updated."})


class ChangeNameView(APIView):
    """Authenticated display-name change; no password required."""

    authentication_classes = [TokenAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = ChangeNameSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        name = serializer.validated_data["name"]
        first_name, _, last_name = name.partition(" ")
        request.user.first_name = first_name
        request.user.last_name = last_name
        request.user.save(update_fields=["first_name", "last_name"])
        dump_persistent_postgres()
        return Response(
            {
                "ok": True,
                "detail": "Name updated.",
                "user": UserSerializer(request.user).data,
            }
        )


class ChangeEmailView(APIView):
    """Authenticated email change; requires the current password."""

    authentication_classes = [TokenAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        if not request.user.has_usable_password():
            return Response(
                {
                    "detail": (
                        "This account signed in with Google and has no password "
                        "to confirm an email change."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = ChangeEmailSerializer(
            data=request.data,
            context={"user": request.user},
        )
        serializer.is_valid(raise_exception=True)
        new_email = serializer.validated_data["email"]
        current_password = serializer.validated_data["current_password"]

        if not request.user.check_password(current_password):
            return Response(
                {"detail": "Current password is incorrect."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if new_email == (request.user.email or "").lower().strip():
            return Response(
                {"detail": "New email must be different from the current email."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        request.user.username = new_email
        request.user.email = new_email
        request.user.save(update_fields=["username", "email"])

        profile = getattr(request.user, "profile", None)
        if profile is not None:
            profile.email_verified = False
            profile.save(update_fields=["email_verified"])

        dump_persistent_postgres()
        return Response(
            {
                "ok": True,
                "detail": "Email updated.",
                "user": UserSerializer(request.user).data,
            }
        )


class GoogleAuthView(APIView):
    """Exchange a Google ID token for a DRF auth Token.

    Matches Flutter AuthService.signInWithGoogle():
    POST /api/auth/google/  body: { "id_token": "..." }
    -> { "token": "...", "user": { id, email, name, avatar_url } }
    """

    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = GoogleAuthSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        raw_id_token = serializer.validated_data["id_token"]

        client_id = getattr(settings, "GOOGLE_CLIENT_ID", "") or ""
        if not client_id:
            return Response(
                {"detail": "Google Sign-In is not configured on the server."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        try:
            idinfo = google_id_token.verify_oauth2_token(
                raw_id_token,
                google_requests.Request(),
                audience=client_id,
            )
        except ValueError as exc:
            detail = "Invalid Google ID token."
            if settings.DEBUG:
                detail = f"Invalid Google ID token: {exc}"
            return Response(
                {"detail": detail},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        email = (idinfo.get("email") or "").lower().strip()
        if not email:
            return Response(
                {"detail": "Google account did not provide an email address."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not idinfo.get("email_verified", False):
            return Response(
                {"detail": "Google account email is not verified."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        name = (idinfo.get("name") or "").strip() or email.split("@")[0]
        picture = idinfo.get("picture") or ""

        user = User.objects.filter(username=email).first()
        created = False
        if user is None:
            first_name, _, last_name = name.partition(" ")
            user = User(username=email, email=email, first_name=first_name, last_name=last_name)
            user.set_unusable_password()
            user.save()
            created = True
        else:
            # Keep profile fresh without overwriting a deliberately set password account.
            if not user.get_full_name() and name:
                first_name, _, last_name = name.partition(" ")
                user.first_name = first_name
                user.last_name = last_name
                user.save(update_fields=["first_name", "last_name"])

        profile = getattr(user, "profile", None)
        update_fields = []
        if profile is not None and picture and profile.avatar_url != picture:
            profile.avatar_url = picture
            update_fields.append("avatar_url")
        if profile is not None and not profile.email_verified:
            profile.email_verified = True
            update_fields.append("email_verified")
        if profile is not None and update_fields:
            profile.save(update_fields=update_fields)

        token, _ = Token.objects.get_or_create(user=user)
        if created:
            dump_persistent_postgres()
        return Response(
            {"token": token.key, "user": UserSerializer(user).data},
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class _AuthenticatedAuthView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [permissions.IsAuthenticated]


class SendEmailCodeView(_AuthenticatedAuthView):
    """Email a 6-digit code after account creation, before checkout."""

    def post(self, request):
        profile = getattr(request.user, "profile", None)
        if profile is not None and profile.email_verified:
            return Response({"ok": True, "already_verified": True})
        try:
            issued = issue_and_send_verification_code(request.user)
        except EmailVerificationError as exc:
            return Response({"detail": str(exc)}, status=exc.status)
        payload = {
            "ok": True,
            "already_verified": False,
            "email": request.user.email,
            "emailed": issued.emailed,
        }
        return Response(payload)


class ForgotPasswordView(APIView):
    """Email a reset code. Unknown addresses get the same success response."""

    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            request_password_reset(serializer.validated_data["email"])
        except PasswordResetError as exc:
            return Response({"detail": str(exc)}, status=exc.status)
        return Response({"ok": True, "detail": GENERIC_DETAIL})


class ResetPasswordView(APIView):
    """Set a new password with the emailed 6-digit code."""

    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = ResetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            reset_password(
                email=serializer.validated_data["email"],
                code=serializer.validated_data["code"],
                new_password=serializer.validated_data["new_password"],
            )
        except PasswordResetError as exc:
            return Response({"detail": str(exc)}, status=exc.status)
        dump_persistent_postgres()
        return Response(
            {
                "ok": True,
                "detail": "Password updated. You can sign in with your new password.",
            }
        )


class VerifyEmailCodeView(_AuthenticatedAuthView):
    """Confirm the emailed 6-digit code so the member can continue to payment."""

    def post(self, request):
        raw = request.data.get("code") if hasattr(request.data, "get") else None
        try:
            verify_email_code(request.user, str(raw or ""))
        except EmailVerificationError as exc:
            return Response({"detail": str(exc)}, status=exc.status)
        dump_persistent_postgres()
        return Response({"ok": True, "user": UserSerializer(request.user).data})
