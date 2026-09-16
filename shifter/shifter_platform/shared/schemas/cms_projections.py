"""Static-typing contracts for ``cms.services`` projection dictionaries.

These ``TypedDict`` schemas describe the *shape* of the plain dictionaries
returned by the read-side ``cms.services`` entrypoints — ``list_agents``,
``initiate_upload``, ``list_scenarios`` / ``list_launchable_scenarios``, and
``get_scenario`` — and consumed by Mission Control and CTF APIs.

They are **static typing only** (issue #317). The returned values have already
crossed their authoritative runtime boundaries — the ORM and
``_assert_agent_projection_shape`` for agents, HMAC upload-token signing and
S3 object/header inspection for uploads, and RAES package-source validation for
scenarios. A ``TypedDict`` annotation is not a
validator, an authorization check, a serializer, or a response allowlist; every
existing runtime gate remains authoritative. See
``docs/architecture/typed-cms-service-projections-preflight-317.md``.

This module is shared-native and stdlib-only: it must not import ``cms`` or the
RAES implementation packages.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from datetime import datetime


class AgentRequirements(TypedDict):
    """Agent-capability flags carried on every scenario projection."""

    requires_windows: bool
    requires_linux: bool
    has_from_agent: bool


class AgentListItem(TypedDict):
    """One row from ``cms.services.list_agents`` (``_agent_projection_dict``).

    Display fields only — never ``s3_key``, hashes, or owner identifiers. DRF's
    ``AgentListItemSerializer`` renders ``created_at`` as a string, but the
    service projection carries the ``datetime`` it read off the model.
    """

    id: int
    name: str
    os_name: str
    os_slug: str
    file_size_mb: float
    original_filename: str
    created_at: datetime
    agent_type: str
    agent_type_display: str


class UploadInitiation(TypedDict):
    """Result of ``cms.services.initiate_upload``.

    ``presigned_url`` and ``upload_token`` are short-lived bearer capabilities
    delivered only in the authenticated JSON response — never logged, persisted,
    or placed in argv/env. ``expected_os`` is non-null at the service boundary:
    installer initiation rejects a file format without an OS slug before the
    result is built, so the looser (nullable) DRF presentation schema does not
    weaken this invariant.
    """

    presigned_url: str
    s3_key: str
    upload_token: str
    expected_os: str


class ScenarioProjection(TypedDict):
    """One RAES package-source entry from the catalog projection."""

    id: str
    name: str
    description: str
    scenario_type: str
    enabled: bool
    staff_only: bool
    is_default: bool
    launchable: bool
    agent_requirements: AgentRequirements

    source_kind: str
    contract_kind: str
    contract_profile: str
