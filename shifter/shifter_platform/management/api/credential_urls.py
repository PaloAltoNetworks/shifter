"""Canonical credential management routes."""

from django.urls import path

from .credential_views import (
    PersonalCredentialCollectionView,
    PersonalCredentialRevokeView,
    PersonalCredentialRotateView,
    ServiceCredentialCollectionView,
    ServiceCredentialDisableView,
    ServicePrincipalUpdateView,
)

urlpatterns = [
    path(
        "services/principals/<uuid:principal_uuid>/",
        ServicePrincipalUpdateView.as_view(),
        name="service-principal-update",
    ),
    path("personal/", PersonalCredentialCollectionView.as_view(), name="personal-credentials"),
    path(
        "personal/<uuid:credential_uuid>/revoke/",
        PersonalCredentialRevokeView.as_view(),
        name="personal-credential-revoke",
    ),
    path(
        "personal/<uuid:credential_uuid>/rotate/",
        PersonalCredentialRotateView.as_view(),
        name="personal-credential-rotate",
    ),
    path("services/", ServiceCredentialCollectionView.as_view(), name="service-credentials"),
    path(
        "services/<uuid:credential_uuid>/disable/",
        ServiceCredentialDisableView.as_view(),
        name="service-credential-disable",
    ),
]
