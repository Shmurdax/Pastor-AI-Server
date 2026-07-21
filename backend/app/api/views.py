"""Staff prayer-request follow-up endpoints.

Chat / public prayer POST live in core.views (production vLLM + Qdrant stack).
"""

from django.shortcuts import get_object_or_404
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import PrayerRequest

from .serializers import PrayerRequestSerializer, PrayerRequestStaffUpdateSerializer


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
