"""Tests for the run_aces_backend_validation management command (#1264).

Covers the flag gate, scenario requirement, and the launch -> wait -> validate ->
teardown orchestration (with the launch/status/evidence seams mocked so no real
provisioning runs). The evidence collector itself is tested in
tests/cms/aces/test_validation.py.
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from cms.aces.validation import AcesEvidenceSummary
from shared.enums import ResourceStatus

_CMD = "run_aces_backend_validation"
_MOD = "cms.management.commands.run_aces_backend_validation"


@pytest.fixture
def smoke_env(monkeypatch):
    monkeypatch.setenv("SMOKE_TEST_USER_EMAIL", "aces-validation@example.com")


@pytest.fixture
def native_on(settings):
    settings.ACES_NATIVE_PROVISIONING_ENABLED = True


def _valid_summary(request_id):
    return AcesEvidenceSummary(
        request_id=request_id,
        receipt_count=1,
        status_count=2,
        snapshot_count=1,
        has_succeeded_status=True,
        snapshot_resource_count=2,
    )


def _mock_launch_ready(monkeypatch, request_id, torn):
    monkeypatch.setattr(
        "cms.services.create_range_dispatch",
        lambda user, scenario, agents, range_source=None: SimpleNamespace(request_id=request_id),
    )
    monkeypatch.setattr("cms.services.find_range_instance_id_by_request", lambda r: 5)
    monkeypatch.setattr("cms.services.get_range_status_by_id", lambda pk: ResourceStatus.READY.value)
    monkeypatch.setattr("cms.services.destroy_range_by_request_id", lambda user, r: torn.setdefault("rid", r))


@pytest.mark.django_db
def test_flag_off_refuses(settings, smoke_env):
    settings.ACES_NATIVE_PROVISIONING_ENABLED = False
    with pytest.raises(CommandError):
        call_command(_CMD, "--scenario", "aces-x")


@pytest.mark.django_db
def test_missing_scenario_refuses(native_on, smoke_env):
    with pytest.raises(CommandError):
        call_command(_CMD)


@pytest.mark.django_db
def test_happy_path_launches_validates_and_tears_down(native_on, smoke_env, monkeypatch):
    request_id = uuid4()
    torn: dict = {}
    _mock_launch_ready(monkeypatch, request_id, torn)
    monkeypatch.setattr(f"{_MOD}.collect_evidence", lambda r: _valid_summary(str(request_id)))
    monkeypatch.setattr(f"{_MOD}.validate_evidence", lambda s: [])

    call_command(_CMD, "--scenario", "aces-x", "--poll-interval", "0")
    assert torn["rid"] == str(request_id)


@pytest.mark.django_db
def test_incomplete_evidence_fails_but_still_tears_down(native_on, smoke_env, monkeypatch):
    request_id = uuid4()
    torn: dict = {}
    _mock_launch_ready(monkeypatch, request_id, torn)
    monkeypatch.setattr(f"{_MOD}.collect_evidence", lambda r: _valid_summary(str(request_id)))
    monkeypatch.setattr(
        f"{_MOD}.validate_evidence", lambda s: ["runtime_snapshot recorded no realized resources (vacuous)"]
    )

    with pytest.raises(CommandError):
        call_command(_CMD, "--scenario", "aces-x", "--poll-interval", "0")
    assert torn["rid"] == str(request_id)


@pytest.mark.django_db
def test_keep_flag_skips_teardown(native_on, smoke_env, monkeypatch):
    request_id = uuid4()
    torn: dict = {}
    _mock_launch_ready(monkeypatch, request_id, torn)
    monkeypatch.setattr(f"{_MOD}.collect_evidence", lambda r: _valid_summary(str(request_id)))
    monkeypatch.setattr(f"{_MOD}.validate_evidence", lambda s: [])

    call_command(_CMD, "--scenario", "aces-x", "--poll-interval", "0", "--keep")
    assert "rid" not in torn
