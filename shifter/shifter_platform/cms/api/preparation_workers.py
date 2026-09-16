"""Private worker transport authenticated independently of platform users."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from drf_spectacular.utils import extend_schema
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from cms.api.preparation_adapters import preparation_error
from engine.services import read_preparation_worker_input, record_preparation_worker_result
from shared.exceptions import ValidationError

_AUTHENTICATION_FAILED = "Preparation worker authentication failed"


@dataclass(frozen=True)
class PreparationWorkerPrincipal:
    """This principal has no platform user, token scopes, or ambient privileges."""

    operation_id: UUID
    is_authenticated: bool = True


@dataclass(frozen=True)
class PreparationWorkerCredential:
    """Keep the bearer credential out of object representations and diagnostics."""

    token: str = field(repr=False)


class PreparationWorkerAuthentication(BaseAuthentication):
    """Validate the exact attempt before granting access to either transport verb."""

    def authenticate(self, request: Request) -> tuple[PreparationWorkerPrincipal, PreparationWorkerCredential]:
        header = get_authorization_header(request)
        if len(header) > 300:
            raise AuthenticationFailed(_AUTHENTICATION_FAILED)
        parts = header.split()
        if len(parts) != 2 or parts[0].lower() != b"bearer":
            raise AuthenticationFailed(_AUTHENTICATION_FAILED)
        try:
            token = parts[1].decode("ascii")
            operation_id = request.parser_context["kwargs"]["operation_id"]
            read_preparation_worker_input(operation_id, token)
        except (UnicodeError, ValidationError) as exc:
            raise AuthenticationFailed(_AUTHENTICATION_FAILED) from exc
        return PreparationWorkerPrincipal(operation_id), PreparationWorkerCredential(token)

    def authenticate_header(self, request: Request) -> str:
        """Advertise this endpoint's independently scoped bearer challenge."""
        return 'Bearer realm="artifact-preparation"'


class IsPreparationWorker(BasePermission):
    """A logged-in platform administrator is still not a preparation worker."""

    def has_permission(self, request: Request, view: APIView) -> bool:
        return isinstance(request.user, PreparationWorkerPrincipal) and isinstance(
            request.auth, PreparationWorkerCredential
        )


class PreparationWorkerView(APIView):
    """Read one input and append one result; neither operation admits inventory."""

    authentication_classes = [PreparationWorkerAuthentication]
    permission_classes = [IsPreparationWorker]

    @extend_schema(exclude=True)
    def get(self, request: Request, operation_id: UUID) -> Response:
        """Return only the authenticated attempt's immutable input envelope."""
        try:
            return Response(read_preparation_worker_input(operation_id, request.auth.token))
        except ValidationError as exc:
            return preparation_error(request, exc)

    @extend_schema(exclude=True)
    def post(self, request: Request, operation_id: UUID) -> Response:
        """A successful HTTP response acknowledges receipt, never artifact readiness."""
        try:
            status = record_preparation_worker_result(operation_id, request.auth.token, request.data)
        except ValidationError as exc:
            return preparation_error(request, exc)
        return Response({"status": status}, status=202)
