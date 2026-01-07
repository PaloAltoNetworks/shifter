"""Tests for App DSL schemas."""

import pytest
from pydantic import ValidationError

# =============================================================================
# AppSpecBase Tests
# =============================================================================


class TestAppSpecBase:
    """Tests for AppSpecBase - base spec for all app types."""

    def test_import_app_spec_base(self):
        """AppSpecBase can be imported from shared.schemas.app."""
        from shared.schemas.app import AppSpecBase

        assert AppSpecBase is not None

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

    def test_import(self):
        """OSAppSpec can be imported."""
        from shared.schemas.app import OSAppSpec

        assert OSAppSpec is not None

    def test_default_app_type(self):
        """OSAppSpec has app_type='os' by default."""
        from shared.schemas.app import OSAppSpec

        spec = OSAppSpec()
        assert spec.app_type == "os"

    def test_inherits_from_app_spec_base(self):
        """OSAppSpec inherits from AppSpecBase."""
        from shared.schemas.app import AppSpecBase, OSAppSpec

        assert issubclass(OSAppSpec, AppSpecBase)


class TestNGFWAppSpec:
    """Tests for NGFWAppSpec."""

    def test_import(self):
        """NGFWAppSpec can be imported."""
        from shared.schemas.app import NGFWAppSpec

        assert NGFWAppSpec is not None

    def test_default_app_type(self):
        """NGFWAppSpec has app_type='ngfw' by default."""
        from shared.schemas.app import NGFWAppSpec

        spec = NGFWAppSpec()
        assert spec.app_type == "ngfw"

    def test_inherits_from_app_spec_base(self):
        """NGFWAppSpec inherits from AppSpecBase."""
        from shared.schemas.app import AppSpecBase, NGFWAppSpec

        assert issubclass(NGFWAppSpec, AppSpecBase)


class TestAgentAppSpec:
    """Tests for AgentAppSpec."""

    def test_import(self):
        """AgentAppSpec can be imported."""
        from shared.schemas.app import AgentAppSpec

        assert AgentAppSpec is not None

    def test_default_app_type(self):
        """AgentAppSpec has app_type='agent' by default."""
        from shared.schemas.app import AgentAppSpec

        spec = AgentAppSpec()
        assert spec.app_type == "agent"

    def test_inherits_from_app_spec_base(self):
        """AgentAppSpec inherits from AppSpecBase."""
        from shared.schemas.app import AgentAppSpec, AppSpecBase

        assert issubclass(AgentAppSpec, AppSpecBase)


class TestOtherAppSpec:
    """Tests for OtherAppSpec."""

    def test_import(self):
        """OtherAppSpec can be imported."""
        from shared.schemas.app import OtherAppSpec

        assert OtherAppSpec is not None

    def test_default_app_type(self):
        """OtherAppSpec has app_type='other' by default."""
        from shared.schemas.app import OtherAppSpec

        spec = OtherAppSpec()
        assert spec.app_type == "other"

    def test_inherits_from_app_spec_base(self):
        """OtherAppSpec inherits from AppSpecBase."""
        from shared.schemas.app import AppSpecBase, OtherAppSpec

        assert issubclass(OtherAppSpec, AppSpecBase)


# =============================================================================
# AppContextBase Tests
# =============================================================================


class TestAppContextBase:
    """Tests for AppContextBase - base context for all app types."""

    def test_import(self):
        """AppContextBase can be imported."""
        from shared.schemas.app import AppContextBase

        assert AppContextBase is not None

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

    def test_import(self):
        """OSAppContext can be imported."""
        from shared.schemas.app import OSAppContext

        assert OSAppContext is not None

    def test_default_app_type(self):
        """OSAppContext has app_type='os' by default."""
        from shared.schemas.app import OSAppContext

        ctx = OSAppContext(app_id=1, name="Ubuntu")
        assert ctx.app_type == "os"

    def test_inherits_from_app_context_base(self):
        """OSAppContext inherits from AppContextBase."""
        from shared.schemas.app import AppContextBase, OSAppContext

        assert issubclass(OSAppContext, AppContextBase)


class TestNGFWAppContext:
    """Tests for NGFWAppContext."""

    def test_import(self):
        """NGFWAppContext can be imported."""
        from shared.schemas.app import NGFWAppContext

        assert NGFWAppContext is not None

    def test_default_app_type(self):
        """NGFWAppContext has app_type='ngfw' by default."""
        from shared.schemas.app import NGFWAppContext

        ctx = NGFWAppContext(app_id=1, name="VM-Series")
        assert ctx.app_type == "ngfw"

    def test_inherits_from_app_context_base(self):
        """NGFWAppContext inherits from AppContextBase."""
        from shared.schemas.app import AppContextBase, NGFWAppContext

        assert issubclass(NGFWAppContext, AppContextBase)


class TestAgentAppContext:
    """Tests for AgentAppContext."""

    def test_import(self):
        """AgentAppContext can be imported."""
        from shared.schemas.app import AgentAppContext

        assert AgentAppContext is not None

    def test_default_app_type(self):
        """AgentAppContext has app_type='agent' by default."""
        from shared.schemas.app import AgentAppContext

        ctx = AgentAppContext(app_id=1, name="Cortex XDR")
        assert ctx.app_type == "agent"

    def test_inherits_from_app_context_base(self):
        """AgentAppContext inherits from AppContextBase."""
        from shared.schemas.app import AgentAppContext, AppContextBase

        assert issubclass(AgentAppContext, AppContextBase)


class TestOtherAppContext:
    """Tests for OtherAppContext."""

    def test_import(self):
        """OtherAppContext can be imported."""
        from shared.schemas.app import OtherAppContext

        assert OtherAppContext is not None

    def test_default_app_type(self):
        """OtherAppContext has app_type='other' by default."""
        from shared.schemas.app import OtherAppContext

        ctx = OtherAppContext(app_id=1, name="Custom Tool")
        assert ctx.app_type == "other"

    def test_inherits_from_app_context_base(self):
        """OtherAppContext inherits from AppContextBase."""
        from shared.schemas.app import AppContextBase, OtherAppContext

        assert issubclass(OtherAppContext, AppContextBase)


# =============================================================================
# AppContext Discriminated Union Tests
# =============================================================================


class TestAppContext:
    """Tests for AppContext discriminated union."""

    def test_import(self):
        """AppContext can be imported."""
        from shared.schemas.app import AppContext

        assert AppContext is not None

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
        from pydantic import TypeAdapter

        from shared.schemas.app import AppContext, NGFWAppContext

        adapter = TypeAdapter(AppContext)
        data = {"app_id": 1, "name": "VM-Series", "app_type": "ngfw"}
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

    def test_import(self):
        """AppRef can be imported."""
        from shared.schemas.app import AppRef

        assert AppRef is not None

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
# Package Export Tests
# =============================================================================


class TestPackageExports:
    """Tests for shared.schemas package exports."""

    def test_all_app_classes_exported_from_package(self):
        """All App classes are exported from shared.schemas."""
        from shared.schemas import (
            AgentAppContext,
            AgentAppSpec,
            AppContext,
            AppContextBase,
            AppRef,
            AppSpecBase,
            NGFWAppContext,
            NGFWAppSpec,
            OSAppContext,
            OSAppSpec,
            OtherAppContext,
            OtherAppSpec,
        )

        assert AppSpecBase is not None
        assert OSAppSpec is not None
        assert NGFWAppSpec is not None
        assert AgentAppSpec is not None
        assert OtherAppSpec is not None
        assert AppContextBase is not None
        assert OSAppContext is not None
        assert NGFWAppContext is not None
        assert AgentAppContext is not None
        assert OtherAppContext is not None
        assert AppContext is not None
        assert AppRef is not None
