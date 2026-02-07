"""Custom middleware for Shifter platform."""

import uuid

from django.http import HttpResponse


class RequestIDMiddleware:
    """Add request ID to all requests for trace correlation.

    Preserves incoming X-Request-ID header if present, otherwise generates
    a new UUID. The request ID is available on the request object and
    included in the response header.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Get existing request ID or generate new one
        request_id = request.META.get("HTTP_X_REQUEST_ID")
        if not request_id:
            request_id = str(uuid.uuid4())[:8]

        # Store on request object for access by views and audit logging
        request.request_id = request_id

        response = self.get_response(request)

        # Include in response for client correlation
        response["X-Request-ID"] = request_id

        return response


class HealthCheckMiddleware:
    """Allow health check requests to bypass ALLOWED_HOSTS validation.

    ALB health checks use internal IP addresses as the Host header,
    which aren't in ALLOWED_HOSTS. This middleware intercepts health
    check requests early and returns a simple 200 OK response.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Handle health check requests before host validation
        if request.path in ("/health", "/health/"):
            return HttpResponse("OK", content_type="text/plain")
        return self.get_response(request)
