"""Scoped model-access sharing/catalog management API (M09, #2126 / PLAT-202).

Thin DRF exposure of the existing Engine sharing validate/preview/publish/drain
boundary and the cross-domain selector composition root. Catalog and deployment
identity are resolved server-side from the mounted, digest-verified runtime
envelope — a web request never supplies or rewrites the catalog. Every mutation
enters the owning service, which re-derives the publisher, re-checks authority and
compares the definition revision (management-preflight-2126.md).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from drf_spectacular.utils import extend_schema
from rest_framework import permissions, serializers
from rest_framework.response import Response

from cms.services import EngineSharingError
from shared.api.errors import api_error_response
from shared.api.model_access import ModelAccessAPIView
from shared.api.permissions import IsAuthenticatedSessionOrApiToken
from shared.api.principals import active_actor_user
from shared.api_tokens.permissions import require_scope
from shared.api_tokens.scopes import (
    MODEL_ACCESS_OPERATOR_READ,
    MODEL_ACCESS_SHARING_READ,
    MODEL_ACCESS_SHARING_WRITE,
)

if TYPE_CHECKING:
    from uuid import UUID

    from rest_framework.request import Request
    from rest_framework.views import APIView

    from shared.model_access import EffectivePolicy, ModelAccessCatalog, SharingBinding, SharingPool


class IsPlatformOperatorActor(permissions.BasePermission):
    """Require the resolved active actor to hold global deployment-operator authority.

    Resolves the session user or token owner and applies the single canonical
    operator predicate. An operator scope, staff status, or token possession does
    not by itself satisfy this — the predicate is superuser-and-active only.
    """

    message = "This action requires platform-operator authority."

    def has_permission(self, request: Request, view: APIView) -> bool:
        from management.services import is_platform_operator

        return is_platform_operator(active_actor_user(request))


# Session/CSRF + scoped-token parity per surface. ``require_scope`` also publishes
# the exact scope into OpenAPI (shared.api.schema.PlatformAutoSchema).
_SHARING_READ: list[type[permissions.BasePermission]] = [
    IsAuthenticatedSessionOrApiToken,
    require_scope(MODEL_ACCESS_SHARING_READ, MODEL_ACCESS_SHARING_READ),
]
_SHARING_WRITE: list[type[permissions.BasePermission]] = [
    IsAuthenticatedSessionOrApiToken,
    require_scope(MODEL_ACCESS_SHARING_WRITE, MODEL_ACCESS_SHARING_WRITE),
]
_OPERATOR_READ: list[type[permissions.BasePermission]] = [
    IsAuthenticatedSessionOrApiToken,
    IsPlatformOperatorActor,
    require_scope(MODEL_ACCESS_OPERATOR_READ, MODEL_ACCESS_OPERATOR_READ),
]

# Bounded, safe error categories. Owner-domain codes never leak provider bodies,
# ORM detail, membership lists or secret references (management-preflight-2126.md).
_UNAVAILABLE = ("model_access_unavailable", "Model access is not available on this deployment.", 503)
_DENIED = ("model_access_denied", "Model access request denied.", 403)
_STALE = ("model_access_revision_conflict", "Definition changed. Reload before saving.", 409)
_NOT_FOUND = ("model_access_binding_not_found", "Binding not found.", 404)
_INVALID = ("model_access_invalid", "Invalid model-access request.", 400)


def _current_envelope() -> tuple[ModelAccessCatalog, UUID] | None:
    """Return ``(catalog, deployment_id)`` from the mounted runtime, or ``None``.

    Neither is client-supplied. When model access is unconfigured or disabled the
    management surface reports temporarily-unavailable rather than acting.
    """
    from django.conf import settings

    if not getattr(settings, "MODEL_ACCESS_ENABLED", False):
        return None
    catalog = getattr(settings, "MODEL_ACCESS_CATALOG", None)
    if catalog is None or not getattr(catalog, "enabled", False):
        return None
    return catalog, catalog.deployment_id


def _error(request: Request, mapped: tuple[str, str, int]) -> Response:
    """Render a bounded ``(code, message, status)`` triple as the shared envelope."""
    code, message, status_code = mapped
    return api_error_response(code=code, message=message, status_code=status_code, request=request)


# Stable owner-domain codes → bounded API category. SharingError carries a
# ``sharing.*`` code; ContractError a ``*.*`` code.
_ERROR_BY_CODE: dict[str, tuple[str, str, int]] = {
    "sharing.revision_conflict": _STALE,
    "source.revision_conflict": _STALE,
    "sharing.binding_not_found": _NOT_FOUND,
    "sharing.publisher_authority_required": _DENIED,
}


def _map_service_error(exc: Exception) -> tuple[str, str, int]:
    """Map an owner-domain exception to one bounded, body-free API category."""
    from config.model_access_sharing import ModelAccessCompositionError
    from shared.model_access import ContractError

    code = getattr(exc, "code", "")
    denied = isinstance(exc, ModelAccessCompositionError) or (
        isinstance(exc, ContractError) and code.endswith("_denied")
    )
    if denied:
        return _DENIED
    return _ERROR_BY_CODE.get(code, _INVALID)


class BindingDraftSerializer(serializers.Serializer):
    """A binding + pool draft. Owner services revalidate the closed contracts."""

    binding = serializers.DictField()
    pool = serializers.DictField()


class PublishSerializer(BindingDraftSerializer):
    """Publish request: a binding+pool draft under an optimistic definition-revision fence."""

    expected_definition_revision = serializers.IntegerField(min_value=0)
    empty_snapshot_ack = serializers.BooleanField(default=False)


class DrainSerializer(serializers.Serializer):
    """Drain request: the binding id and its expected definition revision."""

    sharing_binding_id = serializers.CharField(max_length=64)
    expected_definition_revision = serializers.IntegerField(min_value=0)


class SelectorSerializer(serializers.Serializer):
    """Selector-preview request: one sharing selector to resolve."""

    selector = serializers.DictField()


class SubjectSerializer(serializers.Serializer):
    """Policy-preview request: the subject reference to compile an effective policy for."""

    subject = serializers.DictField()


class RevisionResponseSerializer(serializers.Serializer):
    """Bounded published/drained binding-revision projection."""

    sharing_binding_id = serializers.CharField()
    definition_revision = serializers.IntegerField()
    state = serializers.CharField()


class ValidResponseSerializer(serializers.Serializer):
    """Draft-validation result."""

    valid = serializers.BooleanField()


class MemberSerializer(serializers.Serializer):
    """One resolved selector member reference."""

    owner = serializers.CharField()
    reference = serializers.CharField()


class SelectorPreviewResponseSerializer(serializers.Serializer):
    """Matched selector members and their count (advisory)."""

    matched = serializers.IntegerField()
    members = MemberSerializer(many=True)


class PolicyConflictSerializer(serializers.Serializer):
    """One priority/facet conflict in the compiled effective policy."""

    code = serializers.CharField()
    facet = serializers.CharField(allow_null=True)
    logical_alias = serializers.CharField(allow_null=True)


class PolicyContributionSerializer(serializers.Serializer):
    """One binding contributing to the compiled effective policy."""

    sharing_binding_id = serializers.CharField()
    definition_digest = serializers.CharField()
    membership_revision = serializers.IntegerField()
    routing_revision = serializers.IntegerField()
    priority = serializers.IntegerField()
    matched_reason = serializers.CharField()
    facets = serializers.ListField(child=serializers.CharField())


class AliasRoutingSerializer(serializers.Serializer):
    """The routing affinity chosen for one logical alias."""

    logical_alias = serializers.CharField()
    affinity = serializers.CharField()


class AccountSummarySerializer(serializers.Serializer):
    """Per-dimension count of accounts the policy references (never balances)."""

    capacity = serializers.IntegerField()
    spend = serializers.IntegerField()
    rate = serializers.IntegerField()
    concurrency = serializers.IntegerField()


class EffectivePolicyResponseSerializer(serializers.Serializer):
    """Bounded effective-policy projection: overlaps, conflicts, routings, account counts."""

    stale = serializers.BooleanField()
    is_admissible = serializers.BooleanField()
    conflicts = PolicyConflictSerializer(many=True)
    contributions = PolicyContributionSerializer(many=True)
    alias_routings = AliasRoutingSerializer(many=True)
    account_summary = AccountSummarySerializer()


def _binding_and_pool(data: dict[str, object], deployment_id: UUID) -> tuple[SharingBinding, SharingPool]:
    """Seal a client binding draft into a full binding and validate the pool.

    Server-controlled fields are never trusted from the request: ``deployment_id``
    is injected from the mounted envelope, ``membership_revision`` and
    ``authorized_publisher_ref`` are placeholders that the publish path re-derives
    from the resolved projection and re-seals with the real server publisher, and
    the definition digest is computed by :func:`seal_sharing_binding`.
    """
    from shared.model_access import SharingPool, seal_sharing_binding

    draft = dict(cast("dict[str, object]", data["binding"]))
    draft["deployment_id"] = str(deployment_id)
    draft.setdefault("contract_version", "model-access-sharing/v1")
    draft["membership_revision"] = 1
    draft["authorized_publisher_ref"] = {"owner": "management", "reference": "draft:unresolved"}
    draft.pop("definition_digest", None)
    return seal_sharing_binding(draft), SharingPool.model_validate(data["pool"])


class ModelAccessBindingValidateView(ModelAccessAPIView):
    """Validate a binding+pool draft against the pinned catalog. Confers no authority."""

    permission_classes = _SHARING_READ

    @extend_schema(request=BindingDraftSerializer, responses=ValidResponseSerializer)
    def post(self, request: Request) -> Response:
        from cms.services import engine_validate_sharing_binding
        from shared.model_access import ContractError

        envelope = _current_envelope()
        if envelope is None:
            return _error(request, _UNAVAILABLE)
        serializer = BindingDraftSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        catalog, deployment_id = envelope
        try:
            binding, pool = _binding_and_pool(serializer.validated_data, deployment_id)
            engine_validate_sharing_binding(deployment_id=deployment_id, catalog=catalog, binding=binding, pool=pool)
        except (EngineSharingError, ContractError, ValueError) as exc:
            return _error(request, _map_service_error(exc))
        return Response({"valid": True})


class ModelAccessSelectorPreviewView(ModelAccessAPIView):
    """Preview a selector's matched members and reason codes. Advisory, not authority."""

    permission_classes = _SHARING_READ

    @extend_schema(request=SelectorSerializer, responses=SelectorPreviewResponseSerializer)
    def post(self, request: Request) -> Response:
        from config.model_access_sharing import ModelAccessCompositionError, resolve_model_access_selector

        serializer = SelectorSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            resolution = resolve_model_access_selector(self.actor(request), serializer.validated_data["selector"])
        except (ModelAccessCompositionError, EngineSharingError, ValueError) as exc:
            return _error(request, _map_service_error(exc))
        return Response(
            {
                "matched": resolution.assessment_count,
                "members": [{"owner": ref.owner, "reference": ref.reference} for ref in resolution.member_refs],
            }
        )


class ModelAccessEffectivePolicyPreviewView(ModelAccessAPIView):
    """Preview the compiled effective policy for a subject: overlaps, conflicts, routings."""

    permission_classes = _OPERATOR_READ

    @extend_schema(request=SubjectSerializer, responses=EffectivePolicyResponseSerializer)
    def post(self, request: Request) -> Response:
        from cms.services import engine_preview_effective_policy
        from shared.model_access import ContractError

        envelope = _current_envelope()
        if envelope is None:
            return _error(request, _UNAVAILABLE)
        serializer = SubjectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        catalog, deployment_id = envelope
        try:
            policy = engine_preview_effective_policy(
                deployment_id=deployment_id, catalog=catalog, subject=serializer.validated_data["subject"]
            )
        except (EngineSharingError, ContractError, ValueError) as exc:
            return _error(request, _map_service_error(exc))
        return Response(_project_policy(policy))


class ModelAccessBindingPublishView(ModelAccessAPIView):
    """Publish the next immutable binding revision under an optimistic CAS fence."""

    permission_classes = _SHARING_WRITE

    @extend_schema(request=PublishSerializer, responses=RevisionResponseSerializer)
    def post(self, request: Request) -> Response:
        from config.model_access_sharing import ModelAccessCompositionError, publish_model_access_binding
        from shared.model_access import ContractError

        envelope = _current_envelope()
        if envelope is None:
            return _error(request, _UNAVAILABLE)
        serializer = PublishSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        catalog, deployment_id = envelope
        try:
            binding, pool = _binding_and_pool(serializer.validated_data, deployment_id)
            revision = publish_model_access_binding(
                actor=self.actor(request),
                deployment_id=deployment_id,
                catalog=catalog,
                binding=binding,
                pool=pool,
                expected_definition_revision=serializer.validated_data["expected_definition_revision"],
                empty_snapshot_ack=serializer.validated_data["empty_snapshot_ack"],
            )
        except (ModelAccessCompositionError, EngineSharingError, ContractError, ValueError) as exc:
            return _error(request, _map_service_error(exc))
        return Response(revision, status=201)


class ModelAccessBindingDrainView(ModelAccessAPIView):
    """Withdraw a binding (terminal revision + membership fence) under a CAS fence."""

    permission_classes = _SHARING_WRITE

    @extend_schema(request=DrainSerializer, responses=RevisionResponseSerializer)
    def post(self, request: Request) -> Response:
        from config.model_access_sharing import ModelAccessCompositionError, drain_model_access_binding
        from shared.model_access import ContractError

        envelope = _current_envelope()
        if envelope is None:
            return _error(request, _UNAVAILABLE)
        serializer = DrainSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        _catalog, deployment_id = envelope
        try:
            revision = drain_model_access_binding(
                actor=self.actor(request),
                deployment_id=deployment_id,
                sharing_binding_id=serializer.validated_data["sharing_binding_id"],
                expected_definition_revision=serializer.validated_data["expected_definition_revision"],
            )
        except (ModelAccessCompositionError, EngineSharingError, ContractError, ValueError) as exc:
            return _error(request, _map_service_error(exc))
        return Response(revision)


def _project_policy(policy: EffectivePolicy) -> dict[str, object]:
    """Bounded effective-policy projection.

    Exposes overlap/conflict/routing structure and account presence counts for
    planning; never raw provider coordinates, secret references or balances that
    reveal other members. Balances stay authoritative in the range-status surface.
    """
    return {
        "stale": policy.stale,
        "is_admissible": policy.admissible,
        "conflicts": [
            {"code": c.code, "facet": c.facet.value if c.facet else None, "logical_alias": c.logical_alias}
            for c in policy.conflicts
        ],
        "contributions": [
            {
                "sharing_binding_id": c.sharing_binding_id,
                "definition_digest": c.definition_digest,
                "membership_revision": c.membership_revision,
                "routing_revision": c.routing_revision,
                "priority": c.priority,
                "matched_reason": c.matched_reason,
                "facets": [f.value for f in c.facets],
            }
            for c in policy.contributions
        ],
        "alias_routings": [
            {"logical_alias": r.logical_alias, "affinity": r.affinity.value} for r in policy.alias_routings
        ],
        "account_summary": {
            "capacity": len(policy.capacity_account_refs),
            "spend": len(policy.spend_account_refs),
            "rate": len(policy.rate_account_refs),
            "concurrency": len(policy.concurrency_account_refs),
        },
    }
