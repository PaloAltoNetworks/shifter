"""Credential management HTTP edges; services own every authorization decision."""

from typing import Any
from uuid import UUID

from django.db import IntegrityError
from drf_spectacular.utils import extend_schema
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from management import personal_credentials, service_credentials
from management.api.credential_serializers import (
    CreateServiceCredentialSerializer,
    CredentialPageQuerySerializer,
    EmptyCredentialCommandSerializer,
    IssuedPersonalCredentialSerializer,
    IssuePersonalCredentialSerializer,
    PersonalCredentialPageSerializer,
    PersonalCredentialSerializer,
    ServiceCredentialPageSerializer,
    ServiceCredentialSerializer,
    ServicePrincipalUpdateSerializer,
)
from management.services import PrincipalConflictError
from shared.api.errors import api_error_response
from shared.api.permissions import IsAuthenticatedSession, IsAuthenticatedSessionOrApiToken
from shared.api.principals import authenticated_credential
from shared.api.strict_json import ClosedJSONParser
from shared.api_tokens.models import ApiToken
from shared.authorization import AuthorizationProviderBindingError, TargetRef, configured_authorization_provider
from shared.credentials import resolve_credential_scope
from shared.principal_port import PrincipalResolutionError

_SESSION_ONLY_SCHEMA_AUTH: list[dict[str, list[str]]] = [{"cookieAuth": []}]


class CredentialView(APIView):
    """Apply closed JSON parsing, generic denial, and no-store responses."""

    permission_classes = [IsAuthenticatedSessionOrApiToken]
    parser_classes = [ClosedJSONParser]

    def handle_exception(self, exc: Exception) -> Response:
        """Translate credential-policy failures into one generic denial."""
        if isinstance(
            exc,
            (
                ValueError,
                PrincipalResolutionError,
                PrincipalConflictError,
                IntegrityError,
                AuthorizationProviderBindingError,
            ),
        ):
            return api_error_response(
                code="credential_denied", message="Credential operation denied", status_code=403, request=self.request
            )
        return super().handle_exception(exc)

    def finalize_response(self, request: Request, response: Response, *args: object, **kwargs: object) -> Response:
        """Prevent credential metadata or one-time proofs from being cached."""
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "no-store"
        return response


class AdminPersonalCredentialListView(CredentialView):
    """Prepared safe credential inspection, including for inactive owners."""

    @extend_schema(parameters=[CredentialPageQuerySerializer], responses=PersonalCredentialPageSerializer)
    def get(self, request: Request, principal_uuid: UUID) -> Response:
        page = personal_credentials.admin_list_personal_tokens(
            authenticated_credential(request),
            configured_authorization_provider(),
            principal_uuid,
            **_page_arguments(request),
        )
        return Response(PersonalCredentialPageSerializer(page).data)


class AdminPersonalCredentialRevokeView(CredentialView):
    """Prepared administrator revocation; issuance remains a human-owner ceremony."""

    @extend_schema(request=EmptyCredentialCommandSerializer, responses={204: None})
    def post(self, request: Request, credential_uuid: UUID) -> Response:
        command = EmptyCredentialCommandSerializer(data=request.data)
        command.is_valid(raise_exception=True)
        personal_credentials.admin_revoke_personal_token(
            authenticated_credential(request),
            configured_authorization_provider(),
            credential_uuid,
            request=request._request,
        )
        return Response(status=204)


def _issue_arguments(request: Request) -> dict[str, Any]:
    """Build server-owned issuance arguments from a validated command."""
    command = IssuePersonalCredentialSerializer(data=request.data)
    command.is_valid(raise_exception=True)
    values = dict(command.validated_data)
    target = TargetRef(values.pop("target_type"), values.pop("target_uuid", None))
    return {
        **values,
        "actor": authenticated_credential(request),
        "user": request.user,
        "target": target,
        "scope": resolve_credential_scope(target),
    }


def _page_arguments(request: Request) -> dict[str, Any]:
    """Validate and return bounded collection pagination arguments."""
    query = CredentialPageQuerySerializer(data=request.query_params)
    query.is_valid(raise_exception=True)
    return query.validated_data


def _issued_response(result: tuple[ApiToken, str]) -> Response:
    """Return a newly issued raw proof once with safe metadata."""
    token, raw = result
    payload = dict(PersonalCredentialSerializer(token).data)
    payload["token"] = raw
    return Response(payload, status=201)


class PersonalCredentialCollectionView(CredentialView):
    """List and issue credentials owned by the current human session."""

    permission_classes = [IsAuthenticatedSession]

    @extend_schema(
        parameters=[CredentialPageQuerySerializer],
        responses=PersonalCredentialPageSerializer,
        auth=_SESSION_ONLY_SCHEMA_AUTH,  # type: ignore[arg-type]
    )
    def get(self, request: Request) -> Response:
        """List the current user's safe personal credential metadata."""
        items = personal_credentials.list_own_tokens(
            authenticated_credential(request), request.user, **_page_arguments(request)
        )
        return Response(PersonalCredentialPageSerializer(items).data)

    @extend_schema(
        request=IssuePersonalCredentialSerializer,
        responses={201: IssuedPersonalCredentialSerializer},
        auth=_SESSION_ONLY_SCHEMA_AUTH,  # type: ignore[arg-type]
    )
    def post(self, request: Request) -> Response:
        """Issue one bounded personal credential and return its proof once."""
        return _issued_response(personal_credentials.issue_personal_token(**_issue_arguments(request)))


class PersonalCredentialRevokeView(CredentialView):
    """Revoke one credential owned by the current human session."""

    permission_classes = [IsAuthenticatedSession]

    @extend_schema(
        request=EmptyCredentialCommandSerializer,
        responses={204: None},
        auth=_SESSION_ONLY_SCHEMA_AUTH,  # type: ignore[arg-type]
    )
    def post(self, request: Request, credential_uuid: UUID) -> Response:
        """Idempotently revoke an owned personal credential."""
        command = EmptyCredentialCommandSerializer(data=request.data)
        command.is_valid(raise_exception=True)
        personal_credentials.revoke_own_token(authenticated_credential(request), request.user, credential_uuid)
        return Response(status=204)


class PersonalCredentialRotateView(CredentialView):
    """Atomically replace one owned credential with a new proof."""

    permission_classes = [IsAuthenticatedSession]

    @extend_schema(
        request=IssuePersonalCredentialSerializer,
        responses={201: IssuedPersonalCredentialSerializer},
        auth=_SESSION_ONLY_SCHEMA_AUTH,  # type: ignore[arg-type]
    )
    def post(self, request: Request, credential_uuid: UUID) -> Response:
        """Issue a replacement and revoke the selected old credential."""
        return _issued_response(
            personal_credentials.rotate_personal_token(credential_uuid, **_issue_arguments(request))
        )


class ServiceCredentialCollectionView(CredentialView):
    """List and register explicitly admitted native service identities."""

    @extend_schema(parameters=[CredentialPageQuerySerializer], responses=ServiceCredentialPageSerializer)
    def get(self, request: Request) -> Response:
        """List safe service-principal admission metadata."""
        items = service_credentials.list_service_credentials(
            authenticated_credential(request), **_page_arguments(request)
        )
        return Response(ServiceCredentialPageSerializer(items).data)

    @extend_schema(request=CreateServiceCredentialSerializer, responses={201: ServiceCredentialSerializer})
    def post(self, request: Request) -> Response:
        """Register a native Google service identity admission."""
        command = CreateServiceCredentialSerializer(data=request.data)
        command.is_valid(raise_exception=True)
        item = service_credentials.create_service_credential(
            authenticated_credential(request), **command.validated_data
        )
        return Response(ServiceCredentialSerializer(item).data, status=201)


class ServiceCredentialDisableView(CredentialView):
    """Disable one immutable native service admission."""

    @extend_schema(request=EmptyCredentialCommandSerializer, responses={204: None})
    def post(self, request: Request, credential_uuid: UUID) -> Response:
        """Disable admission while retaining its audit identity."""
        command = EmptyCredentialCommandSerializer(data=request.data)
        command.is_valid(raise_exception=True)
        service_credentials.disable_service_credential(authenticated_credential(request), credential_uuid)
        return Response(status=204)


class ServicePrincipalUpdateView(CredentialView):
    """Update independent service lifecycle and responsible contact."""

    @extend_schema(request=ServicePrincipalUpdateSerializer, responses={204: None})
    def post(self, request: Request, principal_uuid: UUID) -> Response:
        """Apply lifecycle or contact changes without transferring identity."""
        command = ServicePrincipalUpdateSerializer(data=request.data)
        command.is_valid(raise_exception=True)
        service_credentials.update_service_principal(
            authenticated_credential(request), principal_uuid, **command.validated_data
        )
        return Response(status=204)
