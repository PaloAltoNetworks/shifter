"""Tests for GCP config store helpers."""

from cloud.gcp.base import normalize_parameter_name


class TestNormalizeParameterName:
    """GCP config store normalizes SSM-style paths into secret ids."""

    def test_replaces_slashes_with_double_hyphen(self):
        assert normalize_parameter_name("/shifter/ami/kali") == "shifter--ami--kali"

    def test_trims_empty_edges(self):
        assert normalize_parameter_name("shifter/ami/windows/") == "shifter--ami--windows"
