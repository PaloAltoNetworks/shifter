"""Behavior tests for the cms.services NGFW entrypoints.

Drives ``list_ngfws`` / ``get_ngfw`` / ``create_ngfw`` / ``destroy_ngfw`` and the
internal validation/resolution helpers against real ``Credential`` /
``Request`` / ``Instance`` / ``App`` / ``AuditLog`` rows (the seeded
``panw-ngfw`` catalog types and ``deployment_profile`` / ``scm`` credential
types), instead of patching ``App.objects`` / ``Credential`` /
``Request.objects`` / ``hydrate_ngfw`` / ``engine.services.*`` / ``audit_log``.

create_ngfw runs the full resolve -> provision -> hydrate -> dispatch stack: the
engine NGFW provisioning is a no-op because ECS is unconfigured in the test
settings (no cloud mock needed). The engine-error path is driven by a real
engine NGFW instance with an attached range, which the real
``engine.services.destroy_ngfw`` rejects.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model

from cms.exceptions import CMSError
from cms.services import create_ngfw, destroy_ngfw, get_ngfw, list_ngfws
from cms.services._ngfws import (
    _resolve_ngfw_deployment_profile,
    _resolve_ngfw_registration,
    _validate_app_id,
    _validate_ngfw_name,
    _validate_ngfw_user,
)
from risk_register.models import AuditLog
from shared.cloud.exceptions import CloudTaskError
from shared.enums import RequestType, ResourceStatus
from shared.schemas.app import NGFWAppContext, NGFWAppRef

pytestmark = pytest.mark.django_db

User = get_user_model()

_CRED_SPEC = {
    "deployment_profile": "credential.deployment_profile",
    "scm": "credential.scm",
}
_SCM_DATA = {
    "name": "scm",
    "scm_pin_id": "PIN1",
    "scm_pin_value": "VAL1",
    "scm_folder_name": "folder",
    "sls_region": "us",
}


@pytest.fixture(autouse=True)
def _ngfw_catalog(db):
    """Ensure the ``panw-ngfw`` catalog types exist for this test.

    They are migration-seeded, but a ``TransactionTestCase`` elsewhere can flush
    migration-seeded rows from a worker's DB under xdist (the gotcha documented
    in ``test_credential_encryption``), so re-create them defensively rather than
    relying on ``.get()`` finding the seed.
    """
    from cms.models import AppType, InstanceType

    InstanceType.objects.get_or_create(
        slug="panw-ngfw", defaults={"name": "PAN-OS NGFW", "spec_slug": "instance.panw-ngfw"}
    )
    AppType.objects.get_or_create(slug="panw-ngfw", defaults={"name": "PANW NGFW", "spec_slug": "app.panw-ngfw"})


@pytest.fixture
def user(db):
    return User.objects.create_user(username="svc-ngfw@example.com", email="svc-ngfw@example.com")


def _credential(user, slug, data):
    from cms.models import Credential, CredentialType

    ct, _ = CredentialType.objects.get_or_create(slug=slug, defaults={"name": slug, "spec_slug": _CRED_SPEC[slug]})
    return Credential.objects.create(user=user, credential_type=ct, name=f"{slug}-cred", data=data)


@pytest.fixture
def deployment_profile(user):
    return _credential(user, "deployment_profile", {"name": "dp", "authcode": "AUTH-XYZ"})


@pytest.fixture
def scm_credential(user):
    return _credential(user, "scm", _SCM_DATA)


def _cms_ngfw(user, *, name="NGFW", status=ResourceStatus.READY.value, serial="X-1", request_id=None):
    """Create a real CMS NGFW App (Request + Instance + App with panw-ngfw types)."""
    from cms.models import App, AppType, Instance, InstanceType, Request

    req = Request.objects.create(request_id=request_id or uuid4(), request_type=RequestType.NGFW.value, user=user)
    instance = Instance.objects.create(
        request=req, name=name, instance_type=InstanceType.objects.get(slug="panw-ngfw"), status=status
    )
    return App.objects.create(
        name=name,
        app_type=AppType.objects.get(slug="panw-ngfw"),
        instance=instance,
        status=status,
        data={"serial_number": serial},
    )


# ---------------------------------------------------------------------------
# Validation helpers (pure)
# ---------------------------------------------------------------------------


class TestValidateNgfwUser:
    def test_raises_typeerror_for_none(self):
        with pytest.raises(TypeError):
            _validate_ngfw_user(None)

    def test_raises_valueerror_for_unsaved_user(self):
        with pytest.raises(ValueError):
            _validate_ngfw_user(User(username="unsaved"))


class TestValidateNgfwName:
    def test_strips_and_returns(self):
        assert _validate_ngfw_name("  Box  ") == "Box"

    @pytest.mark.parametrize("bad", ["", "   ", None])
    def test_raises_for_empty(self, bad):
        with pytest.raises(ValueError):
            _validate_ngfw_name(bad)


class TestValidateAppId:
    def test_accepts_uuid(self):
        u = uuid4()
        assert _validate_app_id(u) == u

    def test_parses_uuid_string(self):
        u = uuid4()
        assert _validate_app_id(str(u)) == u

    def test_raises_typeerror_for_none(self):
        with pytest.raises(TypeError):
            _validate_app_id(None)

    def test_raises_typeerror_for_int(self):
        with pytest.raises(TypeError):
            _validate_app_id(123)

    def test_raises_valueerror_for_bad_uuid_string(self):
        with pytest.raises(ValueError):
            _validate_app_id("not-a-uuid")


# ---------------------------------------------------------------------------
# Resolution helpers (real Credential model + rows)
# ---------------------------------------------------------------------------


class TestResolveDeploymentProfile:
    def test_requires_id(self, user):
        from cms.models import Credential

        with pytest.raises(ValueError):
            _resolve_ngfw_deployment_profile(user, 0, Credential)

    def test_returns_when_slug_matches(self, user, deployment_profile):
        from cms.models import Credential

        result = _resolve_ngfw_deployment_profile(user, deployment_profile.id, Credential)
        assert result.pk == deployment_profile.pk

    def test_raises_cms_error_when_not_found(self, user):
        from cms.models import Credential

        with pytest.raises(CMSError, match="Deployment profile not found"):
            _resolve_ngfw_deployment_profile(user, 999999, Credential)

    def test_raises_cms_error_when_wrong_type(self, user, scm_credential):
        from cms.models import Credential

        with pytest.raises(CMSError, match="must reference a deployment profile"):
            _resolve_ngfw_deployment_profile(user, scm_credential.id, Credential)


class TestResolveNgfwRegistration:
    def test_invalid_method(self, user):
        from cms.models import Credential

        with pytest.raises(ValueError, match="registration_method"):
            _resolve_ngfw_registration(user, "bogus", None, None, None, Credential)

    def test_otp_requires_value_and_folder(self, user):
        from cms.models import Credential

        with pytest.raises(ValueError, match="otp"):
            _resolve_ngfw_registration(user, "otp", None, None, None, Credential)

    def test_otp_returns_none(self, user):
        from cms.models import Credential

        assert _resolve_ngfw_registration(user, "otp", None, "OTP123", "folder/", Credential) is None

    def test_pin_requires_scm_credential_id(self, user):
        from cms.models import Credential

        with pytest.raises(ValueError, match="scm_credential_id"):
            _resolve_ngfw_registration(user, "pin", None, None, None, Credential)

    def test_pin_returns_scm_credential(self, user, scm_credential):
        from cms.models import Credential

        result = _resolve_ngfw_registration(user, "pin", scm_credential.id, None, None, Credential)
        assert result.pk == scm_credential.pk

    def test_pin_raises_when_credential_not_found(self, user):
        from cms.models import Credential

        with pytest.raises(CMSError, match="SCM credential not found"):
            _resolve_ngfw_registration(user, "pin", 999999, None, None, Credential)

    def test_pin_raises_when_wrong_type(self, user, deployment_profile):
        from cms.models import Credential

        with pytest.raises(CMSError, match="must reference an SCM credential"):
            _resolve_ngfw_registration(user, "pin", deployment_profile.id, None, None, Credential)


# ---------------------------------------------------------------------------
# Public list / get
# ---------------------------------------------------------------------------


class TestListNgfws:
    def test_returns_projection_list(self, user):
        _cms_ngfw(user, name="A")
        _cms_ngfw(user, name="B")
        result = list_ngfws(user)
        assert all(isinstance(r, NGFWAppContext) for r in result)
        assert {r.name for r in result} == {"A", "B"}

    def test_excludes_other_users(self, user, django_user_model):
        other = django_user_model.objects.create_user(username="ngfw-other@e.com", email="ngfw-other@e.com")
        _cms_ngfw(user, name="Mine")
        _cms_ngfw(other, name="Theirs")
        assert {r.name for r in list_ngfws(user)} == {"Mine"}

    def test_validates_user(self):
        with pytest.raises(TypeError):
            list_ngfws(None)


class TestGetNgfw:
    def test_returns_projection(self, user):
        app = _cms_ngfw(user, name="N1", serial="SER-9")
        result = get_ngfw(user, app.id)
        assert result.name == "N1"
        assert result.app_id == app.id
        assert result.serial_number == "SER-9"

    def test_raises_cms_error_when_missing(self, user):
        with pytest.raises(CMSError, match="NGFW not found"):
            get_ngfw(user, uuid4())

    def test_raises_cms_error_for_other_users_ngfw(self, user, django_user_model):
        other = django_user_model.objects.create_user(username="ngfw-other2@e.com", email="ngfw-other2@e.com")
        app = _cms_ngfw(other, name="Theirs")
        with pytest.raises(CMSError, match="NGFW not found"):
            get_ngfw(user, app.id)


# ---------------------------------------------------------------------------
# create_ngfw (full real stack; engine ECS unconfigured => no-op dispatch)
# ---------------------------------------------------------------------------


class TestCreateNgfw:
    def test_creates_ngfw_via_otp(self, user, deployment_profile):
        from cms.models import App

        ref = create_ngfw(
            user=user,
            name="MyNGFW",
            deployment_profile_id=deployment_profile.id,
            registration_method="otp",
            otp_value="OTP123",
            otp_folder="folder/",
        )

        assert isinstance(ref, NGFWAppRef)
        assert ref.is_deleted is False
        app = App.objects.get(pk=ref.app_id)
        assert app.name == "MyNGFW"
        assert app.app_type.slug == "panw-ngfw"
        assert App.objects.filter(instance__request__user=user, app_type__slug="panw-ngfw").exists()
        assert AuditLog.objects.filter(
            entity_type=AuditLog.EntityType.NGFW, action=AuditLog.Action.PROVISION, actor_id=user.id
        ).exists()

    def test_creates_ngfw_via_pin(self, user, deployment_profile, scm_credential):
        ref = create_ngfw(
            user=user,
            name="PinNGFW",
            deployment_profile_id=deployment_profile.id,
            registration_method="pin",
            scm_credential_id=scm_credential.id,
        )
        assert isinstance(ref, NGFWAppRef)
        assert ref.is_deleted is False

    def test_rejects_when_existing_active(self, user, deployment_profile):
        _cms_ngfw(user, name="Existing", status=ResourceStatus.READY.value)
        with pytest.raises(CMSError, match="already have an active NGFW"):
            create_ngfw(
                user=user,
                name="Second",
                deployment_profile_id=deployment_profile.id,
                registration_method="otp",
                otp_value="V",
                otp_folder="F",
            )

    def test_validates_user(self):
        with pytest.raises(TypeError):
            create_ngfw(user=None, name="X", deployment_profile_id=1, registration_method="pin")

    def test_marks_owned_records_failed_when_engine_dispatch_fails(self, user, deployment_profile, settings):
        from cms.models import App as CMSApp
        from cms.models import Instance as CMSInstance
        from engine.models import App as EngineApp
        from engine.models import Instance as EngineInstance

        settings.CLOUD_PROVIDER = "aws"
        settings.LOCAL_PROVISIONER = None
        settings.ENGINE_TASK_CLUSTER = "test-cluster"
        settings.ENGINE_TASK_DEFINITION = "test-taskdef"
        settings.ENGINE_TASK_NETWORK_SECURITY_GROUP_ID = "sg-test"
        settings.ENGINE_TASK_NETWORK_SUBNET_IDS = "subnet-aaa,subnet-bbb"
        ecs_client = MagicMock()
        ecs_client.run_task.return_value = {"tasks": [], "failures": [{"reason": "RESOURCE:CPU"}]}

        with patch("boto3.client", return_value=ecs_client), pytest.raises(CloudTaskError):
            create_ngfw(
                user=user,
                name="DispatchFailNGFW",
                deployment_profile_id=deployment_profile.id,
                registration_method="otp",
                otp_value="OTP123",
                otp_folder="folder/",
            )

        cms_app = CMSApp.all_objects.get(instance__request__user=user)
        cms_instance = CMSInstance.all_objects.get(request__user=user)
        assert cms_app.status == ResourceStatus.FAILED.value
        assert cms_app.deleted_at is not None
        assert cms_instance.status == ResourceStatus.FAILED.value
        assert cms_instance.deleted_at is not None

        engine_instance = EngineInstance.objects.get(request__request_id=cms_instance.request.request_id)
        engine_app = EngineApp.objects.get(request__request_id=cms_instance.request.request_id)
        assert engine_instance.status == ResourceStatus.FAILED.value
        assert engine_app.status == ResourceStatus.FAILED.value
        assert not AuditLog.objects.filter(
            entity_type=AuditLog.EntityType.NGFW,
            action=AuditLog.Action.PROVISION,
            actor_id=user.id,
        ).exists()

    def test_marks_owned_records_failed_when_hydration_fails(self, user, caplog):
        """Hydrator failure marks CMS Instance/App FAILED and logs at ERROR without leaking secrets."""
        import logging

        from cms.models import App as CMSApp
        from cms.models import Instance as CMSInstance

        # A deployment profile with no authcode makes the real hydrate_ngfw raise
        # CMSError during CMS->Engine translation, before any engine dispatch.
        bad_profile = _credential(user, "deployment_profile", {"name": "dp"})

        with caplog.at_level(logging.ERROR), pytest.raises(CMSError):
            create_ngfw(
                user=user,
                name="HydrationFailNGFW",
                deployment_profile_id=bad_profile.id,
                registration_method="otp",
                otp_value="OTP123",
                otp_folder="folder/",
            )

        cms_app = CMSApp.all_objects.get(instance__request__user=user)
        cms_instance = CMSInstance.all_objects.get(request__user=user)
        assert cms_app.status == ResourceStatus.FAILED.value
        assert cms_app.deleted_at is not None
        assert cms_instance.status == ResourceStatus.FAILED.value
        assert cms_instance.deleted_at is not None

        assert not AuditLog.objects.filter(
            entity_type=AuditLog.EntityType.NGFW,
            action=AuditLog.Action.PROVISION,
            actor_id=user.id,
        ).exists()

        # The service-boundary compensation logs the failure with request context.
        # This service-level ERROR record is the red-green driver for the logging change.
        assert any(record.name == "cms.services._ngfws" for record in caplog.records), (
            "Expected an ERROR log from cms.services._ngfws"
        )
        assert str(user.id) in caplog.text, "Expected user_id in log message"
        # Secrets must never appear in log output.
        assert "OTP123" not in caplog.text, "OTP value must not appear in log"
        assert "folder/" not in caplog.text, "OTP folder must not appear in log"


# ---------------------------------------------------------------------------
# destroy_ngfw
# ---------------------------------------------------------------------------


class TestDestroyNgfw:
    def test_happy_path_sets_destroying_and_audits(self, user):
        app = _cms_ngfw(user, name="ToKill")
        ref = destroy_ngfw(user, app.id, "ToKill")

        assert isinstance(ref, NGFWAppRef)
        assert ref.is_deleted is True
        app.refresh_from_db()
        assert app.status == ResourceStatus.DESTROYING.value
        assert app.deleted_at is not None
        assert AuditLog.objects.filter(
            entity_type=AuditLog.EntityType.NGFW, action=AuditLog.Action.DEPROVISION, actor_id=user.id
        ).exists()

    def test_raises_when_not_found(self, user):
        with pytest.raises(CMSError, match="NGFW not found"):
            destroy_ngfw(user, uuid4(), "anything")

    def test_raises_on_name_mismatch(self, user):
        app = _cms_ngfw(user, name="ToKill")
        with pytest.raises(ValueError, match="Name confirmation"):
            destroy_ngfw(user, app.id, "wrong")

    def test_propagates_engine_error_as_cms_error(self, user):
        """A real attached engine range makes engine.services.destroy_ngfw reject -> CMSError."""
        from engine.models import Instance as EngInstance
        from engine.models import Range as EngRange
        from engine.models import Request as EngRequest

        rid = uuid4()
        app = _cms_ngfw(user, name="Attached", request_id=rid)

        eng_req = EngRequest.objects.create(request_id=rid, request_type=RequestType.NGFW.value, user=user)
        eng_ngfw = EngInstance.objects.create(
            uuid=uuid4(),
            request=eng_req,
            role=EngInstance.Role.NGFW,
            os_type=EngInstance.OSType.PANOS,
            status=ResourceStatus.READY.value,
        )
        EngRange.objects.create(user=user, status=EngRange.Status.READY, ngfw_instance=eng_ngfw)

        with pytest.raises(CMSError, match="still attached"):
            destroy_ngfw(user, app.id, "Attached")
