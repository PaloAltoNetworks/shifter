"""NGFW and credential DRF views for Mission Control."""

from __future__ import annotations

import logging

from django.http import Http404, JsonResponse
from rest_framework.request import Request
from rest_framework.response import Response

from cms.services import delete_credential as cms_delete_credential
from cms.services import list_ngfws as cms_list_ngfws
from mission_control.api._base import (
    MissionControlAPIView,
    MissionControlReadAPIView,
    _credentials_write_permission,
    _ngfw_read_permission,
    _ngfw_write_permission,
    _validated,
)
from mission_control.api.permissions import HasMissionControlActor
from mission_control.api.serializers import (
    CredentialCreateSerializer,
    NGFWCreateSerializer,
    NGFWDestroySerializer,
)
from mission_control.views._common import _pkg
from mission_control.views._credentials import _CredentialError, _persist_credential, _validate_credential_spec
from mission_control.views._ngfw import _extract_ngfw_create_payload, _NgfwError, _run_ngfw_destroy
from shared.api.permissions import IsAuthenticatedSessionOrApiToken
from shared.errors import classify_user_message
from shared.exceptions import CMSError
from shared.log_sanitize import safe_log_value

logger = logging.getLogger(__name__)


class NGFWCreateView(MissionControlAPIView):
    """Create a new NGFW."""

    permission_classes = [IsAuthenticatedSessionOrApiToken, HasMissionControlActor, _ngfw_write_permission()]

    def post(self, request: Request) -> Response | JsonResponse:
        """Start NGFW provisioning for the authenticated actor."""
        data, error = _validated(self, NGFWCreateSerializer, request.data)
        if error is not None:
            return error
        assert data is not None
        user = self.actor_user()
        payload = _extract_ngfw_create_payload(data)
        try:
            ngfw_ref = _pkg().cms_create_ngfw(user=user, **payload)
        except (TypeError, ValueError, CMSError) as exc:
            logger.exception("NGFW creation failed: user=%s name=%s", user.pk, safe_log_value(payload.get("name", "")))
            return self.bad_request(classify_user_message(str(exc), default="NGFW could not be created"))

        logger.info("NGFW provisioning started: user=%s app_id=%s", safe_log_value(user.email), ngfw_ref.app_id)
        return Response({"id": str(ngfw_ref.app_id), "name": payload["name"], "status": "provisioning"}, status=201)


class NGFWListView(MissionControlReadAPIView):
    """List user's NGFWs."""

    permission_classes = [IsAuthenticatedSessionOrApiToken, HasMissionControlActor, _ngfw_read_permission()]

    def get(self, request: Request) -> Response:
        """Return NGFWs owned by the authenticated actor."""
        ngfws = cms_list_ngfws(self.actor_user())
        return Response(
            {
                "ngfws": [
                    {
                        "id": str(n.app_id),
                        "name": n.name,
                        "status": n.status,
                        "created_at": n.created_at.isoformat(),
                        "serial_number": n.serial_number,
                    }
                    for n in ngfws
                ]
            }
        )


class NGFWDestroyView(MissionControlAPIView):
    """Destroy an NGFW."""

    permission_classes = [IsAuthenticatedSessionOrApiToken, HasMissionControlActor, _ngfw_write_permission()]

    def post(self, request: Request, app_id: str) -> Response | JsonResponse:
        """Start NGFW deprovisioning for the requested app id."""
        data, error = _validated(self, NGFWDestroySerializer, request.data)
        if error is not None:
            return error
        assert data is not None
        user = self.actor_user()
        try:
            _run_ngfw_destroy(user, app_id, data.get("confirm_name", ""))
        except Http404:
            raise
        except _NgfwError as err:
            return err.response

        logger.info(
            "NGFW deprovisioning started: user=%s app_id=%s",
            safe_log_value(user.email),
            safe_log_value(app_id),
        )
        return Response({"status": "deprovisioning"})


class CredentialCreateView(MissionControlAPIView):
    """Create a credential."""

    permission_classes = [IsAuthenticatedSessionOrApiToken, HasMissionControlActor, _credentials_write_permission()]

    def post(self, request: Request) -> Response | JsonResponse:
        """Validate and persist a Mission Control credential."""
        data, error = _validated(self, CredentialCreateSerializer, request.data)
        if error is not None:
            return error
        assert data is not None

        user = self.actor_user()
        credential_type_slug = data["credential_type"]
        payload = dict(data)
        payload["user_id"] = user.id
        if payload.get("expires_at") == "":
            payload["expires_at"] = None
        try:
            spec = _validate_credential_spec(payload, credential_type_slug)
            kwargs = spec.model_dump(exclude={"user_id"})
            cred_ref = _persist_credential(user, credential_type_slug, kwargs)
        except _CredentialError as err:
            return err.response

        logger.info(
            "Credential created: user=%s credential_id=%s type=%s",
            safe_log_value(user.email),
            cred_ref.credential_id,
            safe_log_value(credential_type_slug),
        )
        return Response({"id": cred_ref.credential_id, "name": spec.name, "credential_type": credential_type_slug}, 201)


class CredentialDeleteView(MissionControlAPIView):
    """Soft-delete a credential."""

    permission_classes = [IsAuthenticatedSessionOrApiToken, HasMissionControlActor, _credentials_write_permission()]

    def post(self, request: Request, credential_id: int) -> Response:
        """Delete a credential visible to the authenticated actor."""
        user = self.actor_user()
        try:
            cms_delete_credential(user, credential_id)
        except CMSError:
            raise Http404("Credential not found") from None

        logger.info(
            "Credential deleted: user=%s credential_id=%s",
            safe_log_value(user.email),
            safe_log_value(credential_id),
        )
        return Response({"success": True})
