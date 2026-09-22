"""Public deploy/health JSON for operators (no secrets)."""

from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .deploy_status import read_deploy_status


class DeployHealthView(APIView):
    """Report whether this checkout matches origin of its git channel."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        return Response(read_deploy_status())
