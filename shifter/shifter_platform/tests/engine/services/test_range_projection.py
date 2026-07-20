"""Unit tests for the pure ``provisioned_instances`` projection helpers.

These functions moved off ``engine.models.Range`` into the services projection
layer (#685). They are pure list traversal — no ORM, no DB — so the tests
build plain instance dicts and assert behaviour matches the former model
methods byte-for-byte (including the empty-uuid ``ValueError``).
"""

from __future__ import annotations

import pytest

from engine.services._common import (
    attacker_instance,
    attacker_private_ip,
    find_instance_by_role,
    find_instance_by_uuid,
    first_victim_private_ip,
    victim_instances,
)

ATTACKER = {"uuid": "a-1", "role": "attacker", "private_ip": "10.1.0.10"}
VICTIM_1 = {"uuid": "v-1", "role": "victim", "private_ip": "10.1.0.20"}
VICTIM_2 = {"uuid": "v-2", "role": "victim", "private_ip": "10.1.0.21"}
INSTANCES = [ATTACKER, VICTIM_1, VICTIM_2]


class TestFindInstanceByRole:
    def test_returns_matching_instance(self):
        assert find_instance_by_role(INSTANCES, "attacker") is ATTACKER

    def test_returns_first_match(self):
        assert find_instance_by_role(INSTANCES, "victim") is VICTIM_1

    def test_returns_none_when_absent(self):
        assert find_instance_by_role(INSTANCES, "dc") is None

    def test_returns_none_for_empty(self):
        assert find_instance_by_role(None, "attacker") is None
        assert find_instance_by_role([], "attacker") is None


class TestFindInstanceByUuid:
    def test_returns_matching_instance(self):
        assert find_instance_by_uuid(INSTANCES, "v-2") is VICTIM_2

    def test_returns_none_when_absent(self):
        assert find_instance_by_uuid(INSTANCES, "missing") is None

    def test_returns_none_for_empty(self):
        assert find_instance_by_uuid(None, "a-1") is None
        assert find_instance_by_uuid([], "a-1") is None

    def test_raises_on_empty_uuid(self):
        with pytest.raises(ValueError, match="uuid is required"):
            find_instance_by_uuid(INSTANCES, "")

    def test_raises_on_none_uuid(self):
        with pytest.raises(ValueError, match="uuid is required"):
            find_instance_by_uuid(INSTANCES, None)


class TestAttackerInstance:
    def test_returns_attacker(self):
        assert attacker_instance(INSTANCES) is ATTACKER

    def test_returns_none_when_no_attacker(self):
        assert attacker_instance([VICTIM_1]) is None

    def test_returns_none_for_empty(self):
        assert attacker_instance(None) is None


class TestVictimInstances:
    def test_returns_all_victims(self):
        assert victim_instances(INSTANCES) == [VICTIM_1, VICTIM_2]

    def test_returns_empty_when_no_victims(self):
        assert victim_instances([ATTACKER]) == []

    def test_returns_empty_for_empty(self):
        assert victim_instances(None) == []


class TestPrivateIpProjections:
    def test_attacker_private_ip(self):
        assert attacker_private_ip(INSTANCES) == "10.1.0.10"

    def test_attacker_private_ip_none_when_no_attacker(self):
        assert attacker_private_ip([VICTIM_1]) is None

    def test_attacker_private_ip_none_when_missing_field(self):
        assert attacker_private_ip([{"role": "attacker"}]) is None

    def test_first_victim_private_ip(self):
        assert first_victim_private_ip(INSTANCES) == "10.1.0.20"

    def test_first_victim_private_ip_none_when_no_victims(self):
        assert first_victim_private_ip([ATTACKER]) is None
