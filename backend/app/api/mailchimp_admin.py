"""Django admin page that exports AI login emails to Mailchimp."""

from django.contrib import admin, messages
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse

from core.persist_db import dump_persistent_postgres

from .mailchimp import (
    ExportResult,
    audience_status,
    collect_exportable_members,
    mailchimp_configured,
    upsert_members,
    MailchimpError,
)
from .models import MailchimpExportRun


def record_export_run(*, started_by: str, candidate_count: int, result: ExportResult) -> MailchimpExportRun:
    run = MailchimpExportRun.objects.create(
        started_by=started_by,
        candidate_count=candidate_count,
        added=result.added,
        updated=result.updated,
        skipped=result.skipped,
        failed=result.failed,
        error_summary="\n".join(result.errors[:20]),
    )
    dump_persistent_postgres()
    return run


def export_members_to_mailchimp(members, *, started_by: str) -> ExportResult:
    result = upsert_members(members)
    record_export_run(
        started_by=started_by,
        candidate_count=len(members),
        result=result,
    )
    return result


def mailchimp_export_view(request):
    if not request.user.is_staff:
        messages.error(request, "You must be an admin user to access this page.")
        return HttpResponseRedirect("../")

    members = collect_exportable_members()
    if request.method == "POST":
        if not mailchimp_configured():
            messages.error(
                request,
                "Mailchimp is not configured. Set MAILCHIMP_API_KEY and "
                "MAILCHIMP_AUDIENCE_ID in tokens.env, then run apply-tokens.sh.",
            )
            return HttpResponseRedirect(request.path)
        try:
            result = export_members_to_mailchimp(
                members,
                started_by=request.user.get_username() or "admin",
            )
        except MailchimpError as exc:
            messages.error(request, str(exc))
        else:
            level = messages.WARNING if result.failed else messages.SUCCESS
            messages.add_message(request, level, result.summary())
        return HttpResponseRedirect(request.path)

    context = {
        **admin.site.each_context(request),
        "title": "Mailchimp audience",
        "audience": audience_status(),
        "exportable_count": len(members),
        "latest_runs": MailchimpExportRun.objects.all()[:8],
    }
    return TemplateResponse(request, "admin/core/mailchimp_export.html", context)
