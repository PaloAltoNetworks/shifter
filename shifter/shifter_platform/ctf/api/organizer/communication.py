"""Scoped communication REST controllers; services own live policy and writes."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from django.contrib.auth.models import User
from django.db import transaction
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

import workspaces.services as ws
from ctf.api._base import HasActiveCTFActor, ctf_error_response
from ctf.api.communication_schema import CommunicationSchema
from ctf.api.serializers.communication import (
    CommunicationCampaignSummarySerializer,
    CommunicationCreateSerializer,
    CommunicationEmptySerializer,
    CommunicationIntentSerializer,
    CommunicationJSONParser,
    CommunicationReleaseSerializer,
    CommunicationRevisionSerializer,
)
from ctf.exceptions import CTFCommunicationError, CTFError
from ctf.models import CommunicationCampaign, MessageRevision
from ctf.services.communication import (
    AdmissionActor,
    CampaignDraft,
    cancel_campaign,
    create_campaign,
    release_campaign,
    revise_message,
    schedule_declaration,
)
from ctf.services.communication.admission import reauthorize
from ctf.services.communication.selection import visible_campaigns
from shared.api.closed_serializer import ClosedSerializer
from shared.api.permissions import IsAuthenticatedSessionOrApiToken
from shared.api.principals import active_actor_user
from shared.api_tokens.models import ApiToken
from shared.api_tokens.permissions import require_scope
from shared.api_tokens.scopes import CTF_COMMUNICATION_READ, CTF_COMMUNICATION_WRITE


class CampaignQuerySerializer(ClosedSerializer):
    """Finite, deterministic workspace collections."""

    workspace_id = serializers.UUIDField()
    event_id = serializers.UUIDField(required=False)
    limit = serializers.IntegerField(min_value=1, max_value=100, default=25)
    offset = serializers.IntegerField(min_value=0, max_value=100000, default=0)


class CampaignListSerializer(serializers.Serializer):
    """A bounded page; offset advances across authorized workspace candidates."""

    results = CommunicationCampaignSummarySerializer(many=True)
    next_offset = serializers.IntegerField(allow_null=True)


def _request_user(request: Request) -> User:
    """Resolve the effective principal or fail before using account authority."""
    user = active_actor_user(request)
    if user is None:
        raise CTFCommunicationError("Unavailable", code="CTF_COMMUNICATION_ACTOR_DENIED")
    return user


def request_actor(request: Request) -> AdmissionActor:
    """Use the authenticated token principal independently of request.user."""
    user = _request_user(request)
    token = request.auth if isinstance(request.auth, ApiToken) else None
    from shared.audit import get_request_id

    return AdmissionActor(user_id=user.pk, token_id=token.pk if token else None, request_id=get_request_id(request))


def validate_query(request: Request, serializer_class: type[ClosedSerializer]) -> dict[str, Any]:
    """Reject unknown or repeated query parameters before validation."""

    if any(len(request.query_params.getlist(key)) != 1 for key in request.query_params):
        raise serializers.ValidationError("Invalid value.")
    serializer = serializer_class(data=request.query_params.dict())
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


class CommunicationView(APIView):
    """Bearer-first auth, closed JSON and canonical domain error translation."""

    schema = CommunicationSchema()
    permission_classes = [
        IsAuthenticatedSessionOrApiToken,
        HasActiveCTFActor,
        require_scope(CTF_COMMUNICATION_READ, CTF_COMMUNICATION_WRITE),
    ]
    parser_classes = [CommunicationJSONParser]

    def handle_exception(self, exc: Exception) -> Response:
        if isinstance(exc, CTFError):
            return ctf_error_response(self.request, exc)
        if isinstance(exc, serializers.ValidationError):
            from shared.api.errors import api_error_response

            return api_error_response(code="invalid", message="Invalid request", status_code=400, request=self.request)
        return super().handle_exception(exc)

    def campaign(self, request: Request, campaign_id: UUID) -> CommunicationCampaign:
        campaign = CommunicationCampaign.objects.prefetch_related("target_events").filter(pk=campaign_id).first()
        if campaign is None:
            raise CTFCommunicationError("Unavailable", code="CTF_COMMUNICATION_NOT_FOUND")
        with transaction.atomic():
            reauthorize(
                campaign,
                list(campaign.target_events.all()),
                request_actor(request),
                required_scope=CTF_COMMUNICATION_READ if request.method == "GET" else CTF_COMMUNICATION_WRITE,
                audit_authority=False,
            )
        return campaign

    def input(self, request: Request, serializer_class: type[ClosedSerializer]) -> dict[str, Any]:
        validate_query(request, CommunicationEmptySerializer)
        serializer = serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data


class CommunicationListView(CommunicationView):
    """Create or list campaigns within one authorized workspace."""

    @extend_schema(
        operation_id="ctf_communications_list", parameters=[CampaignQuerySerializer], responses=CampaignListSerializer
    )
    def get(self, request: Request) -> Response:
        query = validate_query(request, CampaignQuerySerializer)
        try:
            binding = ws.authorize_workspace(
                _request_user(request), query["workspace_id"], ws.WorkspaceOperation.USE_CTF_COMMUNICATIONS
            )
        except ws.WorkspaceAuthorizationError:
            raise CTFCommunicationError("Unavailable", code="CTF_COMMUNICATION_WORKSPACE_DENIED") from None
        start, limit = query["offset"], query["limit"]
        queryset = visible_campaigns(_request_user(request), workspace_id=binding.workspace_id)
        if "event_id" in query:
            queryset = queryset.filter(target_events__pk=query["event_id"])
        candidates = list(
            queryset.prefetch_related("target_events").order_by("created_at", "pk")[start : start + limit + 1]
        )
        visible = []
        with transaction.atomic():
            for campaign in candidates[:limit]:
                reauthorize(
                    campaign,
                    list(campaign.target_events.all()),
                    request_actor(request),
                    required_scope=CTF_COMMUNICATION_READ,
                )
                visible.append(campaign)
        return Response(
            {
                "results": CommunicationCampaignSummarySerializer(visible, many=True).data,
                "next_offset": start + limit if len(candidates) > limit else None,
            }
        )

    @extend_schema(request=CommunicationCreateSerializer, responses={201: CommunicationCampaignSummarySerializer})
    def post(self, request: Request) -> Response:
        data = self.input(request, CommunicationCreateSerializer)
        workspace_id = data.pop("workspace_id")
        actor = request_actor(request)
        campaign = create_campaign(
            _request_user(request),
            workspace_id,
            CampaignDraft(**data, origin="organizer_staff", actor_token_id=actor.token_id),
            actor=actor,
        )
        return Response(CommunicationCampaignSummarySerializer(campaign).data, status=201)


class CommunicationDetailView(CommunicationView):
    """Project a campaign only after complete-target authorization."""

    @extend_schema(responses=CommunicationCampaignSummarySerializer)
    def get(self, request: Request, campaign_id: UUID) -> Response:
        validate_query(request, CommunicationEmptySerializer)
        return Response(CommunicationCampaignSummarySerializer(self.campaign(request, campaign_id)).data)


class CommunicationRevisionView(CommunicationView):
    """Append validated content to an authorized draft campaign."""

    @extend_schema(request=CommunicationRevisionSerializer, responses={201: CommunicationCampaignSummarySerializer})
    def post(self, request: Request, campaign_id: UUID) -> Response:
        data = self.input(request, CommunicationRevisionSerializer)
        campaign = self.campaign(request, campaign_id)
        revise_message(campaign, actor=request_actor(request), **data)
        return Response(CommunicationCampaignSummarySerializer(campaign).data, status=201)


class CommunicationReleaseView(CommunicationView):
    """Accept a release or schedule declaration through the ledger."""

    @extend_schema(request=CommunicationReleaseSerializer, responses={202: CommunicationIntentSerializer})
    def post(self, request: Request, campaign_id: UUID) -> Response:
        data = self.input(request, CommunicationReleaseSerializer)
        campaign = self.campaign(request, campaign_id)
        revision = None
        if "revision_id" in data:
            revision = MessageRevision.objects.filter(pk=data["revision_id"], campaign=campaign).first()
            if revision is None:
                raise CTFCommunicationError("Unavailable", code="CTF_COMMUNICATION_NOT_FOUND")
        from ctf.services.communication.adapters import registered_channels

        if set(campaign.channels) - set(registered_channels()):
            raise CTFCommunicationError("Channel unavailable", code="CTF_COMMUNICATION_CHANNEL_UNAVAILABLE")
        kwargs = {"occurrence_key": data["occurrence_key"], "revision": revision}
        actor = request_actor(request)
        if campaign.trigger_spec["kind"] == "absolute_time":
            intent = schedule_declaration(
                campaign, due_at=datetime.fromisoformat(campaign.trigger_spec["due_at"]), actor=actor, **kwargs
            )
        else:
            intent = release_campaign(campaign, admission=actor, **kwargs)
        return Response(CommunicationIntentSerializer(intent).data, status=202)


class CommunicationCancelView(CommunicationView):
    """Cancel unclaimed work for an authorized campaign."""

    @extend_schema(request=CommunicationEmptySerializer, responses=CommunicationCampaignSummarySerializer)
    def post(self, request: Request, campaign_id: UUID) -> Response:
        self.input(request, CommunicationEmptySerializer)
        campaign = self.campaign(request, campaign_id)
        cancel_campaign(campaign, actor=request_actor(request))
        campaign.refresh_from_db()
        return Response(CommunicationCampaignSummarySerializer(campaign).data)
