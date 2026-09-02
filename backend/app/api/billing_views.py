"""Stripe billing endpoints for Premium subscriptions.

Configure via environment (see config.env.example / tokens.env.example):

  STRIPE_SECRET_KEY=sk_test_...
  STRIPE_PUBLISHABLE_KEY=pk_test_...
  STRIPE_WEBHOOK_SECRET=whsec_...
  STRIPE_PRICE_MONTHLY=price_...   # optional; falls back to inline $15
  STRIPE_PRICE_YEARLY=price_...    # optional; falls back to inline $150
  PUBLIC_APP_URL=https://your-domain   # return URL after checkout
"""

from datetime import datetime, timedelta, timezone as dt_timezone

import logging

import stripe
from django.conf import settings
from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Profile
from .serializers import UserSerializer

logger = logging.getLogger(__name__)


def _stripe_configured() -> bool:
    return bool(getattr(settings, "STRIPE_SECRET_KEY", "") and getattr(settings, "STRIPE_PUBLISHABLE_KEY", ""))


def _mock_checkout_enabled() -> bool:
    """TEMPORARY: fake checkout that gifts Premium until Stripe keys are live.

    Enabled when BILLING_MOCK_CHECKOUT=true/1/yes, OR when unset and Stripe
    is not configured. Set BILLING_MOCK_CHECKOUT=false once Stripe is ready.
    """
    raw = (getattr(settings, "BILLING_MOCK_CHECKOUT", "") or "").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return False
    if raw in {"1", "true", "yes", "on"}:
        return True
    # Default: mock only while Stripe credentials are missing.
    return not _stripe_configured()


def _ensure_stripe() -> None:
    stripe.api_key = settings.STRIPE_SECRET_KEY


def _get_or_create_profile(user: User) -> Profile:
    profile, _ = Profile.objects.get_or_create(user=user)
    return profile


def _line_item_for_period(period: str) -> dict:
    """Prefer configured Price IDs; otherwise create one-off price_data."""
    period = (period or "monthly").lower()
    if period == "yearly":
        price_id = getattr(settings, "STRIPE_PRICE_YEARLY", "") or ""
        if price_id:
            return {"price": price_id, "quantity": 1}
        return {
            "price_data": {
                "currency": "usd",
                "unit_amount": 15000,
                "recurring": {"interval": "year"},
                "product_data": {"name": "Nordin's AI Premium (Yearly)"},
            },
            "quantity": 1,
        }

    price_id = getattr(settings, "STRIPE_PRICE_MONTHLY", "") or ""
    if price_id:
        return {"price": price_id, "quantity": 1}
    return {
        "price_data": {
            "currency": "usd",
            "unit_amount": 1500,
            "recurring": {"interval": "month"},
            "product_data": {"name": "Nordin's AI Premium (Monthly)"},
        },
        "quantity": 1,
    }


def _public_app_url(request) -> str:
    configured = (getattr(settings, "PUBLIC_APP_URL", "") or "").rstrip("/")
    if configured:
        return configured
    origin = request.headers.get("Origin") or request.headers.get("Referer") or ""
    if origin:
        # Referer may include a path — keep scheme+host only.
        from urllib.parse import urlparse

        parsed = urlparse(origin)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"
    return request.build_absolute_uri("/").rstrip("/")


def _period_end_from_now(period: str) -> datetime:
    now = timezone.now()
    if (period or "").lower() == Profile.BillingPeriod.YEARLY:
        try:
            return now.replace(year=now.year + 1)
        except ValueError:
            return now + timedelta(days=365)
    month = now.month + 1
    year = now.year
    if month > 12:
        month = 1
        year += 1
    try:
        return now.replace(year=year, month=month)
    except ValueError:
        return now + timedelta(days=30)


def _datetime_from_stripe_ts(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=dt_timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def _apply_subscription_to_profile(
    profile: Profile,
    *,
    status_value: str,
    customer_id: str = "",
    subscription_id: str = "",
    billing_period: str = "",
    cancel_at_period_end: bool | None = None,
    current_period_end: datetime | None = None,
) -> None:
    update_fields = ["subscription_status"]
    profile.subscription_status = status_value
    if customer_id:
        profile.stripe_customer_id = customer_id
        update_fields.append("stripe_customer_id")
    if subscription_id:
        profile.stripe_subscription_id = subscription_id
        update_fields.append("stripe_subscription_id")
    if billing_period in {Profile.BillingPeriod.MONTHLY, Profile.BillingPeriod.YEARLY}:
        profile.billing_period = billing_period
        update_fields.append("billing_period")
    if cancel_at_period_end is not None:
        profile.cancel_at_period_end = cancel_at_period_end
        update_fields.append("cancel_at_period_end")
    elif status_value == Profile.SubscriptionStatus.ACTIVE:
        profile.cancel_at_period_end = False
        update_fields.append("cancel_at_period_end")
    elif status_value == Profile.SubscriptionStatus.CANCELED:
        profile.cancel_at_period_end = False
        update_fields.append("cancel_at_period_end")
    if current_period_end is not None:
        profile.current_period_end = current_period_end
        update_fields.append("current_period_end")
    profile.save(update_fields=update_fields)


def _billing_period_from_subscription(subscription: dict | stripe.Subscription) -> str:
    try:
        items = subscription["items"]["data"]
        interval = items[0]["price"]["recurring"]["interval"]
        return (
            Profile.BillingPeriod.YEARLY
            if interval == "year"
            else Profile.BillingPeriod.MONTHLY
        )
    except Exception:
        return ""


class BillingConfigView(APIView):
    """Public config the Flutter checkout page needs (publishable key only)."""

    permission_classes = [permissions.AllowAny]

    def get(self, request):
        return Response(
            {
                "configured": _stripe_configured(),
                "mock_checkout": _mock_checkout_enabled(),
                "publishable_key": getattr(settings, "STRIPE_PUBLISHABLE_KEY", "") or "",
                "monthly_amount_display": "$15.00",
                "yearly_amount_display": "$150.00",
            }
        )


class MockActivatePremiumView(APIView):
    """TEMPORARY workaround — gifts Premium without charging.

    Remove this view (and BILLING_MOCK_CHECKOUT) once real Stripe credentials
    are configured. Card fields on the client are never sent here.
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        if not _mock_checkout_enabled():
            return Response(
                {
                    "detail": (
                        "Mock checkout is disabled. Configure Stripe keys and "
                        "set BILLING_MOCK_CHECKOUT=false."
                    )
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        period = (request.data.get("billing_period") or "monthly").lower()
        if period not in {"monthly", "yearly"}:
            return Response(
                {"detail": "billing_period must be 'monthly' or 'yearly'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        profile = _get_or_create_profile(request.user)
        _apply_subscription_to_profile(
            profile,
            status_value=Profile.SubscriptionStatus.ACTIVE,
            billing_period=period,
            cancel_at_period_end=False,
            current_period_end=_period_end_from_now(period),
        )
        user = User.objects.select_related("profile").get(pk=request.user.pk)
        return Response(
            {
                "ok": True,
                "mock": True,
                "user": UserSerializer(user).data,
            }
        )


class CreateCheckoutSessionView(APIView):
    """Create an Embedded Stripe Checkout Session for Premium."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        if not _stripe_configured():
            return Response(
                {
                    "detail": (
                        "Stripe is not configured. Set STRIPE_SECRET_KEY and "
                        "STRIPE_PUBLISHABLE_KEY on the server."
                    )
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        period = (request.data.get("billing_period") or "monthly").lower()
        if period not in {"monthly", "yearly"}:
            return Response(
                {"detail": "billing_period must be 'monthly' or 'yearly'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        _ensure_stripe()
        profile = _get_or_create_profile(request.user)
        app_url = _public_app_url(request)
        return_url = f"{app_url}/?billing=success&session_id={{CHECKOUT_SESSION_ID}}"

        try:
            customer_id = profile.stripe_customer_id or None
            if not customer_id:
                customer = stripe.Customer.create(
                    email=request.user.email,
                    name=request.user.get_full_name() or request.user.username,
                    metadata={"user_id": str(request.user.id)},
                )
                customer_id = customer["id"]
                profile.stripe_customer_id = customer_id
                profile.save(update_fields=["stripe_customer_id"])

            session = stripe.checkout.Session.create(
                ui_mode="embedded_page",
                redirect_on_completion="if_required",
                mode="subscription",
                customer=customer_id,
                client_reference_id=str(request.user.id),
                line_items=[_line_item_for_period(period)],
                return_url=return_url,
                metadata={
                    "user_id": str(request.user.id),
                    "billing_period": period,
                },
                subscription_data={
                    "metadata": {
                        "user_id": str(request.user.id),
                        "billing_period": period,
                    }
                },
            )
        except stripe.error.StripeError as exc:
            logger.exception("Stripe checkout session create failed")
            return Response(
                {"detail": str(exc.user_message or exc)},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response(
            {
                "client_secret": session["client_secret"],
                "session_id": session["id"],
                "publishable_key": settings.STRIPE_PUBLISHABLE_KEY,
            }
        )


class CheckoutSessionStatusView(APIView):
    """Confirm a completed Checkout Session and sync Premium status."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if not _stripe_configured():
            return Response(
                {"detail": "Stripe is not configured."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        session_id = (request.query_params.get("session_id") or "").strip()
        if not session_id:
            return Response(
                {"detail": "session_id is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        _ensure_stripe()
        try:
            session = stripe.checkout.Session.retrieve(session_id)
        except stripe.error.StripeError as exc:
            return Response(
                {"detail": str(exc.user_message or exc)},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        ref = str(session.get("client_reference_id") or "")
        if ref and ref != str(request.user.id):
            return Response(
                {"detail": "Checkout session does not belong to this user."},
                status=status.HTTP_403_FORBIDDEN,
            )

        profile = _get_or_create_profile(request.user)
        payment_status = session.get("status")
        if payment_status == "complete":
            period = (session.get("metadata") or {}).get("billing_period") or ""
            sub_id = session.get("subscription") or ""
            if isinstance(sub_id, dict):
                sub_id = sub_id.get("id") or ""
            _apply_subscription_to_profile(
                profile,
                status_value=Profile.SubscriptionStatus.ACTIVE,
                customer_id=session.get("customer") or "",
                subscription_id=sub_id or "",
                billing_period=period,
            )

        return Response(
            {
                "status": payment_status,
                "user": UserSerializer(request.user).data,
            }
        )


class CancelSubscriptionView(APIView):
    """Stop auto-renewal. Premium stays until the current period ends."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        profile = _get_or_create_profile(request.user)
        profile.expire_canceled_subscription_if_needed()
        if profile.subscription_status != Profile.SubscriptionStatus.ACTIVE:
            return Response(
                {"detail": "You do not have an active Premium subscription to cancel."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if profile.cancel_at_period_end:
            user = User.objects.select_related("profile").get(pk=request.user.pk)
            return Response({"ok": True, "user": UserSerializer(user).data})

        if profile.stripe_subscription_id and _stripe_configured():
            _ensure_stripe()
            try:
                subscription = stripe.Subscription.modify(
                    profile.stripe_subscription_id,
                    cancel_at_period_end=True,
                )
            except stripe.error.StripeError as exc:
                logger.exception("Stripe subscription cancel failed")
                return Response(
                    {"detail": str(exc.user_message or exc)},
                    status=status.HTTP_502_BAD_GATEWAY,
                )
            period_end = _datetime_from_stripe_ts(subscription.get("current_period_end"))
            _apply_subscription_to_profile(
                profile,
                status_value=Profile.SubscriptionStatus.ACTIVE,
                subscription_id=subscription.get("id") or profile.stripe_subscription_id,
                billing_period=_billing_period_from_subscription(subscription)
                or profile.billing_period,
                cancel_at_period_end=True,
                current_period_end=period_end or profile.current_period_end,
            )
        else:
            period_end = profile.current_period_end or _period_end_from_now(
                profile.billing_period or Profile.BillingPeriod.MONTHLY
            )
            _apply_subscription_to_profile(
                profile,
                status_value=Profile.SubscriptionStatus.ACTIVE,
                billing_period=profile.billing_period,
                cancel_at_period_end=True,
                current_period_end=period_end,
            )

        user = User.objects.select_related("profile").get(pk=request.user.pk)
        return Response(
            {
                "ok": True,
                "user": UserSerializer(user).data,
            }
        )


class StripeWebhookView(APIView):
    """Stripe webhook — keep STRIPE_WEBHOOK_SECRET in sync with the Dashboard endpoint."""

    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        if not getattr(settings, "STRIPE_WEBHOOK_SECRET", ""):
            return Response(
                {"detail": "STRIPE_WEBHOOK_SECRET is not configured."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        payload = request.body
        sig_header = request.META.get("HTTP_STRIPE_SIGNATURE", "")
        _ensure_stripe()
        try:
            event = stripe.Webhook.construct_event(
                payload,
                sig_header,
                settings.STRIPE_WEBHOOK_SECRET,
            )
        except ValueError:
            return Response({"detail": "Invalid payload."}, status=status.HTTP_400_BAD_REQUEST)
        except stripe.error.SignatureVerificationError:
            return Response({"detail": "Invalid signature."}, status=status.HTTP_400_BAD_REQUEST)

        event_type = event["type"]
        data_object = event["data"]["object"]

        try:
            if event_type == "checkout.session.completed":
                self._on_checkout_completed(data_object)
            elif event_type in {
                "customer.subscription.created",
                "customer.subscription.updated",
            }:
                self._on_subscription_updated(data_object)
            elif event_type == "customer.subscription.deleted":
                self._on_subscription_deleted(data_object)
        except Exception:
            logger.exception("Error handling Stripe event %s", event_type)
            return Response({"detail": "Handler error."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({"received": True})

    def _profile_for_stripe_object(self, obj) -> Profile | None:
        metadata = obj.get("metadata") or {}
        user_id = metadata.get("user_id") or obj.get("client_reference_id")
        if user_id:
            try:
                user = User.objects.get(pk=int(user_id))
                return _get_or_create_profile(user)
            except (User.DoesNotExist, TypeError, ValueError):
                pass

        customer_id = obj.get("customer") or ""
        if isinstance(customer_id, dict):
            customer_id = customer_id.get("id") or ""
        if customer_id:
            return Profile.objects.filter(stripe_customer_id=customer_id).select_related("user").first()
        return None

    def _on_checkout_completed(self, session) -> None:
        profile = self._profile_for_stripe_object(session)
        if profile is None:
            logger.warning("checkout.session.completed with no matching user: %s", session.get("id"))
            return
        period = (session.get("metadata") or {}).get("billing_period") or ""
        sub_id = session.get("subscription") or ""
        if isinstance(sub_id, dict):
            sub_id = sub_id.get("id") or ""
        _apply_subscription_to_profile(
            profile,
            status_value=Profile.SubscriptionStatus.ACTIVE,
            customer_id=session.get("customer") or "",
            subscription_id=sub_id or "",
            billing_period=period,
            cancel_at_period_end=False,
        )

    def _on_subscription_updated(self, subscription) -> None:
        profile = self._profile_for_stripe_object(subscription)
        if profile is None:
            customer_id = subscription.get("customer") or ""
            profile = Profile.objects.filter(stripe_customer_id=customer_id).first()
        if profile is None:
            return

        stripe_status = subscription.get("status") or ""
        if stripe_status in {"active", "trialing"}:
            status_value = Profile.SubscriptionStatus.ACTIVE
        elif stripe_status == "past_due":
            status_value = Profile.SubscriptionStatus.PAST_DUE
        else:
            status_value = Profile.SubscriptionStatus.CANCELED

        _apply_subscription_to_profile(
            profile,
            status_value=status_value,
            customer_id=subscription.get("customer") or "",
            subscription_id=subscription.get("id") or "",
            billing_period=_billing_period_from_subscription(subscription),
            cancel_at_period_end=bool(subscription.get("cancel_at_period_end")),
            current_period_end=_datetime_from_stripe_ts(subscription.get("current_period_end")),
        )

    def _on_subscription_deleted(self, subscription) -> None:
        profile = self._profile_for_stripe_object(subscription)
        if profile is None:
            customer_id = subscription.get("customer") or ""
            profile = Profile.objects.filter(stripe_customer_id=customer_id).first()
        if profile is None:
            return
        _apply_subscription_to_profile(
            profile,
            status_value=Profile.SubscriptionStatus.CANCELED,
            customer_id=subscription.get("customer") or "",
            subscription_id=subscription.get("id") or "",
            cancel_at_period_end=False,
        )
