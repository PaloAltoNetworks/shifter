"""Tests for App DSL schemas."""

from datetime import UTC

import pytest
from pydantic import ValidationError

# =============================================================================
# AppSpecBase Tests
# =============================================================================


class TestAppSpecBase:
    """Tests for AppSpecBase - base spec for all app types."""

    def test_create_with_no_name(self):
        """AppSpecBase can be created without name (optional)."""
        from shared.schemas.app import AppSpecBase

        spec = AppSpecBase()
        assert spec.name is None

    def test_create_with_name(self):
        """AppSpecBase can be created with name."""
        from shared.schemas.app import AppSpecBase

        spec = AppSpecBase(name="My App")
        assert spec.name == "My App"

    def test_name_strips_whitespace(self):
        """AppSpecBase name validator strips whitespace."""
        from shared.schemas.app import AppSpecBase

        spec = AppSpecBase(name="  My App  ")
        assert spec.name == "My App"

    def test_empty_name_raises_error(self):
        """AppSpecBase rejects empty string name."""
        from shared.schemas.app import AppSpecBase

        with pytest.raises(ValidationError):
            AppSpecBase(name="   ")


# =============================================================================
# Type-Specific Spec Tests
# =============================================================================


class TestOSAppSpec:
    """Tests for OSAppSpec."""

    def test_default_app_type(self):
        """OSAppSpec has app_type='os' by default."""
        from shared.schemas.app import OSAppSpec

        spec = OSAppSpec()
        assert spec.app_type == "os"


class TestNGFWAppSpec:
    """Tests for NGFWAppSpec."""

    def test_default_app_type(self):
        """NGFWAppSpec has app_type='ngfw' by default."""
        from shared.schemas.app import NGFWAppSpec

        spec = NGFWAppSpec(
            name="Test NGFW",
            registration_method="pin",
        )
        assert spec.app_type == "ngfw"

    def test_required_fields(self):
        """NGFWAppSpec requires name and registration_method."""
        import pytest
        from pydantic import ValidationError

        from shared.schemas.app import NGFWAppSpec

        with pytest.raises(ValidationError) as exc_info:
            NGFWAppSpec()
        errors = exc_info.value.errors()
        error_fields = {e["loc"][0] for e in errors}
        assert "name" in error_fields
        assert "registration_method" in error_fields

    def test_deployment_profile_id_positive(self):
        """NGFWAppSpec deployment_profile_id must be positive if provided."""
        import pytest
        from pydantic import ValidationError

        from shared.schemas.app import NGFWAppSpec

        with pytest.raises(ValidationError):
            NGFWAppSpec(
                name="Test NGFW",
                deployment_profile_id=0,
                registration_method="pin",
            )

    def test_deployment_profile_id_optional(self):
        """NGFWAppSpec deployment_profile_id is optional."""
        from shared.schemas.app import NGFWAppSpec

        spec = NGFWAppSpec(
            name="Test NGFW",
            registration_method="pin",
        )
        assert spec.deployment_profile_id is None

    def test_registration_method_literal(self):
        """NGFWAppSpec registration_method must be 'pin' or 'otp'."""
        import pytest
        from pydantic import ValidationError

        from shared.schemas.app import NGFWAppSpec

        with pytest.raises(ValidationError):
            NGFWAppSpec(
                name="Test NGFW",
                deployment_profile_id=1,
                registration_method="invalid",
            )


class TestAgentAppSpec:
    """Tests for AgentAppSpec."""

    def test_default_app_type(self):
        """AgentAppSpec has app_type='agent' by default."""
        from shared.schemas.app import AgentAppSpec

        spec = AgentAppSpec()
        assert spec.app_type == "agent"


class TestOtherAppSpec:
    """Tests for OtherAppSpec."""

    def test_default_app_type(self):
        """OtherAppSpec has app_type='other' by default."""
        from shared.schemas.app import OtherAppSpec

        spec = OtherAppSpec()
        assert spec.app_type == "other"


# =============================================================================
# AppContextBase Tests
# =============================================================================


class TestAppContextBase:
    """Tests for AppContextBase - base context for all app types."""

    def test_create_with_required_fields(self):
        """AppContextBase can be created with app_id and name."""
        from shared.schemas.app import AppContextBase

        ctx = AppContextBase(app_id=1, name="Test App")
        assert ctx.app_id == 1
        assert ctx.name == "Test App"

    def test_app_id_must_be_positive(self):
        """AppContextBase rejects non-positive app_id."""
        from shared.schemas.app import AppContextBase

        with pytest.raises(ValidationError):
            AppContextBase(app_id=0, name="Test")

        with pytest.raises(ValidationError):
            AppContextBase(app_id=-1, name="Test")

    def test_app_id_is_required(self):
        """AppContextBase requires app_id."""
        from shared.schemas.app import AppContextBase

        with pytest.raises(ValidationError):
            AppContextBase(name="Test")

    def test_name_is_required(self):
        """AppContextBase requires name."""
        from shared.schemas.app import AppContextBase

        with pytest.raises(ValidationError):
            AppContextBase(app_id=1)


# =============================================================================
# Type-Specific Context Tests
# =============================================================================


class TestOSAppContext:
    """Tests for OSAppContext."""

    def test_default_app_type(self):
        """OSAppContext has app_type='os' by default."""
        from shared.schemas.app import OSAppContext

        ctx = OSAppContext(app_id=1, name="Ubuntu")
        assert ctx.app_type == "os"


class TestNGFWAppContext:
    """Tests for NGFWAppContext."""

    def test_default_app_type(self):
        """NGFWAppContext has app_type='ngfw' by default."""
        from datetime import datetime
        from uuid import uuid4

        from shared.schemas.app import NGFWAppContext

        ctx = NGFWAppContext(
            app_id=uuid4(),
            instance_id=uuid4(),
            name="VM-Series",
            status="ready",
            created_at=datetime.now(UTC),
        )
        assert ctx.app_type == "ngfw"

    def test_required_fields(self):
        """NGFWAppContext requires app_id, instance_id, name, status, created_at."""
        from uuid import uuid4

        import pytest
        from pydantic import ValidationError

        from shared.schemas.app import NGFWAppContext

        with pytest.raises(ValidationError) as exc_info:
            NGFWAppContext(app_id=uuid4(), instance_id=uuid4(), name="VM-Series")
        errors = exc_info.value.errors()
        error_fields = {e["loc"][0] for e in errors}
        assert "status" in error_fields
        assert "created_at" in error_fields

    def test_get_status_display(self):
        """NGFWAppContext get_status_display formats status for display."""
        from datetime import datetime
        from uuid import uuid4

        from shared.schemas.app import NGFWAppContext

        ctx = NGFWAppContext(
            app_id=uuid4(),
            instance_id=uuid4(),
            name="VM-Series",
            status="not_provisioned",
            created_at=datetime.now(UTC),
        )
        assert ctx.get_status_display() == "Not Provisioned"

    def test_uses_uuid_for_app_id(self):
        """NGFWAppContext uses UUID for app_id (not int like other app types)."""
        from datetime import datetime
        from uuid import UUID, uuid4

        from shared.schemas.app import NGFWAppContext

        app_id = uuid4()
        ctx = NGFWAppContext(
            app_id=app_id,
            instance_id=uuid4(),
            name="VM-Series",
            status="ready",
            created_at=datetime.now(UTC),
        )
        assert isinstance(ctx.app_id, UUID)
        assert ctx.app_id == app_id


class TestAgentAppContext:
    """Tests for AgentAppContext."""

    def test_default_app_type(self):
        """AgentAppContext has app_type='agent' by default."""
        from shared.schemas.app import AgentAppContext

        ctx = AgentAppContext(app_id=1, name="Cortex XDR")
        assert ctx.app_type == "agent"


class TestOtherAppContext:
    """Tests for OtherAppContext."""

    def test_default_app_type(self):
        """OtherAppContext has app_type='other' by default."""
        from shared.schemas.app import OtherAppContext

        ctx = OtherAppContext(app_id=1, name="Custom Tool")
        assert ctx.app_type == "other"


# =============================================================================
# AppContext Discriminated Union Tests
# =============================================================================


class TestAppContext:
    """Tests for AppContext discriminated union."""

    def test_routes_to_os_app_context(self):
        """AppContext routes to OSAppContext based on app_type."""
        from pydantic import TypeAdapter

        from shared.schemas.app import AppContext, OSAppContext

        adapter = TypeAdapter(AppContext)
        data = {"app_id": 1, "name": "Ubuntu", "app_type": "os"}
        result = adapter.validate_python(data)
        assert isinstance(result, OSAppContext)
        assert result.app_type == "os"

    def test_routes_to_ngfw_app_context(self):
        """AppContext routes to NGFWAppContext based on app_type."""
        from datetime import datetime
        from uuid import uuid4

        from pydantic import TypeAdapter

        from shared.schemas.app import AppContext, NGFWAppContext

        adapter = TypeAdapter(AppContext)
        data = {
            "app_id": str(uuid4()),
            "instance_id": str(uuid4()),
            "name": "VM-Series",
            "app_type": "ngfw",
            "status": "ready",
            "created_at": datetime.now(UTC).isoformat(),
        }
        result = adapter.validate_python(data)
        assert isinstance(result, NGFWAppContext)
        assert result.app_type == "ngfw"

    def test_routes_to_agent_app_context(self):
        """AppContext routes to AgentAppContext based on app_type."""
        from pydantic import TypeAdapter

        from shared.schemas.app import AgentAppContext, AppContext

        adapter = TypeAdapter(AppContext)
        data = {"app_id": 1, "name": "Cortex XDR", "app_type": "agent"}
        result = adapter.validate_python(data)
        assert isinstance(result, AgentAppContext)
        assert result.app_type == "agent"

    def test_routes_to_other_app_context(self):
        """AppContext routes to OtherAppContext based on app_type."""
        from pydantic import TypeAdapter

        from shared.schemas.app import AppContext, OtherAppContext

        adapter = TypeAdapter(AppContext)
        data = {"app_id": 1, "name": "Custom", "app_type": "other"}
        result = adapter.validate_python(data)
        assert isinstance(result, OtherAppContext)
        assert result.app_type == "other"


# =============================================================================
# AppRef Tests
# =============================================================================


class TestAppRef:
    """Tests for AppRef - minimal app reference."""

    def test_create_with_app_id(self):
        """AppRef can be created with app_id."""
        from shared.schemas.app import AppRef

        ref = AppRef(app_id=42)
        assert ref.app_id == 42

    def test_app_id_must_be_positive(self):
        """AppRef rejects non-positive app_id."""
        from shared.schemas.app import AppRef

        with pytest.raises(ValidationError):
            AppRef(app_id=0)

        with pytest.raises(ValidationError):
            AppRef(app_id=-1)

    def test_app_id_is_required(self):
        """AppRef requires app_id."""
        from shared.schemas.app import AppRef

        with pytest.raises(ValidationError):
            AppRef()


# =============================================================================
# NGFWAppRef Tests
# =============================================================================


class TestNGFWAppRef:
    """Tests for NGFWAppRef - minimal NGFW reference."""

    def test_create_with_required_fields(self):
        """NGFWAppRef can be created with required fields."""
        from uuid import uuid4

        from shared.schemas.app import NGFWAppRef

        app_id = uuid4()
        instance_id = uuid4()
        ref = NGFWAppRef(app_id=app_id, instance_id=instance_id)
        assert ref.app_id == app_id
        assert ref.instance_id == instance_id
        assert ref.is_deleted is False

    def test_app_id_must_be_uuid(self):
        """NGFWAppRef requires app_id to be a UUID."""
        from uuid import uuid4

        from shared.schemas.app import NGFWAppRef

        # Should work with UUID
        ref = NGFWAppRef(app_id=uuid4(), instance_id=uuid4())
        assert ref.is_deleted is False

    def test_is_deleted_defaults_to_false(self):
        """NGFWAppRef.is_deleted defaults to False."""
        from uuid import uuid4

        from shared.schemas.app import NGFWAppRef

        ref = NGFWAppRef(app_id=uuid4(), instance_id=uuid4())
        assert ref.is_deleted is False

    def test_is_deleted_can_be_set_true(self):
        """NGFWAppRef.is_deleted can be set to True."""
        from uuid import uuid4

        from shared.schemas.app import NGFWAppRef

        ref = NGFWAppRef(app_id=uuid4(), instance_id=uuid4(), is_deleted=True)
        assert ref.is_deleted is True


# =============================================================================
# LinkedRangeContext Tests
# =============================================================================


class TestLinkedRangeContext:
    """Tests for LinkedRangeContext - range linked to an NGFW."""

    def test_create_with_required_fields(self):
        """LinkedRangeContext can be created with required fields."""
        from datetime import datetime

        from shared.schemas.app import LinkedRangeContext

        ctx = LinkedRangeContext(
            range_id=42,
            status="ready",
            created_at=datetime.now(UTC),
        )
        assert ctx.range_id == 42
        assert ctx.status == "ready"

    def test_id_property_returns_range_id(self):
        """LinkedRangeContext.id returns range_id for template compatibility."""
        from datetime import datetime

        from shared.schemas.app import LinkedRangeContext

        ctx = LinkedRangeContext(
            range_id=42,
            status="ready",
            created_at=datetime.now(UTC),
        )
        assert ctx.id == 42

    def test_get_status_display(self):
        """LinkedRangeContext.get_status_display formats status for display."""
        from datetime import datetime

        from shared.schemas.app import LinkedRangeContext

        ctx = LinkedRangeContext(
            range_id=42,
            status="not_provisioned",
            created_at=datetime.now(UTC),
        )
        assert ctx.get_status_display() == "Not Provisioned"
