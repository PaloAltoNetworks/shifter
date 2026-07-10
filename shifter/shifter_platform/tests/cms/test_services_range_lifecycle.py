"""Behavior tests for CMS range-lifecycle validation and by-request-id paths.

Covers input validation, the no-associated-request branch (driven with a real
RangeInstance whose request FK is null), and the destroy/cancel-by-request-id
happy paths (driven against a real provisioned range with engine ECS a no-op),
instead of patching ``RangeInstance.objects`` / the engine calls / ``audit_log``.
"""

from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model

from cms import services
from cms.exceptions import CMSError
from cms.models import RangeInstance
from risk_register.models import AuditLog

pytestmark = pytest.mark.django_db

User = get_user_model()


@pytest.fixture
def user(db):
    return User.objects.create_user(username="cms-lifecycle@example.com", email="cms-lifecycle@example.com")


def _range_no_request(user, *, range_id=42):
    """A real RangeInstance with no associated Request."""
    return RangeInstance.objects.create(
        scenario_id="basic", user_id=user.id, range_id=range_id, status="provisioning", request=None
    )


class TestDestroyRangeValidation:
    def test_raises_typeerror_for_none_range_id(self, user):
        with pytest.raises(TypeError, match="range_instance_pk cannot be None"):
            services.destroy_range(user, None)

    def test_raises_typeerror_for_wrong_type(self, user):
        with pytest.raises(TypeError, match="range_instance_pk must be an int"):
            services.destroy_range(user, "not-int")

    def test_raises_valueerror_for_negative(self, user):
        with pytest.raises(ValueError, match="non-negative"):
            services.destroy_range(user, -1)

    def test_raises_cms_error_when_no_request(self, user):
        ri = _range_no_request(user, range_id=42)
        with pytest.raises(CMSError, match="no associated request"):
            services.destroy_range(user, ri.pk)


class TestCancelRangeValidation:
    def test_raises_typeerror_for_none_range_id(self, user):
        with pytest.raises(TypeError, match="range_id cannot be None"):
            services.cancel_range(user, None)

    def test_raises_typeerror_for_wrong_type(self, user):
        with pytest.raises(TypeError, match="range_id must be an int"):
            services.cancel_range(user, "not-int")

    def test_raises_valueerror_for_negative(self, user):
        with pytest.raises(ValueError, match="non-negative"):
            services.cancel_range(user, -1)

    def test_raises_cms_error_when_range_not_found(self, user):
        with pytest.raises(CMSError, match="not found"):
            services.cancel_range(user, 999)

    def test_raises_cms_error_when_no_request(self, user):
        _range_no_request(user, range_id=42)
        with pytest.raises(CMSError, match="no associated request"):
            services.cancel_range(user, 42)


class TestDestroyRangeByRequestId:
    def test_raises_typeerror_for_none_user(self):
        with pytest.raises(TypeError):
            services.destroy_range_by_request_id(None, str(uuid4()))

    def test_raises_typeerror_for_invalid_user(self):
        with pytest.raises(TypeError, match="User instance"):
            services.destroy_range_by_request_id("not-user", str(uuid4()))

    def test_raises_cms_error_for_empty_request_id(self, user):
        with pytest.raises(CMSError, match="request_id is required"):
            services.destroy_range_by_request_id(user, "")

    def test_raises_cms_error_when_not_found(self, user):
        with pytest.raises(CMSError, match="not found"):
            services.destroy_range_by_request_id(user, str(uuid4()))

    def test_happy_path_destroys_and_audits(self, user, provision_range):
        ri = provision_range(user, range_id=42)
        services.destroy_range_by_request_id(user, str(ri.request.request_id))
        assert AuditLog.objects.filter(
            entity_type=AuditLog.EntityType.RANGE, action=AuditLog.Action.DEPROVISION
        ).exists()
        assert RangeInstance.all_objects.get(range_id=42).deleted_at is not None


class TestCancelRangeByRequestId:
    def test_raises_typeerror_for_none_user(self):
        with pytest.raises(TypeError):
            services.cancel_range_by_request_id(None, str(uuid4()))

    def test_raises_typeerror_for_invalid_user(self):
        with pytest.raises(TypeError, match="User instance"):
            services.cancel_range_by_request_id("not-user", str(uuid4()))

    def test_raises_cms_error_for_empty_request_id(self, user):
        with pytest.raises(CMSError, match="request_id is required"):
            services.cancel_range_by_request_id(user, "")

    def test_raises_cms_error_when_not_found(self, user):
        with pytest.raises(CMSError, match="not found"):
            services.cancel_range_by_request_id(user, str(uuid4()))

    def test_happy_path_cancels_and_audits(self, user, provision_range):
        ri = provision_range(user, range_id=42)
        services.cancel_range_by_request_id(user, str(ri.request.request_id))
        assert AuditLog.objects.filter(entity_type=AuditLog.EntityType.RANGE, action=AuditLog.Action.CANCEL).exists()


class TestPauseRangeValidation:
    def test_raises_typeerror_for_none_range_id(self, user):
        with pytest.raises(TypeError, match="range_instance_pk cannot be None"):
            services.pause_range(user, None)

    def test_raises_typeerror_for_wrong_type(self, user):
        with pytest.raises(TypeError, match="range_instance_pk must be an int"):
            services.pause_range(user, "x")

    def test_raises_valueerror_for_negative(self, user):
        with pytest.raises(ValueError, match="non-negative"):
            services.pause_range(user, -2)

    def test_raises_cms_error_when_no_request(self, user):
        ri = _range_no_request(user, range_id=42)
        with pytest.raises(CMSError, match="no associated request"):
            services.pause_range(user, ri.pk)


class TestResumeRangeValidation:
    def test_raises_typeerror_for_none_range_id(self, user):
        with pytest.raises(TypeError, match="range_instance_pk cannot be None"):
            services.resume_range(user, None)

    def test_raises_typeerror_for_wrong_type(self, user):
        with pytest.raises(TypeError, match="range_instance_pk must be an int"):
            services.resume_range(user, "x")

    def test_raises_valueerror_for_negative(self, user):
        with pytest.raises(ValueError, match="non-negative"):
            services.resume_range(user, -2)

    def test_raises_cms_error_when_no_request(self, user):
        ri = _range_no_request(user, range_id=42)
        with pytest.raises(CMSError, match="no associated request"):
            services.resume_range(user, ri.pk)


class TestPauseResumeByRequestIdValidation:
    def test_pause_raises_typeerror_for_none_user(self):
        with pytest.raises(TypeError):
            services.pause_range_by_request_id(None, str(uuid4()))

    def test_pause_raises_typeerror_for_invalid_user(self):
        with pytest.raises(TypeError, match="User instance"):
            services.pause_range_by_request_id("x", str(uuid4()))

    def test_pause_raises_cms_error_for_empty_request_id(self, user):
        with pytest.raises(CMSError, match="request_id is required"):
            services.pause_range_by_request_id(user, "")

    def test_resume_raises_typeerror_for_none_user(self):
        with pytest.raises(TypeError):
            services.resume_range_by_request_id(None, str(uuid4()))

    def test_resume_raises_typeerror_for_invalid_user(self):
        with pytest.raises(TypeError, match="User instance"):
            services.resume_range_by_request_id("x", str(uuid4()))

    def test_resume_raises_cms_error_for_empty_request_id(self, user):
        with pytest.raises(CMSError, match="request_id is required"):
            services.resume_range_by_request_id(user, "")


class TestCreateRangeInputValidation:
    def test_raises_typeerror_for_none_user(self):
        with pytest.raises(TypeError):
            services.create_range(None, "basic", {"windows": 1})

    def test_raises_typeerror_for_invalid_user(self):
        with pytest.raises(TypeError):
            services.create_range("not-user", "basic", {"windows": 1})
