"""Behavior tests for range-to-workspace scope administration (PLAT-237, #1944).

DB-backed per ADR-019: no patching of first-party ``cms.*`` / ``engine.*`` /
``workspaces.*`` seams. Every workspace, membership, range projection, and engine
range is a real row, so authorization, the expected-source compare-and-set, and
the strict audit are all driven for real.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from cms import services
from cms.exceptions import RangeScopeAdminError
from cms.models import RangeInstance
from cms.models import Request as CmsRequest
from engine.models import Range as EngineRange
from engine.models import Request as EngineRequest
from shared.audit import AuditEntityType
from shared.enums import RangeSource, RequestType, ResourceStatus
from shared.models import AuditLog
from workspaces.models import Organization, Workspace, WorkspaceMembership
from workspaces.roles import WorkspaceRole

pytestmark = pytest.mark.django_db

User = get_user_model()


def _audit(actor) -> services.RangeScopeAuditContext:
    return services.RangeScopeAuditContext(actor_type="user", actor_id=actor.id, request_id="req-test")


@pytest.fixture
def organization(db):
    return Organization.objects.create(name="Scope org")


@pytest.fixture
def admin_user(db):
    return User.objects.create_user(username="scope-admin@example.com", email="scope-admin@example.com")


@pytest.fixture
def range_owner(db):
    return User.objects.create_user(username="scope-owner@example.com", email="scope-owner@example.com")


@pytest.fixture
def aggregate_guard():
    """Expose the shared aggregate-guard seam, restoring the registry afterwards.

    Lets a test register a stub domain guard without leaking it into the
    process-global registry that other tests share.
    """
    import shared.range_workspace_aggregate as agg

    saved = list(agg._guards)
    try:
        yield agg
    finally:
        agg._guards[:] = saved


def _make_workspace(organization, name: str, *, archived: bool = False) -> Workspace:
    workspace = Workspace.objects.create(organization=organization, name=name)
    if archived:
        workspace.archived_at = timezone.now()
        workspace.save(update_fields=["archived_at"])
    return workspace


def _add_member(workspace: Workspace, user, role: WorkspaceRole) -> None:
    WorkspaceMembership.objects.create(workspace=workspace, user=user, role=role.value)


def _rebind(actor, request_id, target_uuid):
    """Single-invocation rebind wrapper.

    Keeps each ``pytest.raises`` block to exactly one possibly-throwing call
    (Sonar S5778); callers hoist the request id and target uuid out of the block.
    """
    return services.rebind_range_workspace(
        actor, request_id=request_id, target_workspace_uuid=target_uuid, audit=_audit(actor)
    )


def _make_range(
    *,
    owner,
    workspace: Workspace,
    range_source: str = RangeSource.MISSION_CONTROL.value,
    with_engine_range: bool = True,
    engine_workspace_id: int | None = None,
) -> RangeInstance:
    """A real CMS Request + RangeInstance (+ engine Request/Range) scoped to ``workspace``."""
    request_id = uuid4()
    cms_request = CmsRequest.objects.create(
        workspace_id=workspace.id,
        request_id=request_id,
        request_type=RequestType.RANGE.value,
        user=owner,
    )
    if with_engine_range:
        engine_request = EngineRequest.objects.create(
            request_id=request_id, request_type=RequestType.RANGE.value, user=owner
        )
        EngineRange.objects.create(
            workspace_id=workspace.id if engine_workspace_id is None else engine_workspace_id,
            uuid=uuid4(),
            user=owner,
            request=engine_request,
            cms_user_id=owner.id,
            status=EngineRange.Status.READY,
            subnet_index=EngineRange.allocate_subnet_index(),
        )
    return RangeInstance.objects.create(
        workspace_id=workspace.id,
        request=cms_request,
        scenario_id="basic",
        user_id=owner.id,
        range_source=range_source,
        status=ResourceStatus.READY.value,
    )


class TestListRangeScopeBindings:
    def test_owner_lists_ranges_in_workspace(self, organization, admin_user, range_owner):
        source = _make_workspace(organization, "Source")
        _add_member(source, admin_user, WorkspaceRole.OWNER)
        _add_member(source, range_owner, WorkspaceRole.MEMBER)
        _make_range(owner=range_owner, workspace=source)
        # A range in another workspace must not leak into this listing. A distinct
        # owner keeps it clear of the one-active-range-per-(user, source) constraint.
        other = _make_workspace(organization, "Other")
        other_owner = User.objects.create_user(username="scope-other@example.com", email="scope-other@example.com")
        _add_member(other, other_owner, WorkspaceRole.MEMBER)
        _make_range(owner=other_owner, workspace=other)

        bindings = list(services.list_range_scope_bindings(admin_user, workspace_uuid=source.uuid))

        assert len(bindings) == 1
        assert bindings[0].workspace_id == source.id

    def test_member_cannot_list(self, organization, admin_user):
        source = _make_workspace(organization, "Source")
        _add_member(source, admin_user, WorkspaceRole.MEMBER)

        with pytest.raises(RangeScopeAdminError) as exc:
            list(services.list_range_scope_bindings(admin_user, workspace_uuid=source.uuid))
        assert exc.value.kind is RangeScopeAdminError.Kind.NOT_FOUND

    def test_unknown_workspace_is_opaque_not_found(self, admin_user):
        with pytest.raises(RangeScopeAdminError) as exc:
            list(services.list_range_scope_bindings(admin_user, workspace_uuid=uuid4()))
        assert exc.value.kind is RangeScopeAdminError.Kind.NOT_FOUND


class TestRebindRangeWorkspaceHappyPath:
    def _setup(self, organization, admin_user, range_owner, *, source_archived=False):
        source = _make_workspace(organization, "Source", archived=source_archived)
        target = _make_workspace(organization, "Target")
        _add_member(source, admin_user, WorkspaceRole.ADMIN)
        _add_member(target, admin_user, WorkspaceRole.ADMIN)
        _add_member(source, range_owner, WorkspaceRole.MEMBER)
        _add_member(target, range_owner, WorkspaceRole.MEMBER)
        instance = _make_range(owner=range_owner, workspace=source)
        return source, target, instance

    def test_moves_all_three_projections(self, organization, admin_user, range_owner):
        _source, target, instance = self._setup(organization, admin_user, range_owner)
        request_id = instance.request.request_id

        result = services.rebind_range_workspace(
            admin_user, request_id=request_id, target_workspace_uuid=target.uuid, audit=_audit(admin_user)
        )

        assert result.changed is True
        assert RangeInstance.objects.get(pk=instance.pk).workspace_id == target.id
        assert CmsRequest.objects.get(request_id=request_id).workspace_id == target.id
        assert EngineRange.objects.get(request__request_id=request_id).workspace_id == target.id

    def test_only_workspace_id_changes(self, organization, admin_user, range_owner):
        _source, target, instance = self._setup(organization, admin_user, range_owner)
        request_id = instance.request.request_id

        services.rebind_range_workspace(
            admin_user, request_id=request_id, target_workspace_uuid=target.uuid, audit=_audit(admin_user)
        )

        moved = RangeInstance.objects.get(pk=instance.pk)
        assert moved.user_id == range_owner.id
        assert moved.range_source == RangeSource.MISSION_CONTROL.value
        assert moved.status == ResourceStatus.READY.value
        engine_range = EngineRange.objects.get(request__request_id=request_id)
        assert engine_range.user_id == range_owner.id

    def test_writes_strict_audit(self, organization, admin_user, range_owner):
        source, target, instance = self._setup(organization, admin_user, range_owner)

        services.rebind_range_workspace(
            admin_user,
            request_id=instance.request.request_id,
            target_workspace_uuid=target.uuid,
            audit=_audit(admin_user),
        )

        entry = AuditLog.objects.filter(entity_type=AuditEntityType.RANGE.value, entity_id=instance.pk).latest(
            "timestamp"
        )
        assert entry.previous_state == {"workspace_id": source.id}
        assert entry.new_state == {"workspace_id": target.id}

    def test_archived_source_can_be_evacuated(self, organization, admin_user, range_owner):
        _source, target, instance = self._setup(organization, admin_user, range_owner, source_archived=True)

        result = services.rebind_range_workspace(
            admin_user,
            request_id=instance.request.request_id,
            target_workspace_uuid=target.uuid,
            audit=_audit(admin_user),
        )

        assert result.changed is True
        assert RangeInstance.objects.get(pk=instance.pk).workspace_id == target.id

    def test_idempotent_no_op_to_same_workspace(self, organization, admin_user, range_owner):
        source, _target, instance = self._setup(organization, admin_user, range_owner)

        result = services.rebind_range_workspace(
            admin_user,
            request_id=instance.request.request_id,
            target_workspace_uuid=source.uuid,
            audit=_audit(admin_user),
        )

        assert result.changed is False
        assert RangeInstance.objects.get(pk=instance.pk).workspace_id == source.id
        assert not AuditLog.objects.filter(entity_type=AuditEntityType.RANGE.value, entity_id=instance.pk).exists()


class TestRebindRangeWorkspaceAuthorization:
    def test_actor_without_source_authority_is_not_found(self, organization, admin_user, range_owner):
        source = _make_workspace(organization, "Source")
        target = _make_workspace(organization, "Target")
        _add_member(target, admin_user, WorkspaceRole.ADMIN)  # target only
        _add_member(source, range_owner, WorkspaceRole.MEMBER)
        _add_member(target, range_owner, WorkspaceRole.MEMBER)
        instance = _make_range(owner=range_owner, workspace=source)

        with pytest.raises(RangeScopeAdminError) as exc:
            _rebind(admin_user, instance.request.request_id, target.uuid)
        assert exc.value.kind is RangeScopeAdminError.Kind.NOT_FOUND

    def test_actor_without_target_authority_is_denied(self, organization, admin_user, range_owner):
        source = _make_workspace(organization, "Source")
        target = _make_workspace(organization, "Target")
        _add_member(source, admin_user, WorkspaceRole.ADMIN)  # source only
        _add_member(source, range_owner, WorkspaceRole.MEMBER)
        _add_member(target, range_owner, WorkspaceRole.MEMBER)
        instance = _make_range(owner=range_owner, workspace=source)

        with pytest.raises(RangeScopeAdminError) as exc:
            _rebind(admin_user, instance.request.request_id, target.uuid)
        assert exc.value.kind is RangeScopeAdminError.Kind.TARGET_DENIED

    def test_member_role_cannot_rebind(self, organization, admin_user, range_owner):
        source = _make_workspace(organization, "Source")
        target = _make_workspace(organization, "Target")
        _add_member(source, admin_user, WorkspaceRole.MEMBER)
        _add_member(target, admin_user, WorkspaceRole.MEMBER)
        _add_member(source, range_owner, WorkspaceRole.MEMBER)
        _add_member(target, range_owner, WorkspaceRole.MEMBER)
        instance = _make_range(owner=range_owner, workspace=source)

        with pytest.raises(RangeScopeAdminError) as exc:
            _rebind(admin_user, instance.request.request_id, target.uuid)
        assert exc.value.kind is RangeScopeAdminError.Kind.NOT_FOUND

    def test_owner_not_member_of_target_is_denied(self, organization, admin_user, range_owner):
        source = _make_workspace(organization, "Source")
        target = _make_workspace(organization, "Target")
        _add_member(source, admin_user, WorkspaceRole.ADMIN)
        _add_member(target, admin_user, WorkspaceRole.ADMIN)
        _add_member(source, range_owner, WorkspaceRole.MEMBER)
        # range_owner is deliberately NOT a member of target
        instance = _make_range(owner=range_owner, workspace=source)

        with pytest.raises(RangeScopeAdminError) as exc:
            _rebind(admin_user, instance.request.request_id, target.uuid)
        assert exc.value.kind is RangeScopeAdminError.Kind.TARGET_DENIED

    def test_archived_target_is_denied(self, organization, admin_user, range_owner):
        source = _make_workspace(organization, "Source")
        target = _make_workspace(organization, "Target", archived=True)
        _add_member(source, admin_user, WorkspaceRole.ADMIN)
        _add_member(target, admin_user, WorkspaceRole.ADMIN)
        _add_member(source, range_owner, WorkspaceRole.MEMBER)
        _add_member(target, range_owner, WorkspaceRole.MEMBER)
        instance = _make_range(owner=range_owner, workspace=source)

        with pytest.raises(RangeScopeAdminError) as exc:
            _rebind(admin_user, instance.request.request_id, target.uuid)
        assert exc.value.kind is RangeScopeAdminError.Kind.TARGET_DENIED


class TestRebindRangeWorkspaceFailClosed:
    def _authorized_pair(self, organization, admin_user, range_owner):
        source = _make_workspace(organization, "Source")
        target = _make_workspace(organization, "Target")
        _add_member(source, admin_user, WorkspaceRole.ADMIN)
        _add_member(target, admin_user, WorkspaceRole.ADMIN)
        _add_member(source, range_owner, WorkspaceRole.MEMBER)
        _add_member(target, range_owner, WorkspaceRole.MEMBER)
        return source, target

    def test_domain_aggregate_bound_range_is_not_reassignable(
        self, organization, admin_user, range_owner, aggregate_guard
    ):
        # A range the aggregate seam reports as owned by a domain (an ADR-051 CTF
        # event, say) is refused -- authoritatively, not by provenance. The range
        # deliberately carries Mission Control provenance to prove the guard is
        # not a range_source check.
        source, target = self._authorized_pair(organization, admin_user, range_owner)
        instance = _make_range(owner=range_owner, workspace=source, range_source=RangeSource.MISSION_CONTROL.value)
        bound_pk = instance.pk
        aggregate_guard.register_range_aggregate_guard(lambda pairs: {rid for _req, rid in pairs if rid == bound_pk})

        with pytest.raises(RangeScopeAdminError) as exc:
            _rebind(admin_user, instance.request.request_id, target.uuid)
        assert exc.value.kind is RangeScopeAdminError.Kind.NOT_REASSIGNABLE

    def test_duplicate_engine_projection_is_conflict(self, organization, admin_user, range_owner):
        source, target = self._authorized_pair(organization, admin_user, range_owner)
        instance = _make_range(owner=range_owner, workspace=source)
        # A second Engine range correlated to the same request breaks the
        # one-to-one invariant; the CAS raises and CMS maps it to a bounded 409,
        # never an unhandled 500.
        engine_range = EngineRange.objects.get(request__request_id=instance.request.request_id)
        EngineRange.objects.create(
            workspace_id=source.id,
            uuid=uuid4(),
            user=range_owner,
            request=engine_range.request,
            cms_user_id=range_owner.id,
            status=EngineRange.Status.READY,
            subnet_index=EngineRange.allocate_subnet_index(),
        )

        with pytest.raises(RangeScopeAdminError) as exc:
            _rebind(admin_user, instance.request.request_id, target.uuid)
        assert exc.value.kind is RangeScopeAdminError.Kind.CONFLICT
        assert RangeInstance.objects.get(pk=instance.pk).workspace_id == source.id

    def test_unknown_range_is_not_found(self, organization, admin_user, range_owner):
        self._authorized_pair(organization, admin_user, range_owner)
        missing_request_id = uuid4()
        missing_target_uuid = uuid4()
        with pytest.raises(RangeScopeAdminError) as exc:
            _rebind(admin_user, missing_request_id, missing_target_uuid)
        assert exc.value.kind is RangeScopeAdminError.Kind.NOT_FOUND

    def test_projection_disagreement_is_conflict(self, organization, admin_user, range_owner):
        source, target = self._authorized_pair(organization, admin_user, range_owner)
        instance = _make_range(owner=range_owner, workspace=source)
        # Drift the CMS Request scope away from the RangeInstance scope.
        request = instance.request
        request.workspace_id = target.id
        request.save(update_fields=["workspace_id"])

        with pytest.raises(RangeScopeAdminError) as exc:
            _rebind(admin_user, instance.request.request_id, target.uuid)
        assert exc.value.kind is RangeScopeAdminError.Kind.CONFLICT

    def test_engine_drift_is_conflict(self, organization, admin_user, range_owner):
        source, target = self._authorized_pair(organization, admin_user, range_owner)
        third = _make_workspace(organization, "Third")
        # Engine range binding disagrees with the CMS projections (drift).
        instance = _make_range(owner=range_owner, workspace=source, engine_workspace_id=third.id)

        with pytest.raises(RangeScopeAdminError) as exc:
            _rebind(admin_user, instance.request.request_id, target.uuid)
        assert exc.value.kind is RangeScopeAdminError.Kind.CONFLICT
        # No partial move: CMS projections stay at source.
        assert RangeInstance.objects.get(pk=instance.pk).workspace_id == source.id
