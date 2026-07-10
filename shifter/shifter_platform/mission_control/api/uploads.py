"""Upload DRF views for Mission Control."""

from __future__ import annotations

import logging
import os
from typing import Any

from django.contrib.auth.models import User
from rest_framework.exceptions import ParseError
from rest_framework.request import Request
from rest_framework.response import Response

from cms.services import cancel_upload as cms_cancel_upload
from cms.services import complete_upload as cms_complete_upload
from cms.services import initiate_upload as cms_initiate_upload
from mission_control.api._base import MissionControlAPIView, _upload_write_permission, _validated
from mission_control.api.permissions import HasMissionControlActor
from mission_control.api.serializers import UploadCancelSerializer, UploadCompleteSerializer, UploadInitiateSerializer
from mission_control.upload_session import check_upload_in_progress, set_upload_in_progress, upload_lock_matches_token
from shared.api.permissions import IsAuthenticatedSessionOrApiToken
from shared.api_tokens.models import ApiToken
from shared.errors import classify_user_message
from shared.exceptions import CMSError
from shared.log_sanitize import safe_log_value

logger = logging.getLogger(__name__)


class UploadInitiateView(MissionControlAPIView):
    """Initiate a presigned agent upload."""

    permission_classes = [IsAuthenticatedSessionOrApiToken, HasMissionControlActor, _upload_write_permission()]

    def post(self, request: Request) -> Response:
        """Create an upload session and presigned destination for an agent."""
        if check_upload_in_progress(request.session):
            return self.error_response(
                code="conflict",
                message="An upload is already in progress. Please wait for it to complete.",
                status_code=409,
            )

        data, error = _validated(self, UploadInitiateSerializer, request.data)
        if error is not None:
            return error
        assert data is not None

        user = self.actor_user()
        return self._initiate_upload(request, user, data)

    def _initiate_upload(self, request: Request, user: User, data: dict[str, Any]) -> Response:
        """Create the presigned upload and mark the session upload state."""
        filename = os.path.basename(data["filename"])
        try:
            result = cms_initiate_upload(user, data["name"], filename, data["file_size"], data["agent_type"])
        except CMSError as exc:
            logger.exception(
                "Upload initiation failed: user=%s filename=%s",
                safe_log_value(user.email),
                safe_log_value(filename),
            )
            return self.bad_request(classify_user_message(str(exc), default="Upload could not be initiated"))

        set_upload_in_progress(request.session, True, upload_token=str(result["upload_token"]))
        safe_filename = filename.replace("\r", " ").replace("\n", " ").replace("\t", " ")[:200]
        safe_email = user.email.replace("\r", " ").replace("\n", " ").replace("\t", " ")[:200]
        logger.info("Upload initiated: user=%s filename=%s size=%d", safe_email, safe_filename, data["file_size"])
        return Response(result)


class UploadCompleteView(MissionControlAPIView):
    """Complete a presigned agent upload."""

    permission_classes = [IsAuthenticatedSessionOrApiToken, HasMissionControlActor, _upload_write_permission()]

    def post(self, request: Request) -> Response:
        """Finalize a completed upload and clear the session upload marker."""
        data, error = _validated(self, UploadCompleteSerializer, request.data)
        if error is not None:
            return error
        assert data is not None

        user = self.actor_user()
        try:
            agent = cms_complete_upload(user, data.get("upload_token", ""))
        except CMSError as exc:
            set_upload_in_progress(request.session, False)
            logger.exception("Upload completion failed: user=%s", user.pk)
            return self.bad_request(classify_user_message(str(exc), default="Upload could not be completed"))

        set_upload_in_progress(request.session, False)
        logger.info("Upload completed: user=%s agent_id=%s", safe_log_value(user.email), agent.id)
        return Response(
            {
                "success": True,
                "agent_id": agent.id,
                "message": f"Agent '{agent.name}' uploaded successfully.",
            }
        )


class UploadCancelView(MissionControlAPIView):
    """Cancel an in-progress agent upload."""

    permission_classes = [IsAuthenticatedSessionOrApiToken, HasMissionControlActor, _upload_write_permission()]

    def _has_cancel_authority(self, request: Request, upload_token: str) -> bool:
        return isinstance(getattr(request, "auth", None), ApiToken) or upload_lock_matches_token(
            request.session, upload_token
        )

    def post(self, request: Request) -> Response:
        """Cancel a validated current upload and clear the session marker."""
        try:
            raw_data = request.data
        except ParseError:
            return self.bad_request("Invalid request")
        data, error = _validated(self, UploadCancelSerializer, raw_data)
        if error is not None:
            return error
        assert data is not None

        upload_token = data["upload_token"]
        user = self.actor_user()
        if self._has_cancel_authority(request, upload_token):
            try:
                # CMS validates the token and absorbs best-effort storage cleanup failures.
                cms_cancel_upload(user, upload_token)
                logger.info("Cancelled upload cleaned up: user=%s", safe_log_value(user.email))
            except (ValueError, CMSError):
                response = self.bad_request("Upload cancel token is invalid or stale")
            else:
                set_upload_in_progress(request.session, False)
                response = Response({"success": True})
        else:
            response = self.bad_request("Upload cancel token is invalid or stale")

        return response
