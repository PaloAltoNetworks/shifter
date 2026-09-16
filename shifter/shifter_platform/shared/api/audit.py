"""Staff-session-only read API for durable audit events."""

from __future__ import annotations

import logging
from datetime import datetime

from django.db.models import QuerySet
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import permissions, serializers, viewsets
from rest_framework.authentication import SessionAuthentication
from rest_framework.request import Request
from rest_framework.views import APIView

from shared.api.permissions import IsStaffSession
from shared.api_tokens.authentication import ApiTokenAuthentication
from shared.audit import AuditAction, AuditEntityType, audit_log_from_request
from shared.models import AuditLog

logger = logging.getLogger(__name__)

# Bearer-first, fail-closed authentication chain (matches the Administer surface).
# ApiTokenAuthentication runs first so an invalid or revoked ``shf_`` bearer
# credential is rejected outright and never falls through to the session; a valid
# platform token authenticates as an ApiToken principal, which the session-only
# permission then rejects. The audit read is deliberately not token-capable.
_AUDIT_AUTHENTICATION = [ApiTokenAuthentication, SessionAuthentication]

# Validated query parameter -> AuditLog queryset lookup. Exact scalar filters over
# indexed fields; the time bounds map to the timestamp range.
_AUDIT_FILTERS = {
    "entity_type": "entity_type",
    "entity_id": "entity_id",
    "action": "action",
    "actor_type": "actor_type",
    "actor_id": "actor_id",
    "request_id": "request_id",
    "from_date": "timestamp__gte",
    "to_date": "timestamp__lte",
}


class AuditLogSerializer(serializers.ModelSerializer):
    """Read-only audit-event representation."""

    # Historical rows can contain retired vocabulary, so these are strings
    # rather than a closed OpenAPI enum.
    entity_type = serializers.CharField(read_only=True)
    action = serializers.CharField(read_only=True)

    class Meta:
        """Bind the serializer to the immutable audit model."""

        model = AuditLog
        fields = [
            "id",
            "entity_type",
            "entity_id",
            "action",
            "actor_type",
            "actor_id",
            "timestamp",
            "previous_state",
            "new_state",
            "context",
            "source_ip",
            "user_agent",
            "request_id",
        ]
        read_only_fields = fields


class AuditLogQuerySerializer(serializers.Serializer):
    """Typed, bounded filters for the audit read API.

    Backs OpenAPI generation and validates the request before it reaches the
    queryset. The exact-match string dimensions stay bounded ``CharField``s, not
    closed ``ChoiceField``s: audit vocabulary is append-only but historical rows
    can carry retired ``action``/``entity_type``/``actor_type`` strings, and a
    closed choice would make that older evidence unfilterable. Integer ids allow
    the historical sentinel ``0``. ``event type`` maps to ``action`` and the
    ``entity``/``actor`` dimensions to their type+id pairs; no overlapping
    ``event_type`` or activity-category taxonomy is introduced.
    """

    entity_type = serializers.CharField(required=False, allow_blank=True, max_length=20)
    entity_id = serializers.IntegerField(required=False, min_value=0)
    action = serializers.CharField(required=False, allow_blank=True, max_length=20)
    actor_type = serializers.CharField(required=False, allow_blank=True, max_length=10)
    actor_id = serializers.IntegerField(required=False, min_value=0)
    request_id = serializers.CharField(required=False, allow_blank=True, max_length=64)
    from_date = serializers.DateTimeField(required=False)
    to_date = serializers.DateTimeField(required=False)

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        """Reject an inverted time window before it reaches the queryset."""
        from_date = attrs.get("from_date")
        to_date = attrs.get("to_date")
        if isinstance(from_date, datetime) and isinstance(to_date, datetime) and from_date > to_date:
            raise serializers.ValidationError({"from_date": "from_date must not be later than to_date."})
        return attrs


class IsStaffAuditSession(permissions.BasePermission):
    """Admit staff browser sessions and audit every denial.

    The staff/superuser session-only authority decision is the canonical
    :class:`IsStaffSession` rule (no second staff-authority rule); this class only
    adds denied-read auditing on top so a rejected audit-read is itself recorded.
    """

    message = IsStaffSession.message

    def has_permission(self, request: Request, view: APIView) -> bool:
        allowed = IsStaffSession().has_permission(request, view)
        if not allowed:
            try:
                audit_log_from_request(
                    request,
                    entity_type=AuditEntityType.CONFIG,
                    entity_id=0,
                    action=AuditAction.ACCESS_DENIED,
                    context=f"Permission denied: {type(view).__name__} - audit read requires staff session",
                )
            except Exception:
                logger.exception("Failed to record denied audit-read request")
        return allowed


# The published contract advertises only the credential the endpoint accepts.
# The runtime authenticates bearer-first purely to fail closed (see
# ``_AUDIT_AUTHENTICATION``), but ``IsStaffAuditSession`` rejects every token
# principal, so the OpenAPI security requirement is session-cookie only rather
# than listing ApiTokenAuth as an accepted alternative. ``extend_schema(auth=...)``
# is passed through verbatim as the operation's ``security`` list (drf-spectacular
# openapi.py), so it must be security-requirement objects; the stub types the
# parameter narrowly as ``Sequence[str]``, hence the argument-type ignores below.
_AUDIT_SCHEMA_AUTH: list[dict[str, list[str]]] = [{"cookieAuth": []}]


@extend_schema_view(
    list=extend_schema(parameters=[AuditLogQuerySerializer], auth=_AUDIT_SCHEMA_AUTH),  # type: ignore[arg-type]
    retrieve=extend_schema(auth=_AUDIT_SCHEMA_AUTH),  # type: ignore[arg-type]
)
class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    """List and retrieve audit events with the existing filter surface."""

    authentication_classes = _AUDIT_AUTHENTICATION
    permission_classes = [IsStaffAuditSession]
    serializer_class = AuditLogSerializer
    # Opt out of the global SearchFilter/OrderingFilter: this endpoint defines no
    # truthful search or ordering fields, so the generated contract must not
    # advertise inert ``search``/``ordering`` parameters. The structured
    # actor/entity/time/action filters below are the authoritative search surface.
    filter_backends: list[object] = []

    def get_queryset(self) -> QuerySet[AuditLog]:
        query = AuditLogQuerySerializer(data=self.request.query_params)
        query.is_valid(raise_exception=True)
        data = query.validated_data

        queryset = AuditLog.objects.all()
        for parameter, field in _AUDIT_FILTERS.items():
            if parameter not in data:
                continue
            value = data[parameter]
            # A blank exact-match string means "no filter", matching the prior
            # behavior; validated integer ids (including the sentinel 0) apply.
            if isinstance(value, str) and value == "":
                continue
            queryset = queryset.filter(**{field: value})
        # Deterministic ordering: newest first, tie-broken by id so pages are
        # stable when rows share a timestamp.
        return queryset.order_by("-timestamp", "-id")
