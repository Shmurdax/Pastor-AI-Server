"""Staff prayer-request follow-up endpoints.

Chat / public prayer POST live in core.views (production vLLM + Qdrant stack).
"""

from pathlib import Path

from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from rest_framework import permissions, status
from rest_framework.authentication import TokenAuthentication
from rest_framework.response import Response
from rest_framework.views import APIView

from api.permissions import HasPremiumAccess

from core.models import PrayerRequest, ChurchEvent, ResponseReport

from .serializers import (
    ChurchEventSerializer,
    ChurchEventWriteSerializer,
    MediaVideoSerializer,
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


class MediaTopicListAPI(APIView):
    """GET /api/media/topics/ — topics from episode notes linked to published videos."""

    authentication_classes = [TokenAuthentication]
    permission_classes = [permissions.IsAuthenticated, HasPremiumAccess]

    def get(self, request):
        from .episode_notes import list_media_topics

        return Response({"results": list_media_topics()})


class MediaVideoListAPI(APIView):
    """GET /api/media/ — Premium list of published Walk through the Word videos.

    Optional ``q`` matches the title, description, note text, and topics.
    Optional ``topic`` keeps episodes whose notes include that topic.
    """

    authentication_classes = [TokenAuthentication]
    permission_classes = [permissions.IsAuthenticated, HasPremiumAccess]

    def get(self, request):
        from .episode_notes import search_published_media

        matches = search_published_media(
            query=request.query_params.get("q") or "",
            topic=request.query_params.get("topic") or "",
        )
        videos = [item["video"] for item in matches]
        rows = MediaVideoSerializer(videos, many=True).data
        for row, item in zip(rows, matches):
            row["note"] = item["note"]
        return Response({"results": rows})


class EpisodeNoteDetailAPI(APIView):
    """GET /api/episode-notes/<id>/ — reflowed notes for one published episode."""

    authentication_classes = [TokenAuthentication]
    permission_classes = [permissions.IsAuthenticated, HasPremiumAccess]

    def get(self, request, note_id: int):
        from .episode_notes import visible_note

        note = visible_note(note_id)
        if note is None:
            raise Http404("Notes were not found.")
        return Response(
            {
                "id": note.pk,
                "episode_date": note.episode_date.isoformat(),
                "topics": [str(item) for item in (note.topics or [])],
                "body": note.search_text,
                "original_filename": note.original_filename,
                "has_notes": True,
            }
        )


class EpisodeNoteFileAPI(APIView):
    """GET /api/episode-notes/<id>/file/ — original PDF, not a sermon-library file."""

    authentication_classes = [TokenAuthentication]
    permission_classes = [permissions.IsAuthenticated, HasPremiumAccess]

    def get(self, request, note_id: int):
        from .episode_notes import note_file_path, visible_note

        note = visible_note(note_id)
        if note is None:
            raise Http404("Notes were not found.")
        path = note_file_path(note)
        if not path.is_file():
            raise Http404("Notes were not found.")
        filename = Path(note.original_filename).name.replace('"', "") or path.name
        return FileResponse(
            path.open("rb"),
            content_type="application/pdf",
            filename=filename,
            as_attachment=False,
        )
