from __future__ import annotations

from django.db import migrations

_RETIRED_PLAN_KIND = "aces_provisioning_plan"
_RETIRED_RESOURCE = "aces-range"
_RETIRED_EVENT_TYPES = ("range.aces.operation", "range.aces.snapshot")
_TERMINAL_RANGE_STATUSES = ("destroyed", "failed")
_TERMINAL_LAUNCH_STATUSES = ("SUCCEEDED", "DLQ")
_TERMINAL_OUTBOX_STATUSES = ("PUBLISHED", "DLQ")


def _retired_work_blockers(apps) -> dict[str, int]:
    range_model = apps.get_model("engine", "Range")
    instance_model = apps.get_model("engine", "Instance")
    launch_intent = apps.get_model("engine", "ProvisionerLaunchIntent")
    result_inbox = apps.get_model("engine", "OperationResultInbox")
    event_outbox = apps.get_model("engine", "RangeEventOutbox")

    return {
        "ranges": range_model.objects.filter(range_config__kind=_RETIRED_PLAN_KIND)
        .exclude(status__in=_TERMINAL_RANGE_STATUSES)
        .count(),
        "instances": instance_model.objects.filter(
            provisioner_operation__startswith=f"{_RETIRED_RESOURCE}:",
        )
        .exclude(status__in=_TERMINAL_RANGE_STATUSES)
        .count(),
        "launch intents": launch_intent.objects.filter(payload__resource=_RETIRED_RESOURCE)
        .exclude(status__in=_TERMINAL_LAUNCH_STATUSES)
        .count(),
        "operation results": result_inbox.objects.filter(
            resource=_RETIRED_RESOURCE,
            disposition="PENDING",
        ).count(),
        "range events": event_outbox.objects.filter(event_type__in=_RETIRED_EVENT_TYPES)
        .exclude(status__in=_TERMINAL_OUTBOX_STATUSES)
        .count(),
    }


def _forward_cleanup(apps, schema_editor) -> None:
    blockers = _retired_work_blockers(apps)
    active = [f"{count} {surface}" for surface, count in blockers.items() if count]
    if active:
        raise RuntimeError(
            "RAES hard cutover requires all retired provisioning work to be drained; " + ", ".join(active)
        )

    apps.get_model("cms", "RaesPackageSource").objects.exclude(contract_kind="raes").delete()
    apps.get_model("shared", "RaesOperationRecord").objects.exclude(contract_kind="raes").delete()
    apps.get_model("shared", "RaesParticipantRuntimeRecord").objects.exclude(contract_kind="raes").delete()


def _reverse_cleanup(apps, schema_editor) -> None:
    apps.get_model("cms", "RaesPackageSource").objects.exclude(contract_kind="aces").delete()
    apps.get_model("shared", "RaesOperationRecord").objects.exclude(contract_kind="aces").delete()
    apps.get_model("shared", "RaesParticipantRuntimeRecord").objects.exclude(contract_kind="aces").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("cms", "0041_raes_hard_cutover"),
        ("engine", "0048_raes_hard_cutover"),
        ("shared", "0008_raes_hard_cutover"),
    ]

    operations = [
        migrations.RunPython(_forward_cleanup, _reverse_cleanup),
    ]
