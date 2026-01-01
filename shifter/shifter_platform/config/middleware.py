"""Custom middleware for Shifter platform."""

from django.http import HttpResponse


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
