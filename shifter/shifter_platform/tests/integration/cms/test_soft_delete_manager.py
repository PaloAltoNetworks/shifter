"""DB-backed integration tests for the canonical soft-delete manager.

These tests exercise :class:`shared.db.SoftDeleteManager` and
:class:`shared.db.SoftDeleteQuerySet` against a real database via a
representative consumer model (``cms.models.Request``). They verify
the *behavior* of the bug-class fix — that ``Model.objects`` cannot
return soft-deleted rows, that ``Model.all_objects`` can, and that
the chainable ``.active()`` / ``.deleted()`` helpers compose
correctly. Mock-based unit tests pin the call shape; these tests pin
the actual queries.

``Request`` was chosen as the representative because it's a concrete
model with the canonical (``objects = SoftDeleteManager()``,
``all_objects = models.Manager()``) declaration and a minimal schema
with no save-time validation chains, so the tests express soft-delete
semantics rather than incidental request data.
"""

from __future__ import annotations

import uuid

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from cms.models import Request
from shared.enums import RequestType

User = get_user_model()


@pytest.fixture
def request_user(db):
    return User.objects.create_user(
        username="soft-delete-test-user",
        email="sdt@example.test",
        password="x",
    )


def _make_request(request_user, label, deleted_at=None):
    obj = Request(
        request_id=uuid.uuid4(),
        request_type=RequestType.RANGE.value,
        user=request_user,
    )
    obj.save()
    if deleted_at:
        obj.deleted_at = deleted_at
        obj.save(update_fields=["deleted_at"])
    return obj


@pytest.mark.django_db
class TestSoftDeleteManagerSemantics:
    """``Model.objects`` excludes soft-deleted rows; ``Model.all_objects`` includes them."""

    def test_objects_excludes_soft_deleted_rows(self, request_user):
        active = _make_request(request_user, "active-only")
        _make_request(request_user, "deleted-1", deleted_at=timezone.now())

        result = list(Request.objects.all())

        assert active in result
        assert all(s.deleted_at is None for s in result)
        assert len(result) == 1

    def test_all_objects_includes_soft_deleted_rows(self, request_user):
        _make_request(request_user, "all-active")
        _make_request(request_user, "all-deleted", deleted_at=timezone.now())

        result = list(Request.all_objects.all())

        assert len(result) == 2
        assert any(s.deleted_at is not None for s in result)

    def test_objects_filter_cannot_return_deleted(self, request_user):
        """Even an explicit filter on ``objects`` cannot leak deleted rows.

        This is the bug-class guarantee: code that writes the plain
        ``Model.objects.filter(...)`` it would write for any other
        model cannot return soft-deleted rows.
        """
        active = _make_request(request_user, "filter-active", deleted_at=None)
        deleted = _make_request(request_user, "filter-deleted", deleted_at=timezone.now())

        result = list(Request.objects.filter(pk__in=[active.pk, deleted.pk]))

        assert active in result
        assert deleted not in result

    def test_objects_get_raises_for_deleted(self, request_user):
        deleted = _make_request(request_user, "get-deleted", deleted_at=timezone.now())

        with pytest.raises(Request.DoesNotExist):
            Request.objects.get(pk=deleted.pk)

    def test_all_objects_get_finds_deleted(self, request_user):
        deleted = _make_request(request_user, "all-get-deleted", deleted_at=timezone.now())

        found = Request.all_objects.get(pk=deleted.pk)

        assert found.pk == deleted.pk
        assert found.deleted_at is not None


@pytest.mark.django_db
class TestSoftDeleteQuerySetHelpers:
    """``.active()`` / ``.deleted()`` chained behavior."""

    def test_active_on_objects_is_idempotent(self, request_user):
        """``Model.objects.active()`` returns the same set as ``Model.objects``."""
        active = _make_request(request_user, "idempotent-active")
        deleted = _make_request(request_user, "idempotent-deleted", deleted_at=timezone.now())

        default = set(Request.objects.values_list("pk", flat=True))
        active_set = set(Request.objects.active().values_list("pk", flat=True))

        assert default == active_set
        assert active.pk in active_set
        assert deleted.pk not in active_set

    def test_deleted_on_all_objects_returns_only_deleted(self, request_user):
        active = _make_request(request_user, "deleted-helper-active")
        deleted = _make_request(request_user, "deleted-helper-deleted", deleted_at=timezone.now())

        result = set(Request.all_objects.deleted().values_list("pk", flat=True))

        assert deleted.pk in result
        assert active.pk not in result

    def test_deleted_on_default_objects_returns_empty(self, request_user):
        """Calling ``.deleted()`` on the active-only manager yields the empty set.

        That's the contradiction (``deleted_at IS NULL`` AND
        ``deleted_at IS NOT NULL``) and it's intentional — the default
        manager guarantees no deleted rows are ever returned, period.
        Code that wants deleted rows must reach for ``all_objects``.
        """
        _make_request(request_user, "double-filter-deleted", deleted_at=timezone.now())

        assert Request.objects.deleted().count() == 0


@pytest.mark.django_db
class TestSoftDeleteCascadesAndAuditPaths:
    """Reverse relations and audit reads use the unfiltered manager.

    The base_manager_name = "all_objects" declaration is critical: without
    it, Django's reverse-FK descriptors and migration introspection would
    only see active rows, which can break cascade behaviour, integrity
    queries, and admin views that need to inspect deleted descendants.
    """

    def test_base_manager_is_unfiltered(self):
        """Request._meta.base_manager must point at all_objects."""
        # Class-level assertion; doesn't need DB but kept here for cohesion.
        assert Request._meta.base_manager_name == "all_objects"
        assert Request._meta.base_manager.model is Request
