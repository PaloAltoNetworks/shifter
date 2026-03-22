"""Tests for CMS OperatingSystem model.

These tests verify the OperatingSystem model is:
- Importable from cms.models
- Has correct fields (slug, name, extensions)
- Has proper methods (get_for_extension)
- Has correct meta options (ordering, verbose_name)
"""

from unittest.mock import MagicMock, patch

from django.db import models

# -----------------------------------------------------------------------------
# Test OperatingSystem Model Structure
# -----------------------------------------------------------------------------


class TestOperatingSystemModel:
    """Tests for OperatingSystem model structure."""

    def test_operating_system_can_be_imported_from_cms(self):
        """OperatingSystem should be importable from cms.models."""
        from cms.models import OperatingSystem

        assert OperatingSystem is not None

    def test_operating_system_is_not_abstract(self):
        """OperatingSystem should be a concrete model."""
        from cms.models import OperatingSystem

        assert OperatingSystem._meta.abstract is False

    def test_operating_system_has_slug_field(self):
        """OperatingSystem should have a slug SlugField."""
        from cms.models import OperatingSystem

        field = OperatingSystem._meta.get_field("slug")
        assert isinstance(field, models.SlugField)
        assert field.max_length == 50
        assert field.unique is True

    def test_operating_system_has_name_field(self):
        """OperatingSystem should have a name CharField."""
        from cms.models import OperatingSystem

        field = OperatingSystem._meta.get_field("name")
        assert isinstance(field, models.CharField)
        assert field.max_length == 100

    def test_operating_system_has_extensions_field(self):
        """OperatingSystem should have an extensions JSONField."""
        from cms.models import OperatingSystem

        field = OperatingSystem._meta.get_field("extensions")
        assert isinstance(field, models.JSONField)

    def test_operating_system_has_ordering_meta(self):
        """OperatingSystem should be ordered by name."""
        from cms.models import OperatingSystem

        assert OperatingSystem._meta.ordering == ["name"]

    def test_operating_system_has_verbose_name_meta(self):
        """OperatingSystem should have correct verbose names."""
        from cms.models import OperatingSystem

        assert OperatingSystem._meta.verbose_name == "Operating System"
        assert OperatingSystem._meta.verbose_name_plural == "Operating Systems"


# -----------------------------------------------------------------------------
# Test OperatingSystem Properties (no DB needed)
# -----------------------------------------------------------------------------


class TestOperatingSystemProperties:
    """Tests for OperatingSystem model properties using in-memory construction."""

    def test_str_returns_name(self):
        """__str__ should return the OS name."""
        from cms.models import OperatingSystem

        os = OperatingSystem(slug="test", name="Test OS", extensions=[".test"])

        assert str(os) == "Test OS"


# -----------------------------------------------------------------------------
# Test OperatingSystem Behavior (mocked DB)
# -----------------------------------------------------------------------------


class TestOperatingSystemBehavior:
    """Tests for OperatingSystem model behavior with mocked database access."""

    def test_get_for_extension_finds_os(self):
        """get_for_extension should find OS by extension."""
        from cms.models import OperatingSystem

        test_os = OperatingSystem(
            slug="test-os-ext",
            name="Test OS",
            extensions=[".testmsi", ".testexe"],
        )

        mock_qs = MagicMock()
        mock_qs.__iter__ = lambda self: iter([test_os])

        with patch.object(OperatingSystem.objects, "all", return_value=mock_qs):
            result = OperatingSystem.get_for_extension(".testmsi")
            assert result == test_os

    def test_get_for_extension_handles_missing_dot(self):
        """get_for_extension should work with or without leading dot."""
        from cms.models import OperatingSystem

        test_os = OperatingSystem(
            slug="test-os-nodot",
            name="Test OS",
            extensions=[".nodot"],
        )

        mock_qs = MagicMock()
        mock_qs.__iter__ = lambda self: iter([test_os])

        with patch.object(OperatingSystem.objects, "all", return_value=mock_qs):
            result = OperatingSystem.get_for_extension("nodot")
            assert result == test_os

    def test_get_for_extension_case_insensitive(self):
        """get_for_extension should be case-insensitive."""
        from cms.models import OperatingSystem

        test_os = OperatingSystem(
            slug="test-os-case",
            name="Test OS",
            extensions=[".casemsi"],
        )

        mock_qs = MagicMock()
        mock_qs.__iter__ = lambda self: iter([test_os])

        with patch.object(OperatingSystem.objects, "all", return_value=mock_qs):
            result = OperatingSystem.get_for_extension(".CASEMSI")
            assert result == test_os

    def test_get_for_extension_returns_none_for_unknown(self):
        """get_for_extension should return None for unknown extensions."""
        from cms.models import OperatingSystem

        test_os = OperatingSystem(
            slug="test-os-unknown",
            name="Test OS",
            extensions=[".msi", ".exe"],
        )

        mock_qs = MagicMock()
        mock_qs.__iter__ = lambda self: iter([test_os])

        with patch.object(OperatingSystem.objects, "all", return_value=mock_qs):
            result = OperatingSystem.get_for_extension(".unknown")
            assert result is None

    def test_extensions_defaults_to_empty_list(self):
        """extensions field should default to empty list."""
        from cms.models import OperatingSystem

        os = OperatingSystem(slug="custom", name="Custom OS")
        assert os.extensions == []
