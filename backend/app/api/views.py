"""Staff prayer-request follow-up endpoints.

Chat / public prayer POST live in core.views (production vLLM + Qdrant stack).
"""

from django.conf import settings
from django.shortcuts import get_object_or_404
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import PrayerRequest, ChurchEvent

from .email_notifications import (
    account_recipient_emails,
    email_delivery_configured,
    send_account_notification,
)
from .serializers import (
    ChurchEventSerializer,
    ChurchEventWriteSerializer,
    PrayerRequestSerializer,
    PrayerRequestStaffUpdateSerializer,
    StaffEmailNotificationSerializer,
)


class ChurchEventListCreateAPI(APIView):
    """GET/POST /api/church-events/ — public list; staff create."""

    def get_permissions(self):
        if self.request.method == "POST":
            return [permissions.IsAdminUser()]
        return [permissions.AllowAny()]

    def get(self, request):
        qs = ChurchEvent.objects.all().order_by('starts_at', 'title')
        if not (request.user.is_authenticated and request.user.is_staff):
            qs = qs.filter(is_published=True)
        data = ChurchEventSerializer(qs, many=True).data
        return Response({"results": data})

    def post(self, request):
        serializer = ChurchEventWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        event = serializer.save(created_by=request.user)
        return Response(
            ChurchEventSerializer(event).data,
            status=status.HTTP_201_CREATED,
        )


class ChurchEventDetailAPI(APIView):
    """GET/PATCH/DELETE /api/church-events/<id>/ — public read; staff write."""

    def get_permissions(self):
        if self.request.method == "GET":
            return [permissions.AllowAny()]
        return [permissions.IsAdminUser()]

    def get(self, request, pk):
        event = get_object_or_404(ChurchEvent, pk=pk)
        if not event.is_published and not (
            request.user.is_authenticated and request.user.is_staff
        ):
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(ChurchEventSerializer(event).data)

    def patch(self, request, pk):
        event = get_object_or_404(ChurchEvent, pk=pk)
        serializer = ChurchEventWriteSerializer(event, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(ChurchEventSerializer(event).data)

    def delete(self, request, pk):
        event = get_object_or_404(ChurchEvent, pk=pk)
        event.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class PrayerRequestDetailAPI(APIView):
    """GET/PATCH /api/prayer-requests/<id>/ — staff view and follow-up updates."""

    permission_classes = [permissions.IsAdminUser]

    def get(self, request, pk):
        prayer = get_object_or_404(PrayerRequest, pk=pk)
        return Response(PrayerRequestSerializer(prayer).data)

    def patch(self, request, pk):
        prayer = get_object_or_404(PrayerRequest, pk=pk)
        serializer = PrayerRequestStaffUpdateSerializer(
            prayer,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(PrayerRequestSerializer(prayer).data)


class StaffEmailNotificationAPI(APIView):
    """GET/POST /api/staff/email-notification/ — staff broadcast to all accounts."""

    permission_classes = [permissions.IsAdminUser]

    def get(self, request):
        recipients = account_recipient_emails()
        return Response(
            {
                "recipient_count": len(recipients),
                "from_email": settings.DEFAULT_FROM_EMAIL,
                "email_configured": email_delivery_configured(),
            }
        )

    def post(self, request):
        serializer = StaffEmailNotificationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            result = send_account_notification(
                subject=serializer.validated_data["subject"],
                body=serializer.validated_data["body"],
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            return Response(
                {"detail": f"Could not send email: {exc}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response(
            {
                "success": result["success"],
                "sent": result["sent"],
                "failed": result["failed"],
                "recipient_count": result["recipient_count"],
                "from_email": result["from_email"],
                "message": (
                    f"Sent to {result['sent']} account"
                    f"{'' if result['sent'] == 1 else 's'}."
                    if result["failed"] == 0
                    else (
                        f"Sent to {result['sent']} of {result['recipient_count']} "
                        f"accounts; {result['failed']} failed."
                    )
                ),
            },
            status=status.HTTP_200_OK,
        )
