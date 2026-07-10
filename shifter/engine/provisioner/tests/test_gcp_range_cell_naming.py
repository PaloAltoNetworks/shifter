"""Tests for GCE range-cell naming/URI/label/tag helpers.

These are pure functions: they normalize scenario values into Compute Engine
resource names/labels and build relative self-links and network tags.
"""

from __future__ import annotations

import pytest

from gcp_range_cell_naming import (
    _disk_type_self_link,
    _label_value,
    _machine_type_self_link,
    _network_name_from_id,
    _network_self_link,
    _network_tag,
    _sanitize_name,
    _short_resource_name,
    _subnet_tag,
    _subnetwork_self_link,
)


class TestSanitizeName:
    def test_lowercases_and_replaces_invalid_chars(self):
        assert _sanitize_name("Polaris Range #1") == "polaris-range-1"

    def test_collapses_and_trims_dashes(self):
        assert _sanitize_name("--a__b--") == "a-b"

    def test_empty_value_falls_back_to_range(self):
        assert _sanitize_name("   ") == "range"

    def test_leading_non_alpha_is_prefixed(self):
        # A name that normalizes to digits must start with a letter (GCE rule).
        assert _sanitize_name("123") == "r-123"

    def test_truncates_to_max_length_without_trailing_dash(self):
        result = _sanitize_name("a" * 70, max_length=10)
        assert result == "a" * 10
        assert len(result) == 10

    def test_truncation_strips_dash_landing_on_boundary(self):
        # Cut lands on a dash; the result must not end with one.
        assert _sanitize_name("ab-cdefgh", max_length=3) == "ab"


class TestLabelValue:
    def test_underscores_are_allowed(self):
        assert _label_value("Role_DC") == "role_dc"

    def test_invalid_chars_replaced_and_trimmed(self):
        assert _label_value(" Kali/Attacker! ") == "kali-attacker"

    def test_empty_falls_back_to_unknown(self):
        assert _label_value("***") == "unknown"

    def test_non_string_is_coerced(self):
        assert _label_value(42) == "42"


class TestShortResourceName:
    def test_joins_prefix_and_parts(self):
        assert _short_resource_name("shifter-range", 42, "polaris") == "shifter-range-42-polaris"

    def test_skips_none_and_empty_parts(self):
        assert _short_resource_name("shifter-r", None, "", "dc01") == "shifter-r-dc01"


class TestSelfLinks:
    def test_network_self_link(self):
        assert _network_self_link("proj", "net") == "projects/proj/global/networks/net"

    def test_subnetwork_self_link(self):
        assert _subnetwork_self_link("proj", "us-central1", "sn") == "projects/proj/regions/us-central1/subnetworks/sn"

    def test_machine_type_self_link(self):
        assert _machine_type_self_link("us-central1-b", "e2-medium") == "zones/us-central1-b/machineTypes/e2-medium"

    def test_disk_type_self_link(self):
        assert _disk_type_self_link("us-central1-b", "pd-balanced") == "zones/us-central1-b/diskTypes/pd-balanced"


class TestNetworkNameFromId:
    @pytest.mark.parametrize(
        "network_id,expected",
        [
            ("net", "net"),
            ("projects/p/global/networks/shared-net", "shared-net"),
            ("https://www.googleapis.com/compute/v1/projects/p/global/networks/n", "n"),
            ("projects/p/global/networks/n/", "n"),
        ],
    )
    def test_extracts_trailing_name(self, network_id, expected):
        assert _network_name_from_id(network_id) == expected


class TestNetworkTags:
    def test_network_tag(self):
        assert _network_tag(42) == "shifter-range-42"

    def test_subnet_tag(self):
        assert _subnet_tag(42, "polaris") == "shifter-range-42-polaris"
