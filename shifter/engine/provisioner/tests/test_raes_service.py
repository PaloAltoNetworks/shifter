"""Tests for authored-service -> plan projection extraction (ADR-031, ADR-032, ADR-032-R8).

Security-critical fail-closed parsing of ``spec.node.services`` at the provisioner
trust boundary: verifies protocol normalization (tcp default, udp preserved, unknown
rejected -- never coerced), concrete integer port validation (bool/float/str/zero/
out-of-range rejected), non-sequence and non-mapping rejection, and duplicate-binding
rejection. A malformed service must raise rather than be silently dropped or widened.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from raes_plan import RaesPlanServicePort  # re-exported from raes_plan
from raes_plan_types import RaesPlanError
from raes_service import build_node_services


class TestHappyPath:
    def test_valid_services_build_value_objects(self):
        services = build_node_services(
            [
                {"port": 80, "name": "http", "protocol": "tcp"},
                {"port": 53, "protocol": "udp", "name": "dns"},
            ]
        )
        assert services == (
            RaesPlanServicePort(port=80, protocol="tcp", name="http"),
            RaesPlanServicePort(port=53, protocol="udp", name="dns"),
        )

    def test_protocol_defaults_to_tcp_when_omitted(self):
        (service,) = build_node_services([{"port": 8080, "name": "web"}])
        assert service.protocol == "tcp"

    def test_protocol_defaults_to_tcp_when_blank(self):
        (service,) = build_node_services([{"port": 8080, "protocol": ""}])
        assert service.protocol == "tcp"

    def test_udp_is_preserved(self):
        (service,) = build_node_services([{"port": 53, "protocol": "UDP"}])
        assert service.protocol == "udp"

    def test_name_optional_defaults_empty(self):
        (service,) = build_node_services([{"port": 22}])
        assert service.name == ""

    def test_author_order_preserved(self):
        services = build_node_services([{"port": 3}, {"port": 1}, {"port": 2}])
        assert [s.port for s in services] == [3, 1, 2]


class TestAbsentAndMalformedContainer:
    def test_absent_services_yield_empty(self):
        assert build_node_services(None) == ()

    def test_empty_list_yields_empty(self):
        assert build_node_services([]) == ()

    @pytest.mark.parametrize("bad", [{"port": 80}, "80", 80, True])
    def test_non_sequence_services_fail_closed(self, bad):
        with pytest.raises(RaesPlanError, match="sequence"):
            build_node_services(bad)

    def test_non_mapping_entry_fails_closed(self):
        with pytest.raises(RaesPlanError, match="not an object"):
            build_node_services([80])


class TestPortValidation:
    @pytest.mark.parametrize("port", [True, False, 1.5, "22", None, 0, -1, 65536, 100000])
    def test_invalid_ports_fail_closed(self, port):
        with pytest.raises(RaesPlanError, match="port"):
            build_node_services([{"port": port}])

    def test_boundary_ports_accepted(self):
        services = build_node_services([{"port": 1, "protocol": "tcp"}, {"port": 65535, "protocol": "tcp"}])
        assert [s.port for s in services] == [1, 65535]


class TestProtocolValidation:
    @pytest.mark.parametrize("protocol", ["icmp", "all", "any", "sctp", "http"])
    def test_unknown_protocol_fails_closed_not_coerced(self, protocol):
        with pytest.raises(RaesPlanError, match="protocol"):
            build_node_services([{"port": 80, "protocol": protocol}])

    def test_non_string_protocol_fails_closed(self):
        with pytest.raises(RaesPlanError, match="protocol"):
            build_node_services([{"port": 80, "protocol": 6}])


class TestDuplicateBindings:
    def test_duplicate_protocol_port_fails_closed(self):
        with pytest.raises(RaesPlanError, match="duplicate"):
            build_node_services([{"port": 80, "protocol": "tcp"}, {"port": 80, "protocol": "tcp", "name": "other"}])

    def test_same_port_different_protocol_is_allowed(self):
        services = build_node_services([{"port": 53, "protocol": "tcp"}, {"port": 53, "protocol": "udp"}])
        assert len(services) == 2


class TestNameValidation:
    def test_non_string_name_fails_closed(self):
        with pytest.raises(RaesPlanError, match="name"):
            build_node_services([{"port": 80, "name": 123}])

    def test_over_long_name_fails_closed(self):
        with pytest.raises(RaesPlanError, match="name"):
            build_node_services([{"port": 80, "name": "x" * 65}])

    def test_name_at_bound_is_accepted_and_stripped(self):
        (service,) = build_node_services([{"port": 80, "name": "  " + "x" * 64 + "  "}])
        assert service.name == "x" * 64


class TestBoundedDiagnostics:
    """ADR-032-R8: boundary errors name the field/index, never the raw authored value."""

    @pytest.mark.parametrize(
        "bad_service",
        [
            {"port": 10**9},  # unbounded int not echoed
            {"port": 80, "protocol": "x" * 200},  # hostile protocol string not echoed
            {"port": 80, "name": "y" * 200},  # hostile name not echoed
        ],
    )
    def test_error_message_does_not_echo_raw_value(self, bad_service):
        with pytest.raises(RaesPlanError) as exc:
            build_node_services([bad_service])
        message = str(exc.value)
        for raw in ("1000000000", "x" * 200, "y" * 200):
            assert raw not in message
