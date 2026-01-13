"""Tests for base schemas.

Tests the SpecBase Pydantic model - the root of the spec hierarchy.
"""

import pytest
from pydantic import ValidationError


class TestSpecBase:
    """Tests for SpecBase Pydantic model."""

    def test_import_spec_base(self):
        """SpecBase can be imported from shared.schemas.base."""
        from shared.schemas.base import SpecBase

        assert SpecBase is not None

    def test_create_with_name(self):
        """SpecBase can be created with a name."""
        from shared.schemas.base import SpecBase

        spec = SpecBase(name="Test Entity")
        assert spec.name == "Test Entity"

    def test_name_is_optional(self):
        """SpecBase allows name to be optional (subclasses can require it)."""
        from shared.schemas.base import SpecBase

        spec = SpecBase()
        assert spec.name is None

    def test_name_cannot_be_empty(self):
        """SpecBase rejects empty name."""
        from shared.schemas.base import SpecBase

        with pytest.raises(ValidationError, match="name"):
            SpecBase(name="")

    def test_name_cannot_be_whitespace(self):
        """SpecBase rejects whitespace-only name."""
        from shared.schemas.base import SpecBase

        with pytest.raises(ValidationError, match="name"):
            SpecBase(name="   ")

    def test_name_is_stripped(self):
        """SpecBase strips whitespace from name."""
        from shared.schemas.base import SpecBase

        spec = SpecBase(name="  My Entity  ")
        assert spec.name == "My Entity"

    def test_model_dump_returns_dict(self):
        """SpecBase.model_dump() returns a dictionary."""
        from shared.schemas.base import SpecBase

        spec = SpecBase(name="Test")
        result = spec.model_dump()
        assert isinstance(result, dict)
        assert result["name"] == "Test"

    def test_model_validate_from_dict(self):
        """SpecBase.model_validate() creates instance from dict."""
        from shared.schemas.base import SpecBase

        data = {"name": "From Dict"}
        spec = SpecBase.model_validate(data)
        assert spec.name == "From Dict"

    def test_subclass_inherits_name_validation(self):
        """Subclasses inherit name validation from SpecBase."""
        from shared.schemas.base import SpecBase

        class ChildSpec(SpecBase):
            extra_field: str

        # Valid
        child = ChildSpec(name="Valid", extra_field="test")
        assert child.name == "Valid"

        # Invalid - empty name
        with pytest.raises(ValidationError, match="name"):
            ChildSpec(name="", extra_field="test")
