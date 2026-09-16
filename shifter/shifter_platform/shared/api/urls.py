"""Routes owned by the shared platform boundary."""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from shared.api.audit import AuditLogViewSet

router = DefaultRouter()
router.register(r"audit", AuditLogViewSet, basename="auditlog")

urlpatterns = [path("", include(router.urls))]
