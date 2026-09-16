"""Backfill open concurrent-range quota reservations for live ranges (PLAT-239, #1946).

Enabling an enforcing per-workspace concurrent-range quota immediately after
upgrade must not undercount infrastructure that is already live. Every
pre-existing non-terminal CMS range projection (any status other than
``destroyed``/``failed`` — including ``destroying`` rows still holding provider
resources) gets exactly one open ``WorkspaceQuotaReservation`` keyed on its CMS
request UUID.

This is a CMS-owned data migration that depends on the ``workspaces`` schema
migration, keeping the migration graph acyclic (ADR-046-R10 preflight): the
schema is owned by ``workspaces``; the CMS-derived backfill follows using scalar
correlation only. It reads the unfiltered historical range rows, fails loudly on
inconsistent workspace/request evidence, and is idempotent on re-run.
"""

from __future__ import annotations

from django.db import migrations

_RESOURCE = "concurrent_ranges"
_TERMINAL_STATUSES = frozenset({"destroyed", "failed"})
_CORRELATION_KEY_MAX = 64


def _backfill(apps, schema_editor):
    RangeInstance = apps.get_model("cms", "RangeInstance")
    WorkspaceQuotaReservation = apps.get_model("workspaces", "WorkspaceQuotaReservation")

    # Historical managers are unfiltered, so soft-deleted DESTROYING rows are
    # included; excluding only terminal states leaves every still-live range.
    live = (
        RangeInstance.objects.exclude(status__in=_TERMINAL_STATUSES)
        .filter(workspace_id__isnull=False, request__isnull=False)
        .select_related("request")
    )

    key_to_workspace: dict[str, int] = {}
    for instance in live.iterator():
        request = instance.request
        if request is None or request.request_id is None:
            continue
        key = str(request.request_id)[:_CORRELATION_KEY_MAX]
        workspace_id = instance.workspace_id
        # The CMS Request and RangeInstance carry the same scalar workspace_id by
        # invariant (ADR-046-R3). A singleton row whose two bindings disagree is
        # corrupt evidence; reserve nothing and fail loudly rather than guess.
        if request.workspace_id is not None and request.workspace_id != workspace_id:
            raise RuntimeError(
                f"Inconsistent range workspace evidence for correlation {key}: "
                f"range {workspace_id} vs request {request.workspace_id}"
            )
        existing_workspace = key_to_workspace.get(key)
        if existing_workspace is not None and existing_workspace != workspace_id:
            raise RuntimeError(
                f"Inconsistent range workspace evidence for correlation {key}: "
                f"workspace {existing_workspace} vs {workspace_id}"
            )
        key_to_workspace[key] = workspace_id

    already_reserved = set(
        WorkspaceQuotaReservation.objects.filter(resource=_RESOURCE).values_list("workspace_id", "correlation_key")
    )
    to_create = [
        WorkspaceQuotaReservation(workspace_id=workspace_id, resource=_RESOURCE, correlation_key=key)
        for key, workspace_id in key_to_workspace.items()
        if (workspace_id, key) not in already_reserved
    ]
    if to_create:
        WorkspaceQuotaReservation.objects.bulk_create(to_create, ignore_conflicts=True)


class Migration(migrations.Migration):
    dependencies = [
        ("cms", "0042_remove_legacy_scenario"),
        ("workspaces", "0009_workspacequotadecision_workspacequotapolicy_and_more"),
    ]

    operations = [
        migrations.RunPython(_backfill, migrations.RunPython.noop),
    ]
