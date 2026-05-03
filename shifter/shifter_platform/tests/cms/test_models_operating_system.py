"""Tests for CMS OperatingSystem model.

These tests verify the OperatingSystem model is:
- Importable from cms.models
- Has correct fields (slug, name, extensions)
- Has proper methods (get_for_extension)
- Has correct meta options (ordering, verbose_name)

Lookup logic is now layered:
- ``normalize_file_extension`` (pure) handles dot/case normalisation.
- ``OperatingSystemQuerySet.for_extension`` does the iteration; tested
  with a manually-constructed iterable so DB access isn't needed.
- ``OperatingSystem.get_for_extension`` is a thin wrapper around the
  queryset method and is verified via a delegation assertion.
"""

from unittest.mock import patch

from django.db import models

from cms.models.catalogs import (
    OperatingSystemQuerySet,
    normalize_file_extension,
)

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
# Pure normalization
# -----------------------------------------------------------------------------


class TestNormalizeFileExtension:
    """``normalize_file_extension`` is pure; no DB or model setup needed."""

    def test_lowercases_uppercase(self):
        assert normalize_file_extension(".MSI") == ".msi"

    def test_adds_leading_dot_when_missing(self):
        assert normalize_file_extension("msi") == ".msi"

    def test_already_normalized_is_idempotent(self):
        assert normalize_file_extension(".msi") == ".msi"

    def test_uppercase_without_dot(self):
        assert normalize_file_extension("EXE") == ".exe"


# -----------------------------------------------------------------------------
# Queryset lookup (no DB; iterates a fake queryset)
# -----------------------------------------------------------------------------


class _FakeOperatingSystemQuerySet(OperatingSystemQuerySet):
    """Concrete queryset stand-in that iterates over a supplied list.

    Lets us exercise ``for_extension`` without standing up the database
    and without relying on Django's lazy queryset machinery.
    """

    def __init__(self, rows):
        self._rows = list(rows)

    def __iter__(self):
        return iter(self._rows)


class TestOperatingSystemQuerySetForExtension:
    """Behavior of ``OperatingSystemQuerySet.for_extension``."""

    def test_finds_matching_extension(self):
        from cms.models import OperatingSystem

        test_os = OperatingSystem(
            slug="test-os-ext",
            name="Test OS",
            extensions=[".testmsi", ".testexe"],
        )
        qs = _FakeOperatingSystemQuerySet([test_os])

        assert qs.for_extension(".testmsi") is test_os

    def test_handles_missing_leading_dot(self):
        from cms.models import OperatingSystem

        test_os = OperatingSystem(
            slug="test-os-nodot",
            name="Test OS",
            extensions=[".nodot"],
        )
        qs = _FakeOperatingSystemQuerySet([test_os])

        assert qs.for_extension("nodot") is test_os

    def test_is_case_insensitive(self):
        from cms.models import OperatingSystem

        test_os = OperatingSystem(
            slug="test-os-case",
            name="Test OS",
            extensions=[".casemsi"],
        )
        qs = _FakeOperatingSystemQuerySet([test_os])

        assert qs.for_extension(".CASEMSI") is test_os

    def test_returns_none_for_unknown_extension(self):
        from cms.models import OperatingSystem

        test_os = OperatingSystem(
            slug="test-os-unknown",
            name="Test OS",
            extensions=[".msi", ".exe"],
        )
        qs = _FakeOperatingSystemQuerySet([test_os])

        assert qs.for_extension(".unknown") is None


# -----------------------------------------------------------------------------
# get_for_extension wrapper delegates to the queryset method
# -----------------------------------------------------------------------------


class TestGetForExtensionWrapper:
    """``OperatingSystem.get_for_extension`` delegates to the queryset method."""

    def test_delegates_to_objects_for_extension(self):
        from cms.models import OperatingSystem

        sentinel = object()
        with patch.object(OperatingSystem.objects, "for_extension", return_value=sentinel) as mock_method:
            result = OperatingSystem.get_for_extension(".testmsi")

            assert result is sentinel
            mock_method.assert_called_once_with(".testmsi")


# -----------------------------------------------------------------------------
# Other model behavior
# -----------------------------------------------------------------------------


class TestOperatingSystemDefaults:
    """Misc. defaults verified without DB access."""

    def test_extensions_defaults_to_empty_list(self):
        """extensions field should default to empty list."""
        from cms.models import OperatingSystem

        os = OperatingSystem(slug="custom", name="Custom OS")
        assert os.extensions == []
