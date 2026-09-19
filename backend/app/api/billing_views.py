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
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.authentication import TokenAuthentication
from rest_framework.response import Response
from rest_framework.views import APIView

from core.persist_db import dump_persistent_postgres

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


def subscription_consent_message(period: str) -> str:
    """Period-aware acknowledgment shown on Stripe Checkout."""
    if (period or "").lower() == Profile.BillingPeriod.YEARLY:
        return (
            "I acknowledge I am subscribing to a yearly Premium plan "
            "($150/year) that renews until I cancel."
        )
    return (
        "I acknowledge I am subscribing to a monthly Premium plan "
        "($15/month) that renews until I cancel."
    )


def _checkout_consent_kwargs(period: str) -> dict:
    message = subscription_consent_message(period)
    return {
        "consent_collection": {"terms_of_service": "required"},
        "custom_text": {
            "terms_of_service_acceptance": {"message": message},
        },
    }


def subscription_terms_view(_request):
    """Public terms page Stripe Checkout can link from the consent checkbox."""
    return HttpResponse(
        """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Nordin's AI Premium subscription terms</title>
</head>
<body style="font-family: system-ui, sans-serif; max-width: 40rem; margin: 2rem auto; padding: 0 1rem; line-height: 1.5;">
  <h1>Nordin's AI Premium subscription</h1>
  <p>Premium is a recurring paid subscription. The monthly plan is $15 per month. The yearly plan is $150 per year.</p>
  <p>Your subscription renews automatically until you cancel. After you cancel, you keep Premium until the end of the current billing period.</p>
</body>
</html>
""",
        content_type="text/html; charset=utf-8",
    )


def _get_or_create_profile(user: User) -> Profile:
    profile, _ = Profile.objects.get_or_create(user=user)
    return profile


_PERIOD_PRICE_CATALOG = {
    Profile.BillingPeriod.YEARLY: {
        "lookup_key": "pastor_ai_premium_yearly",
        "unit_amount": 15000,
        "interval": "year",
        "name": "Nordin's AI Premium (Yearly)",
    },
    Profile.BillingPeriod.MONTHLY: {
        "lookup_key": "pastor_ai_premium_monthly",
        "unit_amount": 1500,
        "interval": "month",
        "name": "Nordin's AI Premium (Monthly)",
    },
}


def _configured_price_id(period: str) -> str:
    period = (period or "monthly").lower()
    if period == Profile.BillingPeriod.YEARLY:
        return (getattr(settings, "STRIPE_PRICE_YEARLY", "") or "").strip()
    return (getattr(settings, "STRIPE_PRICE_MONTHLY", "") or "").strip()


def _line_item_for_period(period: str) -> dict:
    """Prefer configured Price IDs; otherwise create one-off price_data.

    Checkout Sessions accept ``price_data``. Subscription Schedules do not —
    use :func:`_schedule_item_for_period` for plan changes.
    """
    period = (period or "monthly").lower()
    price_id = _configured_price_id(period)
    if price_id:
        return {"price": price_id, "quantity": 1}
    catalog = _PERIOD_PRICE_CATALOG.get(period) or _PERIOD_PRICE_CATALOG[Profile.BillingPeriod.MONTHLY]
    return {
        "price_data": {
            "currency": "usd",
            "unit_amount": catalog["unit_amount"],
            "recurring": {"interval": catalog["interval"]},
            "product_data": {"name": catalog["name"]},
        },
        "quantity": 1,
    }


def _price_id_for_period(period: str) -> str:
    """Return a reusable Stripe Price ID for monthly/yearly plan changes.

    Subscription Schedule phases reject ``price_data``. If the operator has not
    set ``STRIPE_PRICE_*``, look up (or create) a catalog price by lookup_key.
    """
    configured = _configured_price_id(period)
    if configured:
        return configured
    return _get_or_create_recurring_price_id(period)


def _get_or_create_recurring_price_id(period: str) -> str:
    period = (period or "monthly").lower()
    catalog = _PERIOD_PRICE_CATALOG.get(period) or _PERIOD_PRICE_CATALOG[Profile.BillingPeriod.MONTHLY]
    lookup_key = catalog["lookup_key"]
    existing = stripe.Price.list(lookup_keys=[lookup_key], active=True, limit=1)
    data = _stripe_get(existing, "data") or []
    if data:
        price_id = _id_or_value(data[0])
        if price_id:
            return price_id
    product = stripe.Product.create(
        name=catalog["name"],
        metadata={"pastor_ai_billing_period": period},
    )
    try:
        price = stripe.Price.create(
            currency="usd",
            unit_amount=catalog["unit_amount"],
            recurring={"interval": catalog["interval"]},
            product=_id_or_value(product),
            lookup_key=lookup_key,
            metadata={"pastor_ai_billing_period": period},
        )
    except stripe.error.StripeError:
        # A concurrent request may have created the lookup_key first.
        existing = stripe.Price.list(lookup_keys=[lookup_key], limit=1)
        data = _stripe_get(existing, "data") or []
        if data:
            price_id = _id_or_value(data[0])
            if price_id:
                return price_id
        raise
    price_id = _id_or_value(price)
    if not price_id:
        raise ValueError("Could not create a Stripe price for the selected plan.")
    return price_id


def _schedule_item_for_period(period: str) -> dict:
    return {"price": _price_id_for_period(period), "quantity": 1}


def _stripe_error_response(exc) -> Response:
    """Map Stripe failures to JSON 400/503 — never HTTP 502.

    RunPod's proxy replaces origin 502 bodies with its HTML waiting page, which
    the Flutter client then showed as a popup after monthly→yearly updates.
    """
    logger.exception("Stripe request failed")
    detail = getattr(exc, "user_message", None) or str(exc) or "Stripe request failed."
    name = type(exc).__name__
    if name in {"APIConnectionError", "RateLimitError", "APIError", "TryAgain"}:
        code = status.HTTP_503_SERVICE_UNAVAILABLE
    else:
        code = status.HTTP_400_BAD_REQUEST
    return Response({"detail": str(detail)}, status=code)


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


def _stripe_get(obj, key: str, default=None):
    """Read a field from a Stripe object or plain dict.

    Newer stripe-python StripeObjects are not dict subclasses and do not
    implement ``.get``; using ``obj.get(...)`` raises AttributeError and
    aborts Premium sync after a successful Checkout payment.
    """
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    try:
        value = obj[key]
    except (KeyError, TypeError, AttributeError):
        return default
    return default if value is None else value


def _apply_subscription_to_profile(
    profile: Profile,
    *,
    status_value: str,
    customer_id: str = "",
    subscription_id: str = "",
    billing_period: str = "",
    pending_billing_period: str | None = None,
    cancel_at_period_end: bool | None = None,
    current_period_end: datetime | None = None,
) -> None:
    was_active = profile.subscription_status == Profile.SubscriptionStatus.ACTIVE
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
    if pending_billing_period is not None:
        if pending_billing_period not in {
            Profile.BillingPeriod.MONTHLY,
            Profile.BillingPeriod.YEARLY,
            "",
        }:
            pending_billing_period = ""
        if pending_billing_period == (profile.billing_period or ""):
            pending_billing_period = ""
        profile.pending_billing_period = pending_billing_period
        update_fields.append("pending_billing_period")
    elif billing_period in {Profile.BillingPeriod.MONTHLY, Profile.BillingPeriod.YEARLY}:
        if profile.pending_billing_period == billing_period:
            profile.pending_billing_period = ""
            update_fields.append("pending_billing_period")
    if (
        status_value == Profile.SubscriptionStatus.CANCELED
        and "pending_billing_period" not in update_fields
    ):
        profile.pending_billing_period = ""
        update_fields.append("pending_billing_period")
    if current_period_end is not None:
        profile.current_period_end = current_period_end
        update_fields.append("current_period_end")
    profile.save(update_fields=update_fields)
    dump_persistent_postgres()
    if (
        status_value == Profile.SubscriptionStatus.ACTIVE
        and not was_active
        and not profile.email_verified
        and not profile.user.is_staff
        and not profile.user.is_superuser
    ):
        try:
            from .email_verification import EmailVerificationError, issue_and_send_verification_code

            issue_and_send_verification_code(profile.user)
        except EmailVerificationError:
            logger.warning(
                "Could not email verification code after subscription for user %s",
                profile.user_id,
            )
        except Exception:
            logger.exception(
                "Failed to email verification code after subscription for user %s",
                profile.user_id,
            )


def _billing_period_from_subscription(subscription: dict | stripe.Subscription) -> str:
    try:
        items = _stripe_get(_stripe_get(subscription, "items"), "data") or []
        if not items:
            return ""
        return _billing_period_from_price(_stripe_get(items[0], "price"))
    except Exception:
        return ""


def _id_or_value(value) -> str:
    if not value:
        return ""
    if isinstance(value, str):
        return value
    return str(_stripe_get(value, "id") or "")


def _subscription_current_period_end_ts(subscription) -> int | None:
    ts = _stripe_get(subscription, "current_period_end")
    if ts:
        try:
            return int(ts)
        except (TypeError, ValueError):
            pass
    items = _stripe_get(_stripe_get(subscription, "items"), "data") or []
    if not items:
        return None
    ts = _stripe_get(items[0], "current_period_end")
    if not ts:
        return None
    try:
        return int(ts)
    except (TypeError, ValueError):
        return None


def _billing_period_from_price(price) -> str:
    if isinstance(price, str):
        yearly = getattr(settings, "STRIPE_PRICE_YEARLY", "") or ""
        monthly = getattr(settings, "STRIPE_PRICE_MONTHLY", "") or ""
        if yearly and price == yearly:
            return Profile.BillingPeriod.YEARLY
        if monthly and price == monthly:
            return Profile.BillingPeriod.MONTHLY
        return ""
    recurring = _stripe_get(price, "recurring")
    interval = _stripe_get(recurring, "interval")
    if interval == "year":
        return Profile.BillingPeriod.YEARLY
    if interval == "month":
        return Profile.BillingPeriod.MONTHLY
    return ""


def _billing_period_from_phase(phase) -> str:
    items = _stripe_get(phase, "items") or []
    if not items:
        return ""
    return _billing_period_from_price(_stripe_get(items[0], "price"))


def _current_phase_items_from_subscription(subscription) -> list[dict]:
    items = _stripe_get(_stripe_get(subscription, "items"), "data") or []
    result = []
    for item in items:
        price = _stripe_get(item, "price")
        price_id = price if isinstance(price, str) else _stripe_get(price, "id")
        qty = _stripe_get(item, "quantity") or 1
        if price_id:
            result.append({"price": price_id, "quantity": qty})
    return result


def _pending_billing_period_from_schedule(schedule, current_period: str) -> str:
    phases = _stripe_get(schedule, "phases") or []
    if len(phases) < 2:
        return ""
    future = _billing_period_from_phase(phases[-1])
    if future and future != current_period:
        return future
    return ""


def _schedule_subscription_plan_change(subscription, new_period: str) -> int:
    """Keep the current price until period end, then bill the new interval."""
    sub_id = _id_or_value(_stripe_get(subscription, "id") or subscription)
    period_end_ts = _subscription_current_period_end_ts(subscription)
    if not period_end_ts:
        raise ValueError("Stripe subscription is missing the current period end.")

    current_items = _current_phase_items_from_subscription(subscription)
    if not current_items:
        current_period = (
            _billing_period_from_subscription(subscription)
            or Profile.BillingPeriod.MONTHLY
        )
        current_items = [_schedule_item_for_period(current_period)]
    new_items = [_schedule_item_for_period(new_period)]

    created_schedule = False
    schedule_id = _id_or_value(_stripe_get(subscription, "schedule"))
    if schedule_id:
        schedule = stripe.SubscriptionSchedule.retrieve(schedule_id)
    else:
        schedule = stripe.SubscriptionSchedule.create(from_subscription=sub_id)
        created_schedule = True

    phases = _stripe_get(schedule, "phases") or []
    current_phase = phases[0] if phases else None
    start_date = _stripe_get(current_phase, "start_date") if current_phase else None
    if not start_date:
        start_date = _stripe_get(subscription, "start_date")
    if not start_date:
        if created_schedule:
            _release_created_schedule(schedule)
        raise ValueError("Stripe subscription schedule is missing start_date.")

    try:
        stripe.SubscriptionSchedule.modify(
            _id_or_value(_stripe_get(schedule, "id") or schedule),
            end_behavior="release",
            proration_behavior="none",
            phases=[
                {
                    "items": current_items,
                    "start_date": start_date,
                    "end_date": period_end_ts,
                    "proration_behavior": "none",
                },
                {
                    "items": new_items,
                    "proration_behavior": "none",
                },
            ],
        )
    except Exception:
        if created_schedule:
            _release_created_schedule(schedule)
        raise
    return period_end_ts


def _release_created_schedule(schedule) -> None:
    schedule_id = _id_or_value(_stripe_get(schedule, "id") or schedule)
    if not schedule_id:
        return
    try:
        stripe.SubscriptionSchedule.release(schedule_id)
    except stripe.error.StripeError:
        logger.exception("Failed to release Stripe schedule %s after plan change error", schedule_id)


def _release_subscription_schedule(subscription) -> None:
    schedule_id = _id_or_value(_stripe_get(subscription, "schedule"))
    if not schedule_id:
        return
    stripe.SubscriptionSchedule.release(schedule_id)


def _pending_from_stripe_subscription(subscription, current_period: str) -> str | None:
    """Read a scheduled plan change from Stripe, or None if it cannot be determined."""
    schedule_id = _id_or_value(_stripe_get(subscription, "schedule"))
    if not schedule_id:
        return ""
    try:
        schedule = stripe.SubscriptionSchedule.retrieve(schedule_id)
    except stripe.error.StripeError:
        logger.exception("Failed to retrieve Stripe subscription schedule")
        return None
    return _pending_billing_period_from_schedule(schedule, current_period)


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


class _AuthenticatedBillingView(APIView):
    """Token only — SessionAuthentication CSRF-fails Flutter POSTs when an admin cookie is present."""

    authentication_classes = [TokenAuthentication]
    permission_classes = [permissions.IsAuthenticated]


class MockActivatePremiumView(_AuthenticatedBillingView):
    """TEMPORARY workaround — gifts Premium without charging.

    Remove this view (and BILLING_MOCK_CHECKOUT) once real Stripe credentials
    are configured. Card fields on the client are never sent here.
    """

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
            pending_billing_period="",
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


class CreateCheckoutSessionView(_AuthenticatedBillingView):
    """Create an Embedded Stripe Checkout Session for Premium."""

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

            session_kwargs = {
                "ui_mode": "embedded_page",
                "mode": "subscription",
                "customer": customer_id,
                "client_reference_id": str(request.user.id),
                "line_items": [_line_item_for_period(period)],
                "return_url": return_url,
                "metadata": {
                    "user_id": str(request.user.id),
                    "billing_period": period,
                },
                "subscription_data": {
                    "metadata": {
                        "user_id": str(request.user.id),
                        "billing_period": period,
                    }
                },
                **_checkout_consent_kwargs(period),
            }
            try:
                session = stripe.checkout.Session.create(**session_kwargs)
            except stripe.error.InvalidRequestError as exc:
                # Stripe only renders the required TOS checkbox when a Terms of
                # Service URL is set in Dashboard → Settings → Public details.
                # Fall back to submit-button copy so checkout still opens.
                detail = str(exc).lower()
                if "terms of service" not in detail and "terms_of_service" not in detail:
                    raise
                logger.warning(
                    "Stripe TOS URL missing; showing consent text without a required checkbox"
                )
                session_kwargs.pop("consent_collection", None)
                session_kwargs["custom_text"] = {
                    "submit": {"message": subscription_consent_message(period)},
                }
                session = stripe.checkout.Session.create(**session_kwargs)
        except stripe.error.StripeError as exc:
            return _stripe_error_response(exc)

        return Response(
            {
                "client_secret": session["client_secret"],
                "session_id": session["id"],
                "publishable_key": settings.STRIPE_PUBLISHABLE_KEY,
            }
        )


class CheckoutSessionStatusView(_AuthenticatedBillingView):
    """Confirm a completed Checkout Session and sync Premium status."""

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
            return _stripe_error_response(exc)

        ref = str(_stripe_get(session, "client_reference_id") or "")
        if ref and ref != str(request.user.id):
            return Response(
                {"detail": "Checkout session does not belong to this user."},
                status=status.HTTP_403_FORBIDDEN,
            )

        profile = _get_or_create_profile(request.user)
        payment_status = _stripe_get(session, "status")
        if payment_status == "complete":
            metadata = _stripe_get(session, "metadata") or {}
            period = _stripe_get(metadata, "billing_period") or ""
            if isinstance(metadata, dict):
                period = metadata.get("billing_period") or period
            sub_id = _stripe_get(session, "subscription") or ""
            if not isinstance(sub_id, str):
                sub_id = _stripe_get(sub_id, "id") or ""
            period_end = None
            if sub_id:
                try:
                    subscription = stripe.Subscription.retrieve(sub_id)
                    period_end = _datetime_from_stripe_ts(
                        _stripe_get(subscription, "current_period_end")
                    )
                    if not period:
                        period = _billing_period_from_subscription(subscription)
                except stripe.error.StripeError:
                    logger.exception(
                        "Failed to retrieve Stripe subscription %s for session status",
                        sub_id,
                    )
            if period_end is None and period:
                period_end = _period_end_from_now(period)
            customer_id = _stripe_get(session, "customer") or ""
            if not isinstance(customer_id, str):
                customer_id = _stripe_get(customer_id, "id") or ""
            _apply_subscription_to_profile(
                profile,
                status_value=Profile.SubscriptionStatus.ACTIVE,
                customer_id=customer_id or "",
                subscription_id=sub_id or "",
                billing_period=period,
                pending_billing_period="",
                current_period_end=period_end,
            )

        # Reload so serializer sees the updated related Profile (not a stale cache).
        user = User.objects.select_related("profile").get(pk=request.user.pk)
        return Response(
            {
                "status": payment_status,
                "user": UserSerializer(user).data,
            }
        )


class CancelSubscriptionView(_AuthenticatedBillingView):
    """Stop auto-renewal. Premium stays until the current period ends."""

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
                existing = stripe.Subscription.retrieve(profile.stripe_subscription_id)
                _release_subscription_schedule(existing)
                subscription = stripe.Subscription.modify(
                    profile.stripe_subscription_id,
                    cancel_at_period_end=True,
                )
            except stripe.error.StripeError as exc:
                return _stripe_error_response(exc)
            period_end = _datetime_from_stripe_ts(
                _stripe_get(subscription, "current_period_end")
            )
            _apply_subscription_to_profile(
                profile,
                status_value=Profile.SubscriptionStatus.ACTIVE,
                subscription_id=_stripe_get(subscription, "id")
                or profile.stripe_subscription_id,
                billing_period=_billing_period_from_subscription(subscription)
                or profile.billing_period,
                pending_billing_period="",
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
                pending_billing_period="",
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


class ChangePlanView(_AuthenticatedBillingView):
    """Schedule a monthly/yearly switch for the next billing period.

    The current period stays at the current price. Stripe (or mock checkout)
    bills the new price starting at ``current_period_end``.
    """

    def post(self, request):
        period = (request.data.get("billing_period") or "").strip().lower()
        if period not in {Profile.BillingPeriod.MONTHLY, Profile.BillingPeriod.YEARLY}:
            return Response(
                {"detail": "billing_period must be 'monthly' or 'yearly'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        profile = _get_or_create_profile(request.user)
        profile.expire_canceled_subscription_if_needed()
        profile.apply_pending_plan_change_if_needed()
        if profile.subscription_status != Profile.SubscriptionStatus.ACTIVE:
            return Response(
                {"detail": "You need an active Premium subscription to change plans."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        current = (profile.billing_period or "").strip().lower()
        pending = (profile.pending_billing_period or "").strip().lower()

        if period == current and not pending:
            return Response(
                {"detail": f"You are already on the {period} plan."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if period == pending:
            user = User.objects.select_related("profile").get(pk=request.user.pk)
            return Response({"ok": True, "user": UserSerializer(user).data})

        reverting = period == current and bool(pending)
        next_pending = "" if reverting else period
        period_end = profile.current_period_end

        if profile.stripe_subscription_id and _stripe_configured():
            _ensure_stripe()
            try:
                subscription = stripe.Subscription.retrieve(
                    profile.stripe_subscription_id,
                    expand=["items.data.price"],
                )
                if reverting:
                    _release_subscription_schedule(subscription)
                    period_end_ts = _subscription_current_period_end_ts(subscription)
                else:
                    period_end_ts = _schedule_subscription_plan_change(
                        subscription, period
                    )
                    if _stripe_get(subscription, "cancel_at_period_end"):
                        stripe.Subscription.modify(
                            profile.stripe_subscription_id,
                            cancel_at_period_end=False,
                        )
                period_end = (
                    _datetime_from_stripe_ts(period_end_ts) or period_end
                )
            except ValueError as exc:
                return Response(
                    {"detail": str(exc)},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            except stripe.error.StripeError as exc:
                return _stripe_error_response(exc)

        if period_end is None:
            period_end = _period_end_from_now(
                current or Profile.BillingPeriod.MONTHLY
            )

        _apply_subscription_to_profile(
            profile,
            status_value=Profile.SubscriptionStatus.ACTIVE,
            subscription_id=profile.stripe_subscription_id,
            billing_period=current or profile.billing_period,
            pending_billing_period=next_pending,
            cancel_at_period_end=False,
            current_period_end=period_end,
        )
        user = User.objects.select_related("profile").get(pk=request.user.pk)
        return Response({"ok": True, "user": UserSerializer(user).data})


class SyncSubscriptionView(_AuthenticatedBillingView):
    """Pull an active Stripe subscription onto the local profile.

    Covers cases where Checkout paid in Stripe but the web client never called
    session-status (common on Flutter web), and after an admin reset while
    Stripe still has an active test subscription.
    """

    def post(self, request):
        if not _stripe_configured():
            return Response(
                {"detail": "Stripe is not configured."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        profile = _get_or_create_profile(request.user)
        customer_id = (profile.stripe_customer_id or "").strip()
        if not customer_id:
            user = User.objects.select_related("profile").get(pk=request.user.pk)
            return Response(
                {
                    "ok": True,
                    "synced": False,
                    "detail": "No Stripe customer on this account yet.",
                    "user": UserSerializer(user).data,
                }
            )

        _ensure_stripe()
        try:
            subscriptions = stripe.Subscription.list(
                customer=customer_id,
                status="all",
                limit=20,
            )
        except stripe.error.StripeError as exc:
            return _stripe_error_response(exc)

        active = None
        for sub in subscriptions.data:
            if _stripe_get(sub, "status") in {"active", "trialing"}:
                active = sub
                break

        if active is None:
            user = User.objects.select_related("profile").get(pk=request.user.pk)
            return Response(
                {
                    "ok": True,
                    "synced": False,
                    "detail": "No active Stripe subscription found.",
                    "user": UserSerializer(user).data,
                }
            )

        actual_period = _billing_period_from_subscription(active)
        pending = _pending_from_stripe_subscription(active, actual_period)
        if pending is None:
            pending = profile.pending_billing_period
        _apply_subscription_to_profile(
            profile,
            status_value=Profile.SubscriptionStatus.ACTIVE,
            customer_id=customer_id,
            subscription_id=_stripe_get(active, "id") or "",
            billing_period=actual_period,
            pending_billing_period=pending,
            cancel_at_period_end=bool(_stripe_get(active, "cancel_at_period_end")),
            current_period_end=_datetime_from_stripe_ts(
                _subscription_current_period_end_ts(active)
            ),
        )
        user = User.objects.select_related("profile").get(pk=request.user.pk)
        return Response(
            {
                "ok": True,
                "synced": True,
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
        metadata = _stripe_get(obj, "metadata") or {}
        user_id = _stripe_get(metadata, "user_id") or _stripe_get(
            obj, "client_reference_id"
        )
        if isinstance(metadata, dict) and not _stripe_get(metadata, "user_id"):
            user_id = metadata.get("user_id") or user_id
        if user_id:
            try:
                user = User.objects.get(pk=int(user_id))
                return _get_or_create_profile(user)
            except (User.DoesNotExist, TypeError, ValueError):
                pass

        customer_id = _stripe_get(obj, "customer") or ""
        if not isinstance(customer_id, str):
            customer_id = _stripe_get(customer_id, "id") or ""
        if customer_id:
            return Profile.objects.filter(stripe_customer_id=customer_id).select_related("user").first()
        return None

    def _on_checkout_completed(self, session) -> None:
        profile = self._profile_for_stripe_object(session)
        if profile is None:
            logger.warning(
                "checkout.session.completed with no matching user: %s",
                _stripe_get(session, "id"),
            )
            return
        metadata = _stripe_get(session, "metadata") or {}
        period = _stripe_get(metadata, "billing_period") or ""
        if isinstance(metadata, dict):
            period = metadata.get("billing_period") or period
        sub_id = _stripe_get(session, "subscription") or ""
        if not isinstance(sub_id, str):
            sub_id = _stripe_get(sub_id, "id") or ""
        customer_id = _stripe_get(session, "customer") or ""
        if not isinstance(customer_id, str):
            customer_id = _stripe_get(customer_id, "id") or ""
        _apply_subscription_to_profile(
            profile,
            status_value=Profile.SubscriptionStatus.ACTIVE,
            customer_id=customer_id or "",
            subscription_id=sub_id or "",
            billing_period=period,
            pending_billing_period="",
            cancel_at_period_end=False,
        )

    def _on_subscription_updated(self, subscription) -> None:
        profile = self._profile_for_stripe_object(subscription)
        if profile is None:
            customer_id = _stripe_get(subscription, "customer") or ""
            if not isinstance(customer_id, str):
                customer_id = _stripe_get(customer_id, "id") or ""
            profile = Profile.objects.filter(stripe_customer_id=customer_id).first()
        if profile is None:
            return

        stripe_status = _stripe_get(subscription, "status") or ""
        if stripe_status in {"active", "trialing"}:
            status_value = Profile.SubscriptionStatus.ACTIVE
        elif stripe_status == "past_due":
            status_value = Profile.SubscriptionStatus.PAST_DUE
        else:
            status_value = Profile.SubscriptionStatus.CANCELED

        customer_id = _stripe_get(subscription, "customer") or ""
        if not isinstance(customer_id, str):
            customer_id = _stripe_get(customer_id, "id") or ""
        actual_period = _billing_period_from_subscription(subscription)
        pending = _pending_from_stripe_subscription(
            subscription, actual_period or profile.billing_period
        )
        if pending is None:
            if actual_period and actual_period == profile.pending_billing_period:
                pending = ""
        period_end = _datetime_from_stripe_ts(
            _subscription_current_period_end_ts(subscription)
        )
        apply_kwargs = {
            "status_value": status_value,
            "customer_id": customer_id or "",
            "subscription_id": _stripe_get(subscription, "id") or "",
            "billing_period": actual_period,
            "cancel_at_period_end": bool(
                _stripe_get(subscription, "cancel_at_period_end")
            ),
            "current_period_end": period_end,
        }
        if pending is not None:
            apply_kwargs["pending_billing_period"] = pending
        _apply_subscription_to_profile(profile, **apply_kwargs)

    def _on_subscription_deleted(self, subscription) -> None:
        profile = self._profile_for_stripe_object(subscription)
        if profile is None:
            customer_id = _stripe_get(subscription, "customer") or ""
            if not isinstance(customer_id, str):
                customer_id = _stripe_get(customer_id, "id") or ""
            profile = Profile.objects.filter(stripe_customer_id=customer_id).first()
        if profile is None:
            return
        customer_id = _stripe_get(subscription, "customer") or ""
        if not isinstance(customer_id, str):
            customer_id = _stripe_get(customer_id, "id") or ""
        _apply_subscription_to_profile(
            profile,
            status_value=Profile.SubscriptionStatus.CANCELED,
            customer_id=customer_id or "",
            subscription_id=_stripe_get(subscription, "id") or "",
            cancel_at_period_end=False,
        )
