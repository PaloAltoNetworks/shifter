"""Delivery-engine metrics: fail-soft emission and closed low-cardinality labels.

Covers issue #2098 (CTF-008): a metrics outage never raises (delivery truth is
never affected), and an out-of-set label value is dropped rather than emitted.
"""

from __future__ import annotations

import pytest
from django.utils import timezone

from ctf.services.communication import metrics
from ctf.services.communication.delivery import DeliveryRunStats


class _RaisingClient:
    def put_metric_data(self, **kwargs: object) -> object:
        raise RuntimeError("cloudwatch unavailable")


class _CapturingClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def put_metric_data(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return None


def test_admission_denied_drops_an_unknown_scope_class():
    # An out-of-set scope value must never become an unbounded metric label.
    client = _CapturingClient()
    assert metrics.emit_admission_denied(scope_class="not-a-real-scope", client=client) is False
    assert client.calls == []  # dropped entirely, never published under a bogus label


def test_admission_denied_emits_a_closed_scope():
    client = _CapturingClient()
    assert metrics.emit_admission_denied(scope_class="workspace", client=client) is True
    dims = client.calls[0]["MetricData"][0]["Dimensions"]
    assert {"Name": "ScopeClass", "Value": "workspace"} in dims


def test_worker_metrics_are_fail_soft(db):
    # A publisher outage returns False and never raises out of the worker path.
    stats = DeliveryRunStats(claimed=1, accepted=1)
    assert metrics.emit_worker_run(stats, now_func=timezone.now, client=_RaisingClient()) is False


def test_backlog_gauges_emit_oldest_due_age(db):
    client = _CapturingClient()
    assert metrics.emit_backlog_gauges(now_func=timezone.now, client=client) is True
    names = {entry["MetricName"] for call in client.calls for entry in call["MetricData"]}
    assert "OldestDueAgeSeconds" in names


def test_backlog_gauges_report_per_channel_depth(organizer_user, ctf_event):
    # A real QUEUED command exercises the per-channel BacklogDepth loop (not just
    # the always-emitted oldest-due gauge on an empty table).
    import workspaces.services as workspace_services
    from ctf.enums import ParticipantStatus
    from ctf.models import CTFParticipant
    from ctf.services.communication import CampaignDraft, create_campaign, release_campaign

    CTFParticipant.objects.create(
        event=ctf_event,
        email="a@test.com",
        name="a",
        status=ParticipantStatus.ACTIVE.value,
        registered_at=timezone.now(),
    )
    workspace_uuid = str(workspace_services.resolve_personal_workspace(organizer_user).workspace_uuid)
    draft = CampaignDraft(
        title="Kickoff",
        origin="organizer_staff",
        target_event_ids=[ctf_event.id],
        audience_spec={"kind": "event", "event_ids": [str(ctf_event.id)]},
        trigger_spec={"kind": "manual"},
        channels=["in_app"],
        subject="Welcome",
        body="See the [rules](/rules).",
    )
    campaign = create_campaign(organizer_user, workspace_uuid, draft)
    release_campaign(campaign, occurrence_key="occ", actor_user_id=organizer_user.id)

    client = _CapturingClient()
    assert metrics.emit_backlog_gauges(now_func=timezone.now, client=client) is True
    backlog = [entry for call in client.calls for entry in call["MetricData"] if entry["MetricName"] == "BacklogDepth"]
    assert any(
        {"Name": "Channel", "Value": "in_app"} in entry["Dimensions"] and entry["Value"] >= 1.0 for entry in backlog
    )


def test_resolve_client_selects_aws(settings, monkeypatch):
    settings.CLOUD_PROVIDER = "aws"
    import boto3

    monkeypatch.setattr(boto3, "client", lambda name: f"boto-{name}")
    assert metrics._resolve_client() == "boto-cloudwatch"


def test_resolve_client_selects_gcp(settings):
    settings.CLOUD_PROVIDER = "gcp"
    assert isinstance(metrics._resolve_client(), metrics._GcpMonitoringPublisher)


def test_resolve_client_rejects_unknown_provider(settings):
    settings.CLOUD_PROVIDER = "azure"
    with pytest.raises(RuntimeError):
        metrics._resolve_client()


def test_gcp_publisher_writes_a_time_series(monkeypatch):
    captured: dict[str, object] = {}

    class _FakeClient:
        def create_time_series(self, *, name, time_series):
            captured["name"] = name
            captured["series"] = list(time_series)

    from google.cloud import monitoring_v3

    monkeypatch.setattr(monitoring_v3, "MetricServiceClient", lambda: _FakeClient())
    monkeypatch.setattr("shared.cloud.gcp.base.get_project_id", lambda: "proj-1")

    metrics._GcpMonitoringPublisher().put_metric_data(
        Namespace="Shifter/CtfCommunication",
        MetricData=[
            {
                "MetricName": "BacklogDepth",
                "Dimensions": [{"Name": "Channel", "Value": "in_app"}],
                "Value": 3.0,
                "Unit": "Count",
            }
        ],
    )

    assert captured["name"] == "projects/proj-1"
    assert len(captured["series"]) == 1
