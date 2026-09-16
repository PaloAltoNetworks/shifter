"""Contract tests for the ``cms.services`` projection TypedDicts.

These lock the *key set* of the static-typing contracts in
``shared.schemas.cms_projections`` so a key removed/renamed on a TypedDict trips
a red test (in addition to blocking mypy). They are structural, not
runtime-validation tests: the TypedDicts are static-only and do not validate at
runtime (see the module docstring and the #317 preflight note).

The required-vs-optional split is enforced by mypy — it is not asserted here
because the module uses ``from __future__ import annotations`` (matching the
``shared.messages.payloads`` precedent), under which the runtime
``__required_keys__`` / ``__optional_keys__`` introspection is unreliable. Only
the full key set (``__annotations__``) is stable at runtime.
"""

from __future__ import annotations

from shared.schemas.cms_projections import (
    AgentListItem,
    AgentRequirements,
    ScenarioProjection,
    UploadInitiation,
)


def test_agent_requirements_keys() -> None:
    assert set(AgentRequirements.__annotations__) == {
        "requires_windows",
        "requires_linux",
        "has_from_agent",
    }


def test_agent_list_item_keys() -> None:
    assert set(AgentListItem.__annotations__) == {
        "id",
        "name",
        "os_name",
        "os_slug",
        "file_size_mb",
        "original_filename",
        "created_at",
        "agent_type",
        "agent_type_display",
    }


def test_upload_initiation_keys() -> None:
    assert set(UploadInitiation.__annotations__) == {
        "presigned_url",
        "s3_key",
        "upload_token",
        "expected_os",
    }


def test_scenario_projection_keys() -> None:
    assert set(ScenarioProjection.__annotations__) == {
        # Common catalog metadata (every source).
        "id",
        "name",
        "description",
        "scenario_type",
        "enabled",
        "staff_only",
        "is_default",
        "launchable",
        "agent_requirements",
        # RAES provenance.
        "source_kind",
        "contract_kind",
        "contract_profile",
    }
