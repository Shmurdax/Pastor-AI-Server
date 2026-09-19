"""Staff prayer-request follow-up endpoints.

Chat / public prayer POST live in core.views (production vLLM + Qdrant stack).
"""

from django.shortcuts import get_object_or_404
from rest_framework import permissions, status
from rest_framework.authentication import TokenAuthentication
from rest_framework.response import Response
from rest_framework.views import APIView

from api.permissions import HasPremiumAccess

from core.models import PrayerRequest, ChurchEvent, ResponseReport

from .media_catalog import public_media_catalog
from .serializers import (
    ChurchEventSerializer,
    ChurchEventWriteSerializer,
    PrayerRequestSerializer,
    PrayerRequestStaffUpdateSerializer,
    ResponseReportSerializer,
    ResponseReportStaffUpdateSerializer,
)


class ChurchEventListCreateAPI(APIView):
    """GET/POST /api/church-events/ — Premium list; staff create."""

    authentication_classes = [TokenAuthentication]

    def get_permissions(self):
        if self.request.method == "POST":
            return [permissions.IsAdminUser()]
        return [permissions.IsAuthenticated(), HasPremiumAccess()]

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
    """GET/PATCH/DELETE /api/church-events/<id>/ — Premium read; staff write."""

    authentication_classes = [TokenAuthentication]

    def get_permissions(self):
        if self.request.method == "GET":
            return [permissions.IsAuthenticated(), HasPremiumAccess()]
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


class ResponseReportDetailAPI(APIView):
    """GET/PATCH /api/response-reports/<id>/ — staff view and status updates."""

    permission_classes = [permissions.IsAdminUser]

    def get(self, request, pk):
        report = get_object_or_404(ResponseReport, pk=pk)
        return Response(ResponseReportSerializer(report).data)

    def patch(self, request, pk):
        from django.utils import timezone

        report = get_object_or_404(ResponseReport, pk=pk)
        serializer = ResponseReportStaffUpdateSerializer(
            report,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        report = serializer.save()
        if "status" in serializer.validated_data:
            if report.status == ResponseReport.Status.NEW:
                report.reviewed_at = None
            else:
                report.reviewed_at = timezone.now()
            report.save(update_fields=["reviewed_at"])
        return Response(ResponseReportSerializer(report).data)


class MediaVideoListAPI(APIView):
    """GET /api/media/ — Premium Daily Devotionals (folder sync + embedded Vimeo)."""

    authentication_classes = [TokenAuthentication]
    permission_classes = [permissions.IsAuthenticated, HasPremiumAccess]

    def get(self, request):
        return Response({"results": public_media_catalog()})
