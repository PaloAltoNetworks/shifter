"""Session-authenticated tenant pack installation; multipart bytes are bounded."""

from uuid import UUID

from django.conf import settings
from django.core.files.uploadhandler import FileUploadHandler, StopUpload
from django.http import HttpRequest
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.parsers import MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from cms.services._tenant_pack_upload import upload_tenant_pack
from shared.api.errors import api_error_response
from shared.api.permissions import IsAuthenticatedSession
from shared.audit import get_request_id
from shared.exceptions import ValidationError
from workspaces.services import OrganizationAuthorizationError, get_organization_profile

from .preparation_adapters import PreparationSerializer


class _BoundedUpload(FileUploadHandler):
    """Stop multipart ingestion once the archive byte budget is exhausted."""

    def __init__(self, request: HttpRequest) -> None:
        super().__init__(request)
        self.received = 0
        self.exceeded = False

    def receive_data_chunk(self, raw_data: bytes, start: int) -> bytes:
        self.received += len(raw_data)
        if self.received > settings.RAES_PACKAGE_MAX_ARCHIVE_BYTES:
            self.exceeded = True
            raise StopUpload(connection_reset=True)
        return raw_data

    def file_complete(self, file_size: int) -> None:
        return None


class TenantPackUploadSerializer(PreparationSerializer):
    """Named pack archive with an optional expected revision digest."""

    name = serializers.RegexField(r"^[A-Za-z0-9_-]{1,100}$")
    archive = serializers.FileField()
    expected_digest = serializers.RegexField(r"^(sha256:[a-f0-9]{64})?$", required=False, default="", allow_blank=True)


class TenantPackInstalledSerializer(serializers.Serializer):
    """The immutable registered pack identity and conformance result."""

    scenario_id = serializers.CharField()
    name = serializers.CharField()
    source_kind = serializers.CharField()
    contract_kind = serializers.CharField()
    contract_profile = serializers.CharField()
    package_version = serializers.CharField()
    package_digest = serializers.CharField()
    conformance_status = serializers.CharField()
    created = serializers.BooleanField()


class TenantPackUploadView(APIView):
    """Validate and install an organization-owned scenario pack."""

    permission_classes = [IsAuthenticatedSession]
    parser_classes = [MultiPartParser]

    def initialize_request(self, request: HttpRequest, *args: object, **kwargs: object) -> Request:
        # Must precede session/CSRF authentication, which may parse request.POST.
        request.upload_handlers.insert(0, _BoundedUpload(request))
        return super().initialize_request(request, *args, **kwargs)

    @extend_schema(request=TenantPackUploadSerializer, responses={201: TenantPackInstalledSerializer})
    def post(self, request: Request, organization_uuid: UUID) -> Response:
        try:
            get_organization_profile(request.user, organization_uuid)
            data = request.data
            if any(getattr(handler, "exceeded", False) for handler in request._request.upload_handlers):
                raise ValidationError("The pack archive exceeds its size limit")
            if any(len(data.getlist(key)) != 1 for key in data):
                raise ValidationError("Submit each pack field exactly once")
            serializer = TenantPackUploadSerializer(data=data)
            serializer.is_valid(raise_exception=True)
            result = upload_tenant_pack(
                user=request.user,
                organization_uuid=organization_uuid,
                request_id=get_request_id(request._request),
                **serializer.validated_data,
            )
            return Response(result, status=201)
        except (OrganizationAuthorizationError, ValidationError) as exc:
            denied = isinstance(exc, OrganizationAuthorizationError)
            return api_error_response(
                code="pack_access_denied" if denied else "pack_invalid",
                message=exc.message if isinstance(exc, ValidationError) else "Organization access denied",
                status_code=403 if denied else 400,
                request=request,
            )
