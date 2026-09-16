"""Unit tests for the persisted range_config RAES discriminator (#1310).

``is_raes_provisioning_plan`` decides RAES-vs-legacy lifecycle from the persisted,
validated ``range_config.kind`` (ADR-031-R6). It positively identifies an RAES
plan and treats everything else -- ``None``, an empty dict, a cyberscript
wrapped-spec envelope, an unknown ``kind``, or a non-dict -- as legacy.
"""

from __future__ import annotations

from shared.raes.runtime_target import RAES_PROVISIONING_PLAN_KIND, is_raes_provisioning_plan


def test_identifies_raes_plan():
    assert is_raes_provisioning_plan({"kind": RAES_PROVISIONING_PLAN_KIND}) is True
    assert is_raes_provisioning_plan({"kind": RAES_PROVISIONING_PLAN_KIND, "resources": {}}) is True


def test_treats_non_raes_as_legacy():
    assert is_raes_provisioning_plan(None) is False
    assert is_raes_provisioning_plan({}) is False
    assert is_raes_provisioning_plan({"spec_schema": "range_spec", "payload": {}}) is False
    assert is_raes_provisioning_plan({"kind": "something_else"}) is False
    assert is_raes_provisioning_plan("not-a-dict") is False
