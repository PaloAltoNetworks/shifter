"""Behavior tests for CMS destroy_range / cancel_range services.

Drives the real services against a real provisioned range (cms RangeInstance +
matching engine Range/Request; engine ECS unconfigured so teardown is a no-op),
instead of patching ``RangeInstance.objects`` / ``get_range`` / the engine calls /
``audit_log``.
"""

from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth import get_user_model

from cms import services
from cms.exceptions import CMSError
from cms.models import RangeInstance
from engine.models import Range as EngineRange
from risk_register.models import AuditLog
from shared.cloud.exceptions import CloudTaskError
from shared.enums import ResourceStatus
from tests.conftest import INVALID_RANGE_IDS, INVALID_USERS

pytestmark = pytest.mark.django_db

User = get_user_model()


@pytest.fixture
def user(db):
    return User.objects.create_user(username="cms-destroy@example.com", email="cms-destroy@example.com")


def _reload(range_id):
    # Destroy/cancel soft-delete the row, so read it through the unfiltered manager.
    return RangeInstance.all_objects.get(range_id=range_id)


def _request_id_of(range_instance):
    return str(range_instance.request.request_id)


def _configure_failing_ecs(settings):
    settings.CLOUD_PROVIDER = "aws"
    settings.LOCAL_PROVISIONER = None
    settings.ENGINE_TASK_CLUSTER = "test-cluster"
    settings.ENGINE_TASK_DEFINITION = "test-taskdef"
    settings.ENGINE_TASK_NETWORK_SECURITY_GROUP_ID = "sg-test"
    settings.ENGINE_TASK_NETWORK_SUBNET_IDS = "subnet-aaa,subnet-bbb"
    client = MagicMock()
    client.run_task.return_value = {"tasks": [], "failures": [{"reason": "RESOURCE:CPU"}]}
    return client


class TestDestroyRange:
    def test_sets_status_to_destroying_and_soft_deletes(self, user, provision_range):
        # range_id deliberately differs from pk; destroy resolves by pk (#1139).
        ri = provision_range(user, range_id=42)
        assert services.destroy_range(user, ri.pk) is None
        reloaded = _reload(42)
        assert reloaded.status == ResourceStatus.DESTROYING.value
        assert reloaded.deleted_at is not None

    def test_records_deprovision_audit(self, user, provision_range):
        ri = provision_range(user, range_id=42)
        services.destroy_range(user, ri.pk)
        assert AuditLog.objects.filter(
            entity_type=AuditLog.EntityType.RANGE, entity_id=ri.pk, action=AuditLog.Action.DEPROVISION
        ).exists()

    def test_reverts_when_engine_dispatch_fails(self, user, provision_range, settings):
        ri = provision_range(user, range_id=42, engine_status=EngineRange.Status.READY)
        ri.status = ResourceStatus.READY.value
        ri.save(update_fields=["status"])

        with patch("boto3.client", return_value=_configure_failing_ecs(settings)), pytest.raises(CloudTaskError):
            services.destroy_range(user, ri.pk)

        reloaded = RangeInstance.objects.get(pk=ri.pk)
        assert reloaded.status == ResourceStatus.READY.value
        assert reloaded.deleted_at is None

    def test_raises_cms_error_when_range_not_found(self, user):
        with pytest.raises(CMSError, match="Range 999999 not found"):
            services.destroy_range(user, 999999)

    def test_raises_cms_error_when_not_owner(self, user, django_user_model, provision_range):
        other = django_user_model.objects.create_user(username="cms-d-other@e.com", email="cms-d-other@e.com")
        ri = provision_range(other, range_id=77)
        with pytest.raises(CMSError, match="not found"):
            services.destroy_range(user, ri.pk)

    def test_requires_user_argument(self):
        with pytest.raises(TypeError):
            services.destroy_range(range_id=42)

    @pytest.mark.parametrize("invalid_user", INVALID_USERS)
    def test_raises_on_invalid_user(self, invalid_user):
        with pytest.raises((TypeError, ValueError, AttributeError)):
            services.destroy_range(invalid_user, 42)

    def test_requires_range_id_argument(self, user):
        with pytest.raises(TypeError):
            services.destroy_range(user)

    @pytest.mark.parametrize("invalid_range_id", INVALID_RANGE_IDS)
    def test_raises_on_invalid_range_id(self, user, invalid_range_id):
        with pytest.raises((TypeError, ValueError)):
            services.destroy_range(user, invalid_range_id)


class TestCancelRange:
    def test_sets_status_to_destroying(self, user, provision_range):
        provision_range(user, range_id=42)
        assert services.cancel_range(user, 42) is None
        reloaded = _reload(42)
        assert reloaded.status == ResourceStatus.DESTROYING.value
        assert reloaded.deleted_at is None

    def test_records_cancel_audit(self, user, provision_range):
        provision_range(user, range_id=42)
        services.cancel_range(user, 42)
        assert AuditLog.objects.filter(
            entity_type=AuditLog.EntityType.RANGE, entity_id=42, action=AuditLog.Action.CANCEL
        ).exists()

    def test_cancel_retry_is_idempotent_without_duplicate_audit(self, user, provision_range):
        provision_range(user, range_id=42)
        services.cancel_range(user, 42)
        services.cancel_range(user, 42)
        assert _reload(42).status == ResourceStatus.DESTROYING.value
        assert (
            AuditLog.objects.filter(
                entity_type=AuditLog.EntityType.RANGE,
                entity_id=42,
                action=AuditLog.Action.CANCEL,
            ).count()
            == 1
        )

    def test_reverts_and_skips_audit_when_engine_rejects(self, user, provision_range):
        provision_range(user, range_id=42, engine_status=EngineRange.Status.READY)

        with pytest.raises(CMSError, match="cannot be cancelled"):
            services.cancel_range(user, 42)

        assert _reload(42).status == ResourceStatus.PROVISIONING.value
        assert not AuditLog.objects.filter(
            entity_type=AuditLog.EntityType.RANGE,
            entity_id=42,
            action=AuditLog.Action.CANCEL,
        ).exists()

    def test_raises_cms_error_when_range_not_found(self, user):
        with pytest.raises(CMSError):
            services.cancel_range(user, 999)

    def test_raises_cms_error_when_not_owner(self, user, django_user_model, provision_range):
        other = django_user_model.objects.create_user(username="cms-c-other@e.com", email="cms-c-other@e.com")
        provision_range(other, range_id=88)
        with pytest.raises(CMSError):
            services.cancel_range(user, 88)

    def test_requires_user_argument(self):
        with pytest.raises(TypeError):
            services.cancel_range(range_id=42)

    @pytest.mark.parametrize("invalid_user", INVALID_USERS)
    def test_raises_on_invalid_user(self, invalid_user):
        with pytest.raises((TypeError, ValueError, AttributeError)):
            services.cancel_range(invalid_user, 42)

    def test_requires_range_id_argument(self, user):
        with pytest.raises(TypeError):
            services.cancel_range(user)

    @pytest.mark.parametrize("invalid_range_id", INVALID_RANGE_IDS)
    def test_raises_on_invalid_range_id(self, user, invalid_range_id):
        with pytest.raises((TypeError, ValueError)):
            services.cancel_range(user, invalid_range_id)


class TestCancelRangeByRequestId:
    def test_sets_status_to_destroying(self, user, provision_range):
        ri = provision_range(user, range_id=42)
        services.cancel_range_by_request_id(user, _request_id_of(ri))
        reloaded = _reload(42)
        assert reloaded.status == ResourceStatus.DESTROYING.value
        assert reloaded.deleted_at is None

    def test_retry_is_idempotent_without_duplicate_audit(self, user, provision_range):
        ri = provision_range(user, range_id=42)
        services.cancel_range_by_request_id(user, _request_id_of(ri))
        services.cancel_range_by_request_id(user, _request_id_of(ri))
        assert _reload(42).status == ResourceStatus.DESTROYING.value
        assert (
            AuditLog.objects.filter(
                entity_type=AuditLog.EntityType.RANGE,
                entity_id=ri.id,
                action=AuditLog.Action.CANCEL,
            ).count()
            == 1
        )

    def test_reverts_and_skips_audit_when_engine_rejects(self, user, provision_range):
        ri = provision_range(user, range_id=42, engine_status=EngineRange.Status.READY)

        with pytest.raises(CMSError, match="cannot be cancelled"):
            services.cancel_range_by_request_id(user, _request_id_of(ri))

        assert _reload(42).status == ResourceStatus.PROVISIONING.value
        assert not AuditLog.objects.filter(
            entity_type=AuditLog.EntityType.RANGE,
            entity_id=ri.id,
            action=AuditLog.Action.CANCEL,
        ).exists()

    def test_raises_cms_error_when_range_not_found(self, user):
        from uuid import uuid4

        with pytest.raises(CMSError):
            services.cancel_range_by_request_id(user, str(uuid4()))


class TestDestroyRangeByRequestId:
    def test_reverts_when_engine_dispatch_fails(self, user, provision_range, settings):
        ri = provision_range(user, range_id=42, engine_status=EngineRange.Status.READY)
        ri.status = ResourceStatus.READY.value
        ri.save(update_fields=["status"])

        with patch("boto3.client", return_value=_configure_failing_ecs(settings)), pytest.raises(CloudTaskError):
            services.destroy_range_by_request_id(user, _request_id_of(ri))

        reloaded = RangeInstance.objects.get(pk=ri.pk)
        assert reloaded.status == ResourceStatus.READY.value
        assert reloaded.deleted_at is None
