"""Data migration: bind existing CMS request/range rows to a workspace (#1325).

ADR-046-R3/R4. CMS request intent and the CMS range projection are two of the
three ownership projections a range carries; this migration gives both the
workspace scope of their existing owner, so nothing changes hands.

Before writing anything it proves the historical ownership evidence is
consistent -- the range projection agrees with its request, and CMS agrees with
Engine about who owns a range. Divergent evidence stops the migration loudly
(ADR-046-R4): guessing a tenant would silently place someone else's range in the
wrong scope, and that is not a decision a migration gets to make. Diagnostics
name the row, never the account's email or credentials.

Only unbound rows are filled; an existing scope is never rewritten.
"""

from django.db import migrations


def _personal_workspace_ids(workspace_model) -> dict[int, int]:
    """Map user id -> personal workspace id for every user that has one."""
    return dict(
        workspace_model.objects.filter(personal_for_user__isnull=False).values_list("personal_for_user_id", "id")
    )


def _assert_projection_agrees_with_request(range_instance_model) -> None:
    """Fail when a range projection's owner disagrees with its own request."""
    rows = range_instance_model.objects.filter(request__isnull=False).values_list("id", "user_id", "request__user_id")
    for instance_id, instance_user_id, request_user_id in rows:
        if instance_user_id != request_user_id:
            msg = (
                f"CMS range projection {instance_id} is owned by user {instance_user_id} but its request is "
                f"owned by user {request_user_id}. Resolve the ownership divergence before migrating (#1325)."
            )
            raise RuntimeError(msg)


def _assert_cms_agrees_with_engine(request_model, engine_range_model) -> None:
    """Fail when CMS and Engine disagree about who owns the same range."""
    cms_owner_by_request = dict(request_model.objects.values_list("request_id", "user_id"))
    if not cms_owner_by_request:
        return
    rows = engine_range_model.objects.filter(request__isnull=False).values_list("id", "user_id", "request__request_id")
    for range_id, engine_user_id, request_id in rows:
        cms_user_id = cms_owner_by_request.get(request_id)
        if cms_user_id is not None and cms_user_id != engine_user_id:
            msg = (
                f"engine range {range_id} is owned by user {engine_user_id} but its CMS request is owned by "
                f"user {cms_user_id}. Resolve the ownership divergence before migrating (#1325)."
            )
            raise RuntimeError(msg)


def _workspace_for(personal: dict[int, int], user_id: int, label: str, row_id: int) -> int:
    """Resolve a user's personal workspace or fail loudly naming the row."""
    workspace_id = personal.get(user_id)
    if workspace_id is None:
        msg = (
            f"{label} {row_id} references user {user_id}, which has no personal workspace. "
            "Resolve the row's ownership before migrating (#1325)."
        )
        raise RuntimeError(msg)
    return workspace_id


def backfill_workspace_bindings(apps, schema_editor):  # noqa: ARG001 - migration signature
    """Bind unbound CMS requests and range projections to their owner's workspace."""
    request_model = apps.get_model("cms", "Request")
    range_instance_model = apps.get_model("cms", "RangeInstance")
    workspace_model = apps.get_model("workspaces", "Workspace")
    engine_range_model = apps.get_model("engine", "Range")

    _assert_projection_agrees_with_request(range_instance_model)
    _assert_cms_agrees_with_engine(request_model, engine_range_model)

    personal = _personal_workspace_ids(workspace_model)
    if not personal:
        return

    for request_id, user_id in request_model.objects.filter(workspace_id__isnull=True).values_list("id", "user_id"):
        workspace_id = _workspace_for(personal, user_id, "CMS request", request_id)
        request_model.objects.filter(id=request_id).update(workspace_id=workspace_id)

    for instance_id, user_id in range_instance_model.objects.filter(workspace_id__isnull=True).values_list(
        "id", "user_id"
    ):
        workspace_id = _workspace_for(personal, user_id, "CMS range projection", instance_id)
        range_instance_model.objects.filter(id=instance_id).update(workspace_id=workspace_id)


class Migration(migrations.Migration):
    """Bind pre-#1325 CMS request/range rows to their owner's personal workspace."""

    dependencies = [
        ("cms", "0038_rangeinstance_workspace_id_request_workspace_id"),
        ("workspaces", "0002_backfill_personal_workspaces"),
    ]

    # This migration owns the ownership-divergence checks for both layers, so it
    # must run before any range is bound -- otherwise a divergent deployment
    # would have engine rows already written when it halts. The edge is declared
    # here rather than as an engine->cms dependency because CMS is the layer
    # allowed to know about Engine (ADR-001), never the reverse.
    run_before = [
        ("engine", "0041_backfill_workspace_bindings"),
    ]

    operations = [
        migrations.RunPython(backfill_workspace_bindings, migrations.RunPython.noop),
    ]
