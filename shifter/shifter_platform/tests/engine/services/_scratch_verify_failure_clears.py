from __future__ import annotations

import pytest

import engine.launch_intents as launch_intents_mod

pytestmark = pytest.mark.django_db


def test_failure_test_passes_even_if_operation_id_never_cleared(monkeypatch):
    # If clear_provisioner_operation_after_failure were broken to a no-op, the
    # existing failure test should still pass, because it never asserts on
    # provisioner_operation_id. It's imported inside _apply_failure at call
    # time (`from engine.launch_intents import ...`), so patch the source.
    monkeypatch.setattr(launch_intents_mod, "clear_provisioner_operation_after_failure", lambda row: [])
    from tests.engine.services.test_operation_apply_domain import TestTerminalTransition

    TestTerminalTransition().test_failure_carries_only_the_authored_reason_code()
