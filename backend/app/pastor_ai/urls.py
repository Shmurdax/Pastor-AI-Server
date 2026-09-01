"""
URL configuration for pastor_ai project.
"""
from django.contrib import admin
from django.urls import path, re_path
from api.auth_views import (
    GoogleAuthView,
    LoginView,
    LogoutView,
    MeView,
    RegisterView,
)
from api.billing_views import (
    BillingConfigView,
    CancelSubscriptionView,
    CheckoutSessionStatusView,
    CreateCheckoutSessionView,
    MockActivatePremiumView,
    StripeWebhookView,
)
from api.views import (
    ChurchEventDetailAPI,
    ChurchEventListCreateAPI,
    MediaVideoListAPI,
    PrayerRequestDetailAPI,
    ResponseReportDetailAPI,
)
from core.views import (
    ChatAPIView,
    IngestedDocumentsAPIView,
    IngestedDocumentFileAPIView,
    SermonPdfByNameAPIView,
    PrayerRequestAPIView,
    TranslateAPIView,
    ResponseReportAPIView,
)
from .frontend import serve_frontend
from .robots import robots_txt_view

urlpatterns = [
    path("robots.txt", robots_txt_view, name="robots_txt"),
    path('admin/', admin.site.urls),

    # Auth — Flutter AuthService paths
    path('api/auth/register/', RegisterView.as_view()),
    path('api/auth/login/', LoginView.as_view()),
    path('api/auth/google/', GoogleAuthView.as_view()),
    path('api/auth/me/', MeView.as_view()),
    path('api/auth/logout/', LogoutView.as_view()),

    # Stripe billing
    path('api/billing/config/', BillingConfigView.as_view()),
    path('api/billing/create-checkout-session/', CreateCheckoutSessionView.as_view()),
    path('api/billing/session-status/', CheckoutSessionStatusView.as_view()),
    path('api/billing/mock-activate/', MockActivatePremiumView.as_view()),
    path('api/billing/cancel-subscription/', CancelSubscriptionView.as_view()),
    path('api/billing/webhook/', StripeWebhookView.as_view()),

    # Chat + prayer + ingested docs
    path('api/chat/', ChatAPIView.as_view(), name='chat_api'),
    path('api/translate/', TranslateAPIView.as_view(), name='translate_api'),
    path('api/prayer-requests/', PrayerRequestAPIView.as_view(), name='prayer_requests_api'),
    path('api/prayer-requests/<int:pk>/', PrayerRequestDetailAPI.as_view(), name='prayer_request_detail_api'),
    path('api/response-reports/', ResponseReportAPIView.as_view(), name='response_reports_api'),
    path('api/response-reports/<int:pk>/', ResponseReportDetailAPI.as_view(), name='response_report_detail_api'),
    path('api/church-events/', ChurchEventListCreateAPI.as_view(), name='church_events_api'),
    path('api/church-events/<int:pk>/', ChurchEventDetailAPI.as_view(), name='church_event_detail_api'),
    path('api/media/', MediaVideoListAPI.as_view(), name='media_list_api'),
    path('api/ingested-documents/', IngestedDocumentsAPIView.as_view(), name='ingested_documents_api'),
    path('api/ingested-documents/<int:document_id>/file/', IngestedDocumentFileAPIView.as_view(), name='ingested_document_file_api'),
    # Backward-compatible route for existing Flutter builds that open /sermons/<name>.pdf directly.
    path('sermons/<str:sermon_name>.pdf', SermonPdfByNameAPIView.as_view(), name='sermon_pdf_by_name'),
    # Legacy alias: older Flutter builds POST to /chat/; route here so CSRF does not hit serve_frontend.
    path('chat/', ChatAPIView.as_view(), name='chat_api_legacy'),

    # Serve Flutter web build and client-side routes from /
    path("", serve_frontend, name="home"),
    re_path(r"^(?!admin/|api/|static/|chat/|sermons/|admin/core/ingested-documents/)(?P<path>.*)$", serve_frontend, name="frontend"),
]
