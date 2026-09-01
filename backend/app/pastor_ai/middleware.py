"""Project middleware."""

from .robots import NOINDEX_HEADER_VALUE, path_requires_noindex


class NoIndexSensitivePathsMiddleware:
    """Send X-Robots-Tag on admin/API responses so indexes drop them even if crawled."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if path_requires_noindex(request.path):
            response["X-Robots-Tag"] = NOINDEX_HEADER_VALUE
        return response
