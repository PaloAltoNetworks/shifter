"""Contract tests for the synchronous subnet-coordination boundary (#1838).

ADR-043-R6. The coordination request crosses a process boundary into a
privileged database routine, so every bound here is a real trust boundary: a
dataclass field, a type hint, or a SQL cast is not validation.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from shared.subnet_coordination import (
    ACCEPTED_COORDINATION_VERSIONS,
    COORDINATION_CONTRACT_VERSION,
    MAX_OBSERVED_CIDRS,
    MAX_SUBNET_COUNT,
    SUPPORTED_PREFIX_LENGTHS,
    SubnetCoordinationError,
    build_reservation_request,
    parse_reservation_result,
    reservation_shape_fingerprint,
)

OID = str(uuid4())
RID = str(uuid4())


def _request(**overrides):
    base = {
        "operation_id": OID,
        "request_id": RID,
        "network_id": "range-network-test",
        "network_cidr": "10.1.0.0/16",
        "prefix_length": 28,
        "subnets": ["0:attack", "1:victim", "2:dmz"],
        "observed_cidrs": ["10.1.2.0/28"],
    }
    base.update(overrides)
    return base


class TestBuildReservationRequest:
    def test_round_trips_a_valid_request(self):
        req = build_reservation_request(**_request())

        assert req.contract_version == COORDINATION_CONTRACT_VERSION
        assert COORDINATION_CONTRACT_VERSION in ACCEPTED_COORDINATION_VERSIONS
        assert req.operation_id == OID
        assert req.request_id == RID
        assert req.network_cidr == "10.1.0.0/16"
        assert req.prefix_length == 28
        assert req.subnet_count == 3
        assert req.subnets == ("0:attack", "1:victim", "2:dmz")
        assert req.shape_fingerprint.startswith("sha256:")
        assert req.observed_cidrs == ("10.1.2.0/28",)

    def test_normalizes_uuid_objects(self):
        req = build_reservation_request(**_request(operation_id=uuid4(), request_id=uuid4()))

        assert isinstance(req.operation_id, str)
        assert isinstance(req.request_id, str)

    def test_rejects_a_non_uuid_operation_id(self):
        candidate = _request(operation_id="not-a-uuid")

        with pytest.raises(SubnetCoordinationError):
            build_reservation_request(**candidate)

    def test_rejects_a_missing_operation_id(self):
        # Fail closed: the preflight forbids a missing-operation fallback, so an
        # absent generation must not silently reserve untracked capacity.
        candidate = _request(operation_id=None)

        with pytest.raises(SubnetCoordinationError):
            build_reservation_request(**candidate)

    def test_rejects_an_unsupported_prefix_length(self):
        assert 26 not in SUPPORTED_PREFIX_LENGTHS
        candidate = _request(prefix_length=26)

        with pytest.raises(SubnetCoordinationError):
            build_reservation_request(**candidate)

    def test_rejects_an_empty_subnet_list(self):
        candidate = _request(subnets=[])

        with pytest.raises(SubnetCoordinationError):
            build_reservation_request(**candidate)

    def test_rejects_an_oversized_subnet_list(self):
        candidate = _request(subnets=[f"{i}:s" for i in range(MAX_SUBNET_COUNT + 1)])

        with pytest.raises(SubnetCoordinationError):
            build_reservation_request(**candidate)

    def test_rejects_duplicate_subnet_identities(self):
        candidate = _request(subnets=["0:attack", "0:attack"])

        with pytest.raises(SubnetCoordinationError):
            build_reservation_request(**candidate)

    def test_rejects_control_characters_in_a_subnet_identity(self):
        # The fingerprint is newline-separated, so a label carrying one could
        # forge a field boundary and collide with a different request shape.
        candidate = _request(subnets=["0:attack\n1:victim", "2:dmz"])

        with pytest.raises(SubnetCoordinationError):
            build_reservation_request(**candidate)

    def test_rejects_an_empty_network_id(self):
        candidate = _request(network_id="")

        with pytest.raises(SubnetCoordinationError):
            build_reservation_request(**candidate)

    def test_rejects_a_non_canonical_network_cidr(self):
        # 10.1.0.1/16 has host bits set; accepting it would let the routine
        # derive candidates from a network the caller never actually named.
        candidate = _request(network_cidr="10.1.0.1/16")

        with pytest.raises(SubnetCoordinationError):
            build_reservation_request(**candidate)

    def test_rejects_a_non_ipv4_network_cidr(self):
        candidate = _request(network_cidr="2001:db8::/32")

        with pytest.raises(SubnetCoordinationError):
            build_reservation_request(**candidate)

    def test_rejects_a_prefix_length_shorter_than_the_network(self):
        # A /28 request inside a /28 network is fine; a /24 request inside a /28
        # network cannot be satisfied and must fail at the contract, not by
        # returning an empty batch.
        candidate = _request(network_cidr="10.1.2.0/28", prefix_length=24)

        with pytest.raises(SubnetCoordinationError):
            build_reservation_request(**candidate)

    def test_rejects_a_malformed_observation(self):
        # Malformed observations fail closed rather than being skipped: silently
        # dropping one would let the allocator hand out a CIDR the provider is
        # already using.
        candidate = _request(observed_cidrs=["10.1.2.0/28", "not-a-cidr"])

        with pytest.raises(SubnetCoordinationError):
            build_reservation_request(**candidate)

    def test_rejects_too_many_observations(self):
        candidate = _request(
            observed_cidrs=[f"10.1.{i // 16}.{(i % 16) * 16}/28" for i in range(MAX_OBSERVED_CIDRS + 1)]
        )

        with pytest.raises(SubnetCoordinationError):
            build_reservation_request(**candidate)

    def test_accepts_no_observations(self):
        req = build_reservation_request(**_request(observed_cidrs=[]))

        assert req.observed_cidrs == ()

    def test_rejects_leading_zero_octets(self):
        # "010.1.2.0" is ambiguous (octal or decimal), so it is rejected rather
        # than normalized -- guessing an interpretation here would decide which
        # network the allocator treats as occupied.
        candidate = _request(observed_cidrs=["010.001.002.000/28"])

        with pytest.raises(SubnetCoordinationError):
            build_reservation_request(**candidate)

    def test_deduplicates_observations(self):
        req = build_reservation_request(**_request(observed_cidrs=["10.1.2.0/28", "10.1.2.0/28"]))

        assert req.observed_cidrs == ("10.1.2.0/28",)

    def test_orders_observations_independently_of_provider_listing_order(self):
        forward = build_reservation_request(**_request(observed_cidrs=["10.1.2.0/28", "10.1.3.0/28"]))
        reverse = build_reservation_request(**_request(observed_cidrs=["10.1.3.0/28", "10.1.2.0/28"]))

        assert forward.observed_cidrs == reverse.observed_cidrs


class TestParseReservationResult:
    def test_returns_cidrs_in_ordinal_order(self):
        rows = [(2, "10.1.2.16/28"), (1, "10.1.2.0/28")]

        assert parse_reservation_result(rows, expected_count=2) == ("10.1.2.0/28", "10.1.2.16/28")

    def test_rejects_a_short_batch(self):
        # A reservation batch is all-or-nothing; a partial result must never be
        # mistaken for a satisfied request.
        with pytest.raises(SubnetCoordinationError):
            parse_reservation_result([(1, "10.1.2.0/28")], expected_count=2)

    def test_rejects_a_long_batch(self):
        rows = [(1, "10.1.2.0/28"), (2, "10.1.2.16/28")]
        with pytest.raises(SubnetCoordinationError):
            parse_reservation_result(rows, expected_count=1)

    def test_rejects_non_contiguous_ordinals(self):
        rows = [(1, "10.1.2.0/28"), (3, "10.1.2.16/28")]
        with pytest.raises(SubnetCoordinationError):
            parse_reservation_result(rows, expected_count=2)

    def test_rejects_duplicate_ordinals(self):
        rows = [(1, "10.1.2.0/28"), (1, "10.1.2.16/28")]
        with pytest.raises(SubnetCoordinationError):
            parse_reservation_result(rows, expected_count=2)

    def test_rejects_a_duplicate_cidr(self):
        rows = [(1, "10.1.2.0/28"), (2, "10.1.2.0/28")]
        with pytest.raises(SubnetCoordinationError):
            parse_reservation_result(rows, expected_count=2)

    def test_rejects_a_malformed_cidr(self):
        with pytest.raises(SubnetCoordinationError):
            parse_reservation_result([(1, "not-a-cidr")], expected_count=1)


class TestReservationShapeFingerprint:
    """The fingerprint is what makes a retry provably the *same* request."""

    def _fingerprint(self, **overrides):
        base = {
            "network_id": "range-network-test",
            "network_cidr": "10.1.0.0/16",
            "prefix_length": 28,
            "subnets": ("0:attack", "1:victim"),
        }
        base.update(overrides)
        return reservation_shape_fingerprint(**base)

    def test_is_stable_for_an_identical_request(self):
        first = self._fingerprint()
        second = self._fingerprint()

        assert first == second

    def test_changes_with_the_base_network_cidr(self):
        # Same count, different base network: returning the first batch here
        # would hand subnets CIDRs outside the network they were asked for.
        assert self._fingerprint() != self._fingerprint(network_cidr="10.9.0.0/16")

    def test_changes_with_the_network_identifier(self):
        assert self._fingerprint() != self._fingerprint(network_id="range-network-other")

    def test_changes_with_the_prefix_length(self):
        assert self._fingerprint() != self._fingerprint(prefix_length=24)

    def test_changes_when_authored_subnets_are_reordered(self):
        # Position binds an authored subnet to its CIDR, so a reordered spec is a
        # different realization even though every element is the same.
        assert self._fingerprint() != self._fingerprint(subnets=("1:victim", "0:attack"))

    def test_changes_when_a_subnet_is_renamed(self):
        assert self._fingerprint() != self._fingerprint(subnets=("0:attack", "1:dmz"))

    def test_changes_with_the_subnet_count(self):
        assert self._fingerprint() != self._fingerprint(subnets=("0:attack", "1:victim", "2:dmz"))

    def test_matches_the_fingerprint_the_request_builder_computes(self):
        request = build_reservation_request(
            operation_id=OID,
            request_id=RID,
            network_id="range-network-test",
            network_cidr="10.1.0.0/16",
            prefix_length=28,
            subnets=["0:attack", "1:victim"],
        )

        assert request.shape_fingerprint == self._fingerprint()
