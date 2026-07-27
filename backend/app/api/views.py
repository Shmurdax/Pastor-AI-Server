"""Staff prayer-request follow-up endpoints.

Chat / public prayer POST live in core.views (production vLLM + Qdrant stack).
"""

from django.shortcuts import get_object_or_404
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import PrayerRequest, ChurchEvent

from .serializers import (
    ChurchEventSerializer,
    ChurchEventWriteSerializer,
    PrayerRequestSerializer,
    PrayerRequestStaffUpdateSerializer,
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
