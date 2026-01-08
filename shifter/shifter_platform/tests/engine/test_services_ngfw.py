"""Engine NGFW service tests.

Tests for engine.create_ngfw service function:
- Inputs: InstanceSpec with nested NGFWAppSpec from CMS hydrator
- Outputs: engine_ngfw_id (int)
- Side effects: creates Engine NGFW record, calls ECS provisioning
- Errors: validation errors for invalid InstanceSpec
- Logging: info on creation
"""

from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model

from engine.models import NGFW
from shared.enums import InstanceStatus
from shared.schemas import InstanceSpec, NGFWAppSpec

User = get_user_model()


@pytest.fixture
def user(db):
    return User.objects.create_user(
        username="test@example.com", email="test@example.com"
    )


@pytest.fixture
def ngfw_app_spec():
    """Hydrated NGFWAppSpec for testing."""
    return NGFWAppSpec(
        name="Test NGFW",
        registration_method="pin",
        deployment_profile_id=1,
        scm_credential_id=2,
        ngfw_id=100,
        user_id=1,
        authcode="D1234567",
        scm_folder_name="test-folder",
        scm_pin_id="pin-123",
        scm_pin_value="secret-pin-value",
        sls_region="americas",
    )


@pytest.fixture
def ngfw_instance_spec(ngfw_app_spec):
    """InstanceSpec with nested NGFWAppSpec for testing."""
    return InstanceSpec(
        name="Test NGFW",
        uuid="12345678-1234-1234-1234-123456789abc",
        role="ngfw",
        os_type="panos",
        ngfw_app=ngfw_app_spec,
    )


@pytest.mark.django_db
class TestCreateNgfw:
    """Tests for engine.create_ngfw() service function."""

    # -------------------------------------------------------------------------
    # Happy path
    # -------------------------------------------------------------------------

    def test_creates_engine_ngfw_record(self, user, ngfw_instance_spec):
        """create_ngfw creates an Engine NGFW model record."""
        from engine.services import create_ngfw

        ngfw_instance_spec.ngfw_app.user_id = user.id

        with patch("engine.ecs.start_ngfw_provisioning"):
            engine_ngfw_id = create_ngfw(ngfw_instance_spec)

        ngfw = NGFW.objects.get(id=engine_ngfw_id)
        assert ngfw.cms_ngfw_id == 100
        assert ngfw.status == InstanceStatus.PROVISIONING.value

    def test_returns_engine_ngfw_id(self, user, ngfw_instance_spec):
        """create_ngfw returns the Engine NGFW record ID."""
        from engine.services import create_ngfw

        ngfw_instance_spec.ngfw_app.user_id = user.id

        with patch("engine.ecs.start_ngfw_provisioning"):
            engine_ngfw_id = create_ngfw(ngfw_instance_spec)

        assert isinstance(engine_ngfw_id, int)
        assert NGFW.objects.filter(id=engine_ngfw_id).exists()

    def test_stores_ngfw_config(self, user, ngfw_instance_spec):
        """create_ngfw stores the full InstanceSpec in ngfw_config."""
        from engine.services import create_ngfw

        ngfw_instance_spec.ngfw_app.user_id = user.id

        with patch("engine.ecs.start_ngfw_provisioning"):
            engine_ngfw_id = create_ngfw(ngfw_instance_spec)

        ngfw = NGFW.objects.get(id=engine_ngfw_id)
        assert ngfw.ngfw_config is not None
        assert ngfw.ngfw_config["role"] == "ngfw"
        assert ngfw.ngfw_config["ngfw_app"]["authcode"] == "D1234567"

    def test_calls_ecs_provisioning(self, user, ngfw_instance_spec):
        """create_ngfw triggers ECS provisioning with Engine NGFW ID."""
        from engine.services import create_ngfw

        ngfw_instance_spec.ngfw_app.user_id = user.id

        with patch("engine.ecs.start_ngfw_provisioning") as mock_ecs:
            engine_ngfw_id = create_ngfw(ngfw_instance_spec)

            mock_ecs.assert_called_once_with(engine_ngfw_id)

    def test_associates_with_user(self, user, ngfw_instance_spec):
        """create_ngfw associates NGFW with the correct user."""
        from engine.services import create_ngfw

        ngfw_instance_spec.ngfw_app.user_id = user.id

        with patch("engine.ecs.start_ngfw_provisioning"):
            engine_ngfw_id = create_ngfw(ngfw_instance_spec)

        ngfw = NGFW.objects.get(id=engine_ngfw_id)
        assert ngfw.user_id == user.id

    # -------------------------------------------------------------------------
    # Input validation
    # -------------------------------------------------------------------------

    def test_raises_when_not_instance_spec(self, user):
        """create_ngfw raises ValueError when not given InstanceSpec."""
        from engine.services import create_ngfw

        with pytest.raises(ValueError, match="Expected InstanceSpec"):
            create_ngfw({"role": "ngfw"})

    def test_raises_when_wrong_role(self, user, ngfw_instance_spec):
        """create_ngfw raises ValueError when role is not 'ngfw'."""
        from engine.services import create_ngfw

        ngfw_instance_spec.ngfw_app.user_id = user.id
        # Create new spec with wrong role
        wrong_role_spec = InstanceSpec(
            name="Test",
            uuid="12345678-1234-1234-1234-123456789abc",
            role="victim",
            os_type="ubuntu",
        )

        with pytest.raises(ValueError, match="role='ngfw'"):
            create_ngfw(wrong_role_spec)

    def test_raises_when_ngfw_app_missing(self, user):
        """create_ngfw raises ValueError when ngfw_app is None."""
        from engine.services import create_ngfw

        spec = InstanceSpec(
            name="Test",
            uuid="12345678-1234-1234-1234-123456789abc",
            role="ngfw",
            os_type="panos",
            ngfw_app=None,
        )

        with pytest.raises(ValueError, match="ngfw_app is required"):
            create_ngfw(spec)

    def test_raises_when_ngfw_app_not_hydrated(self, user):
        """create_ngfw raises ValueError when ngfw_app is not hydrated."""
        from engine.services import create_ngfw

        # Non-hydrated spec - no authcode or credential values
        non_hydrated_app = NGFWAppSpec(
            name="Test NGFW",
            registration_method="pin",
            deployment_profile_id=1,
            scm_credential_id=2,
        )
        spec = InstanceSpec(
            name="Test",
            uuid="12345678-1234-1234-1234-123456789abc",
            role="ngfw",
            os_type="panos",
            ngfw_app=non_hydrated_app,
        )

        with pytest.raises(ValueError, match="must be hydrated"):
            create_ngfw(spec)

    def test_raises_when_user_not_found(self, db, ngfw_instance_spec):
        """create_ngfw raises User.DoesNotExist for invalid user_id."""
        from engine.services import create_ngfw

        ngfw_instance_spec.ngfw_app.user_id = 99999

        with pytest.raises(User.DoesNotExist), patch(
            "engine.ecs.start_ngfw_provisioning"
        ):
            create_ngfw(ngfw_instance_spec)

    # -------------------------------------------------------------------------
    # Logging
    # -------------------------------------------------------------------------

    def test_logs_info_on_creation(self, user, ngfw_instance_spec, caplog):
        """create_ngfw logs info when NGFW is created."""
        import logging

        from engine.services import create_ngfw

        ngfw_instance_spec.ngfw_app.user_id = user.id

        with (
            patch("engine.ecs.start_ngfw_provisioning"),
            caplog.at_level(logging.INFO, logger="engine.services"),
        ):
            create_ngfw(ngfw_instance_spec)

        assert "create_ngfw" in caplog.text or "NGFW" in caplog.text
