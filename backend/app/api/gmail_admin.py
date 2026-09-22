"""Staff admin page to upload the Gmail service-account JSON key."""

from django.contrib import admin, messages
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse

from .gmail_send import GmailSendError, gmail_key_status, gmail_sender, install_gmail_service_account_json


def gmail_sender_key_view(request):
    if not request.user.is_staff:
        messages.error(request, "You must be an admin user to access this page.")
        return HttpResponseRedirect("../")

    if request.method == "POST":
        uploaded = request.FILES.get("gmail_json")
        raw = uploaded.read() if uploaded else b""
        try:
            installed = install_gmail_service_account_json(raw)
        except GmailSendError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(
                request,
                f"Installed Gmail key ({installed['bytes']} bytes) as {installed['client_email']}. "
                "Signup codes will send from info@thenordins.org after you restart with bash start.sh.",
            )
        return HttpResponseRedirect(request.path)

    status = gmail_key_status()
    context = {
        **admin.site.each_context(request),
        "title": "Gmail sender key",
        "gmail_status": status,
        "gmail_sender": gmail_sender(),
    }
    return TemplateResponse(request, "admin/core/gmail_sender_key.html", context)
