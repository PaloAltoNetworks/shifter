"""Tests for shared credential schemas.

Tests the Pydantic models used for credential data contracts:
- CredentialSpecBase: base for all credential specs
- SCMCredentialSpec: SCM credential creation specification
- DeploymentProfileSpec: deployment profile creation specification
- CredentialContext: template-safe projection for display
- CredentialRef: minimal reference for operations
"""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError


class TestCredentialSpecBase:
    """Tests for CredentialSpecBase Pydantic model."""

    def test_create_with_required_fields(self):
        """CredentialSpecBase can be created with required fields."""
        from shared.schemas.credentials import CredentialSpecBase

        spec = CredentialSpecBase(name="Test Cred", user_id=1)
        assert spec.name == "Test Cred"
        assert spec.user_id == 1
        assert spec.expires_at is None

    def test_inherits_name_validation_from_spec_base(self):
        """CredentialSpecBase inherits name validation from SpecBase."""
        from shared.schemas.credentials import CredentialSpecBase

        with pytest.raises(ValidationError, match="name"):
            CredentialSpecBase(name="", user_id=1)

        with pytest.raises(ValidationError, match="name"):
            CredentialSpecBase(name="   ", user_id=1)

    def test_name_is_stripped(self):
        """CredentialSpecBase strips whitespace from name."""
        from shared.schemas.credentials import CredentialSpecBase

        spec = CredentialSpecBase(name="  My Cred  ", user_id=1)
        assert spec.name == "My Cred"

    def test_user_id_is_required(self):
        """CredentialSpecBase requires user_id field."""
        from shared.schemas.credentials import CredentialSpecBase

        with pytest.raises(ValidationError):
            CredentialSpecBase(name="Test")

    def test_user_id_must_be_positive(self):
        """CredentialSpecBase rejects zero or negative user_id."""
        from shared.schemas.credentials import CredentialSpecBase

        with pytest.raises(ValidationError, match="user_id"):
            CredentialSpecBase(name="Test", user_id=0)

        with pytest.raises(ValidationError, match="user_id"):
            CredentialSpecBase(name="Test", user_id=-1)

    def test_expires_at_is_optional(self):
        """CredentialSpecBase expires_at defaults to None."""
        from shared.schemas.credentials import CredentialSpecBase

        spec = CredentialSpecBase(name="Test", user_id=1)
        assert spec.expires_at is None

    def test_expires_at_accepts_datetime(self):
        """CredentialSpecBase accepts datetime for expires_at."""
        from shared.schemas.credentials import CredentialSpecBase

        expiry = datetime.now(UTC) + timedelta(days=30)
        spec = CredentialSpecBase(name="Test", user_id=1, expires_at=expiry)
        assert spec.expires_at == expiry


class TestSCMCredentialSpec:
    """Tests for SCMCredentialSpec Pydantic model."""

    def test_create_scm_credential(self):
        """SCMCredentialSpec can be created with all fields."""
        from shared.schemas.credentials import SCMCredentialSpec

        spec = SCMCredentialSpec(
            name="My SCM Cred",
            user_id=1,
            scm_folder_name="folder",
            scm_pin_id="PIN123",
            scm_pin_value="secret",
            sls_region="americas",
        )
        assert spec.name == "My SCM Cred"
        assert spec.user_id == 1
        assert spec.scm_folder_name == "folder"
        assert spec.scm_pin_id == "PIN123"
        assert spec.scm_pin_value == "secret"
        assert spec.sls_region == "americas"

    def test_inherits_from_credential_spec_base(self):
        """SCMCredentialSpec inherits from CredentialSpecBase."""
        from shared.schemas.credentials import CredentialSpecBase, SCMCredentialSpec

        assert issubclass(SCMCredentialSpec, CredentialSpecBase)

    def test_scm_folder_name_is_required(self):
        """SCMCredentialSpec requires scm_folder_name."""
        from shared.schemas.credentials import SCMCredentialSpec

        with pytest.raises(ValidationError):
            SCMCredentialSpec(
                name="Test",
                user_id=1,
                scm_pin_id="PIN",
                scm_pin_value="secret",
                sls_region="americas",
            )

    def test_scm_pin_id_is_required(self):
        """SCMCredentialSpec requires scm_pin_id."""
        from shared.schemas.credentials import SCMCredentialSpec

        with pytest.raises(ValidationError):
            SCMCredentialSpec(
                name="Test",
                user_id=1,
                scm_folder_name="folder",
                scm_pin_value="secret",
                sls_region="americas",
            )

    def test_scm_pin_value_is_required(self):
        """SCMCredentialSpec requires scm_pin_value."""
        from shared.schemas.credentials import SCMCredentialSpec

        with pytest.raises(ValidationError):
            SCMCredentialSpec(
                name="Test",
                user_id=1,
                scm_folder_name="folder",
                scm_pin_id="PIN",
                sls_region="americas",
            )

    def test_sls_region_is_required(self):
        """SCMCredentialSpec requires sls_region."""
        from shared.schemas.credentials import SCMCredentialSpec

        with pytest.raises(ValidationError):
            SCMCredentialSpec(
                name="Test",
                user_id=1,
                scm_folder_name="folder",
                scm_pin_id="PIN",
                scm_pin_value="secret",
            )

    def test_sls_region_validates_allowed_values(self):
        """SCMCredentialSpec sls_region must be valid region."""
        from shared.schemas.credentials import SCMCredentialSpec

        with pytest.raises(ValidationError):
            SCMCredentialSpec(
                name="Test",
                user_id=1,
                scm_folder_name="folder",
                scm_pin_id="PIN",
                scm_pin_value="secret",
                sls_region="invalid",
            )

    def test_sls_region_allows_valid_regions(self):
        """SCMCredentialSpec accepts all valid SLS regions."""
        from shared.schemas.credentials import SCMCredentialSpec

        for region in ["americas", "europe", "japan", "asiapacific"]:
            spec = SCMCredentialSpec(
                name="Test",
                user_id=1,
                scm_folder_name="folder",
                scm_pin_id="PIN",
                scm_pin_value="secret",
                sls_region=region,
            )
            assert spec.sls_region == region

    def test_model_dump_returns_dict(self):
        """SCMCredentialSpec.model_dump() returns a dictionary."""
        from shared.schemas.credentials import SCMCredentialSpec

        spec = SCMCredentialSpec(
            name="Test",
            user_id=42,
            scm_folder_name="folder",
            scm_pin_id="PIN",
            scm_pin_value="secret",
            sls_region="americas",
        )
        result = spec.model_dump()
        assert isinstance(result, dict)
        assert result["name"] == "Test"
        assert result["user_id"] == 42
        assert result["scm_folder_name"] == "folder"

    def test_model_validate_from_dict(self):
        """SCMCredentialSpec.model_validate() creates instance from dict."""
        from shared.schemas.credentials import SCMCredentialSpec

        data = {
            "name": "Test Cred",
            "user_id": 1,
            "scm_folder_name": "folder",
            "scm_pin_id": "PIN",
            "scm_pin_value": "secret",
            "sls_region": "americas",
        }
        spec = SCMCredentialSpec.model_validate(data)
        assert spec.name == "Test Cred"
        assert spec.scm_folder_name == "folder"


class TestDeploymentProfileSpec:
    """Tests for DeploymentProfileSpec Pydantic model."""

    def test_create_deployment_profile(self):
        """DeploymentProfileSpec can be created with all fields."""
        from shared.schemas.credentials import DeploymentProfileSpec

        spec = DeploymentProfileSpec(
            name="My Profile",
            user_id=1,
            authcode="D1234567",
        )
        assert spec.name == "My Profile"
        assert spec.user_id == 1
        assert spec.authcode == "D1234567"

    def test_inherits_from_credential_spec_base(self):
        """DeploymentProfileSpec inherits from CredentialSpecBase."""
        from shared.schemas.credentials import CredentialSpecBase, DeploymentProfileSpec

        assert issubclass(DeploymentProfileSpec, CredentialSpecBase)

    def test_authcode_is_required(self):
        """DeploymentProfileSpec requires authcode."""
        from shared.schemas.credentials import DeploymentProfileSpec

        with pytest.raises(ValidationError):
            DeploymentProfileSpec(name="Test", user_id=1)

    def test_model_dump_returns_dict(self):
        """DeploymentProfileSpec.model_dump() returns a dictionary."""
        from shared.schemas.credentials import DeploymentProfileSpec

        spec = DeploymentProfileSpec(
            name="Test",
            user_id=42,
            authcode="D1234567",
        )
        result = spec.model_dump()
        assert isinstance(result, dict)
        assert result["name"] == "Test"
        assert result["user_id"] == 42
        assert result["authcode"] == "D1234567"

    def test_model_validate_from_dict(self):
        """DeploymentProfileSpec.model_validate() creates instance from dict."""
        from shared.schemas.credentials import DeploymentProfileSpec

        data = {
            "name": "Test Profile",
            "user_id": 1,
            "authcode": "D9999999",
        }
        spec = DeploymentProfileSpec.model_validate(data)
        assert spec.name == "Test Profile"
        assert spec.authcode == "D9999999"


class TestCredentialContextBase:
    """Tests for CredentialContextBase Pydantic model (base projection)."""

    def test_credential_id_must_be_positive(self):
        """CredentialContextBase rejects zero or negative credential_id."""
        from shared.schemas.credentials import CredentialContextBase

        now = datetime.now(UTC)
        with pytest.raises(ValidationError, match="credential_id"):
            CredentialContextBase(
                credential_id=0,
                name="Test",
                user_id=1,
                created_at=now,
            )

    def test_user_id_must_be_positive(self):
        """CredentialContextBase rejects zero or negative user_id."""
        from shared.schemas.credentials import CredentialContextBase

        now = datetime.now(UTC)
        with pytest.raises(ValidationError, match="user_id"):
            CredentialContextBase(
                credential_id=1,
                name="Test",
                user_id=0,
                created_at=now,
            )

    def test_is_deleted_defaults_to_false(self):
        """CredentialContextBase is_deleted defaults to False."""
        from shared.schemas.credentials import CredentialContextBase

        now = datetime.now(UTC)
        ctx = CredentialContextBase(
            credential_id=1,
            name="Test",
            user_id=1,
            created_at=now,
        )
        assert ctx.is_deleted is False

    def test_is_expired_false_when_no_expiration(self):
        """is_expired returns False when expires_at is None."""
        from shared.schemas.credentials import CredentialContextBase

        now = datetime.now(UTC)
        ctx = CredentialContextBase(
            credential_id=1,
            name="Test",
            user_id=1,
            created_at=now,
            expires_at=None,
        )
        assert ctx.is_expired is False

    def test_is_expired_true_when_past(self):
        """is_expired returns True when expires_at is in the past."""
        from shared.schemas.credentials import CredentialContextBase

        now = datetime.now(UTC)
        past = now - timedelta(days=1)
        ctx = CredentialContextBase(
            credential_id=1,
            name="Test",
            user_id=1,
            created_at=now,
            expires_at=past,
        )
        assert ctx.is_expired is True

    def test_is_expired_false_when_future(self):
        """is_expired returns False when expires_at is in the future."""
        from shared.schemas.credentials import CredentialContextBase

        now = datetime.now(UTC)
        future = now + timedelta(days=60)
        ctx = CredentialContextBase(
            credential_id=1,
            name="Test",
            user_id=1,
            created_at=now,
            expires_at=future,
        )
        assert ctx.is_expired is False

    def test_expires_soon_false_when_no_expiration(self):
        """expires_soon returns False when expires_at is None."""
        from shared.schemas.credentials import CredentialContextBase

        now = datetime.now(UTC)
        ctx = CredentialContextBase(
            credential_id=1,
            name="Test",
            user_id=1,
            created_at=now,
            expires_at=None,
        )
        assert ctx.expires_soon is False

    def test_expires_soon_false_when_expired(self):
        """expires_soon returns False when already expired."""
        from shared.schemas.credentials import CredentialContextBase

        now = datetime.now(UTC)
        past = now - timedelta(days=1)
        ctx = CredentialContextBase(
            credential_id=1,
            name="Test",
            user_id=1,
            created_at=now,
            expires_at=past,
        )
        assert ctx.expires_soon is False

    def test_expires_soon_true_within_30_days(self):
        """expires_soon returns True when expiring within 30 days."""
        from shared.schemas.credentials import CredentialContextBase

        now = datetime.now(UTC)
        soon = now + timedelta(days=15)
        ctx = CredentialContextBase(
            credential_id=1,
            name="Test",
            user_id=1,
            created_at=now,
            expires_at=soon,
        )
        assert ctx.expires_soon is True

    def test_expires_soon_false_beyond_30_days(self):
        """expires_soon returns False when expiring beyond 30 days."""
        from shared.schemas.credentials import CredentialContextBase

        now = datetime.now(UTC)
        far = now + timedelta(days=60)
        ctx = CredentialContextBase(
            credential_id=1,
            name="Test",
            user_id=1,
            created_at=now,
            expires_at=far,
        )
        assert ctx.expires_soon is False


class TestSCMCredentialContext:
    """Tests for SCMCredentialContext Pydantic model."""

    def test_create_scm_context(self):
        """SCMCredentialContext can be created with all fields."""
        from shared.schemas.credentials import SCMCredentialContext

        now = datetime.now(UTC)
        ctx = SCMCredentialContext(
            credential_id=1,
            name="SCM Cred",
            user_id=1,
            created_at=now,
            scm_folder_name="folder",
            scm_pin_id="PIN123",
            sls_region="americas",
        )
        assert ctx.credential_id == 1
        assert ctx.name == "SCM Cred"
        assert ctx.credential_type == "scm"
        assert ctx.scm_folder_name == "folder"
        assert ctx.scm_pin_id == "PIN123"
        assert ctx.sls_region == "americas"

    def test_inherits_from_credential_context_base(self):
        """SCMCredentialContext inherits from CredentialContextBase."""
        from shared.schemas.credentials import (
            CredentialContextBase,
            SCMCredentialContext,
        )

        assert issubclass(SCMCredentialContext, CredentialContextBase)

    def test_credential_type_defaults_to_scm(self):
        """SCMCredentialContext credential_type defaults to 'scm'."""
        from shared.schemas.credentials import SCMCredentialContext

        now = datetime.now(UTC)
        ctx = SCMCredentialContext(
            credential_id=1,
            name="Test",
            user_id=1,
            created_at=now,
            scm_folder_name="folder",
            scm_pin_id="PIN",
            sls_region="americas",
        )
        assert ctx.credential_type == "scm"

    def test_scm_fields_are_required(self):
        """SCMCredentialContext requires type-specific fields."""
        from shared.schemas.credentials import SCMCredentialContext

        now = datetime.now(UTC)
        with pytest.raises(ValidationError):
            SCMCredentialContext(
                credential_id=1,
                name="Test",
                user_id=1,
                created_at=now,
                # Missing: scm_folder_name, scm_pin_id, sls_region
            )

    def test_model_dump_includes_computed_fields(self):
        """model_dump() includes computed fields is_expired, expires_soon."""
        from shared.schemas.credentials import SCMCredentialContext

        now = datetime.now(UTC)
        ctx = SCMCredentialContext(
            credential_id=1,
            name="Test",
            user_id=1,
            created_at=now,
            expires_at=now + timedelta(days=15),
            scm_folder_name="folder",
            scm_pin_id="PIN",
            sls_region="americas",
        )
        result = ctx.model_dump()
        assert "is_expired" in result
        assert "expires_soon" in result
        assert result["is_expired"] is False
        assert result["expires_soon"] is True


class TestDeploymentProfileContext:
    """Tests for DeploymentProfileContext Pydantic model."""

    def test_create_deployment_profile_context(self):
        """DeploymentProfileContext can be created with all fields."""
        from shared.schemas.credentials import DeploymentProfileContext

        now = datetime.now(UTC)
        ctx = DeploymentProfileContext(
            credential_id=1,
            name="Profile",
            user_id=1,
            created_at=now,
            authcode_masked="D7654***",
        )
        assert ctx.credential_id == 1
        assert ctx.name == "Profile"
        assert ctx.credential_type == "deployment_profile"
        assert ctx.authcode_masked == "D7654***"

    def test_inherits_from_credential_context_base(self):
        """DeploymentProfileContext inherits from CredentialContextBase."""
        from shared.schemas.credentials import (
            CredentialContextBase,
            DeploymentProfileContext,
        )

        assert issubclass(DeploymentProfileContext, CredentialContextBase)

    def test_credential_type_defaults_to_deployment_profile(self):
        """DeploymentProfileContext credential_type defaults to 'deployment_profile'."""
        from shared.schemas.credentials import DeploymentProfileContext

        now = datetime.now(UTC)
        ctx = DeploymentProfileContext(
            credential_id=1,
            name="Test",
            user_id=1,
            created_at=now,
            authcode_masked="D1234***",
        )
        assert ctx.credential_type == "deployment_profile"

    def test_authcode_masked_is_required(self):
        """DeploymentProfileContext requires authcode_masked."""
        from shared.schemas.credentials import DeploymentProfileContext

        now = datetime.now(UTC)
        with pytest.raises(ValidationError):
            DeploymentProfileContext(
                credential_id=1,
                name="Test",
                user_id=1,
                created_at=now,
                # Missing: authcode_masked
            )


class TestCredentialContextDiscriminatedUnion:
    """Tests for CredentialContext discriminated union."""

    def test_validate_routes_to_scm_context(self):
        """model_validate routes to SCMCredentialContext based on credential_type."""

        from pydantic import TypeAdapter

        from shared.schemas.credentials import CredentialContext, SCMCredentialContext

        now = datetime.now(UTC)
        data = {
            "credential_id": 1,
            "name": "SCM Cred",
            "credential_type": "scm",
            "user_id": 42,
            "created_at": now.isoformat(),
            "scm_folder_name": "folder",
            "scm_pin_id": "PIN123",
            "sls_region": "americas",
        }
        adapter = TypeAdapter(CredentialContext)
        ctx = adapter.validate_python(data)
        assert isinstance(ctx, SCMCredentialContext)
        assert ctx.credential_type == "scm"
        assert ctx.scm_folder_name == "folder"

    def test_validate_routes_to_deployment_profile_context(self):
        """model_validate routes to DeploymentProfileContext based on credential_type."""
        from pydantic import TypeAdapter

        from shared.schemas.credentials import (
            CredentialContext,
            DeploymentProfileContext,
        )

        now = datetime.now(UTC)
        data = {
            "credential_id": 42,
            "name": "Test Cred",
            "credential_type": "deployment_profile",
            "user_id": 1,
            "created_at": now.isoformat(),
            "authcode_masked": "D1234***",
        }
        adapter = TypeAdapter(CredentialContext)
        ctx = adapter.validate_python(data)
        assert isinstance(ctx, DeploymentProfileContext)
        assert ctx.credential_type == "deployment_profile"
        assert ctx.authcode_masked == "D1234***"

    def test_invalid_credential_type_raises_error(self):
        """Invalid credential_type raises ValidationError."""
        from pydantic import TypeAdapter
        from pydantic import ValidationError as PydanticValidationError

        from shared.schemas.credentials import CredentialContext

        now = datetime.now(UTC)
        data = {
            "credential_id": 1,
            "name": "Test",
            "credential_type": "unknown",
            "user_id": 1,
            "created_at": now.isoformat(),
        }
        adapter = TypeAdapter(CredentialContext)
        with pytest.raises(PydanticValidationError):
            adapter.validate_python(data)


class TestCredentialRef:
    """Tests for CredentialRef Pydantic model (minimal reference projection)."""

    def test_create_with_required_fields(self):
        """CredentialRef can be created with required fields."""
        from shared.schemas.credentials import CredentialRef

        ref = CredentialRef(
            credential_id=123,
            user_id=42,
        )
        assert ref.credential_id == 123
        assert ref.user_id == 42
        assert ref.is_deleted is False

    def test_credential_id_must_be_positive(self):
        """CredentialRef rejects zero or negative credential_id."""
        from shared.schemas.credentials import CredentialRef

        with pytest.raises(ValidationError, match="credential_id"):
            CredentialRef(credential_id=0, user_id=1)

        with pytest.raises(ValidationError, match="credential_id"):
            CredentialRef(credential_id=-1, user_id=1)

    def test_user_id_must_be_positive(self):
        """CredentialRef rejects zero or negative user_id."""
        from shared.schemas.credentials import CredentialRef

        with pytest.raises(ValidationError, match="user_id"):
            CredentialRef(credential_id=1, user_id=0)

        with pytest.raises(ValidationError, match="user_id"):
            CredentialRef(credential_id=1, user_id=-1)

    def test_is_deleted_defaults_to_false(self):
        """CredentialRef is_deleted defaults to False."""
        from shared.schemas.credentials import CredentialRef

        ref = CredentialRef(credential_id=1, user_id=1)
        assert ref.is_deleted is False

    def test_is_deleted_can_be_true(self):
        """CredentialRef is_deleted can be set to True."""
        from shared.schemas.credentials import CredentialRef

        ref = CredentialRef(credential_id=1, user_id=1, is_deleted=True)
        assert ref.is_deleted is True

    def test_model_dump_returns_dict(self):
        """model_dump() returns a dictionary."""
        from shared.schemas.credentials import CredentialRef

        ref = CredentialRef(credential_id=123, user_id=42)
        result = ref.model_dump()
        assert isinstance(result, dict)
        assert result["credential_id"] == 123
        assert result["user_id"] == 42
        assert result["is_deleted"] is False

    def test_model_validate_from_dict(self):
        """model_validate() creates CredentialRef from dict."""
        from shared.schemas.credentials import CredentialRef

        data = {"credential_id": 123, "user_id": 42, "is_deleted": True}
        ref = CredentialRef.model_validate(data)
        assert ref.credential_id == 123
        assert ref.user_id == 42
        assert ref.is_deleted is True
