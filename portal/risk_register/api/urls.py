"""API URL routing for Risk Register."""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from risk_register.api import views

router = DefaultRouter()
router.register(r"risks", views.RiskViewSet, basename="risk")
router.register(r"api-keys", views.APIKeyViewSet, basename="apikey")

urlpatterns = [
    path("", include(router.urls)),
    # Nested comment routes
    path(
        "risks/<int:risk_pk>/comments/",
        views.CommentViewSet.as_view({"get": "list", "post": "create"}),
        name="risk-comments-list",
    ),
    path(
        "risks/<int:risk_pk>/comments/<int:pk>/",
        views.CommentViewSet.as_view({"delete": "destroy"}),
        name="risk-comments-detail",
    ),
]
