"""Read-only catalog presentation DTO over the unified scenario registry.

Issue #1254: expose RAES package-backed catalog entries as read-only catalog
metadata through the CMS API and the scenario editor, without adding an RAES
authoring editor.

This is a bounded projection *over* :mod:`cms.scenarios.registry` — it does not
duplicate the catalog, access model, or launchability rules. RAES entries gain a
nested ``raes`` block carrying
package-source identity, digests, conformance status/report ref, and a *bounded*
provenance summary. It never carries raw RAES SDL, imported module bodies,
generated content, flags, credentials, presigned URLs, provider payloads, or
runtime config.

See ``docs/adr/index.yaml``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from cms.scenarios.registry import get_catalog_entry, list_all_scenarios

if TYPE_CHECKING:
    from django.contrib.auth.models import User

    from cms.models import RaesPackageSource

RAES_SCENARIO_TYPE = "raes"

# Bounded allowlist of provenance keys surfaced in the presentation summary. It
# mirrors ``shared.schemas.raes_package_source.PROVENANCE_KEYS`` but is kept as
# an explicit *presentation-side* allowlist so that widening the persisted
# provenance contract never automatically widens what reaches API or template
# responses (defense in depth for the redaction boundary).
PROVENANCE_SUMMARY_KEYS: tuple[str, ...] = (
    "repo",
    "commit",
    "ref",
    "tool",
    "tool_version",
    "conformance_report",
    "generated_at",
    "notes",
)


def scenario_source(scenario_type: str, is_default: bool) -> str:
    """Classify a scenario's source for the read-only presentation.

    Single server-owned source of truth for the source classification. Both the
    catalog projection (this module) and the scenario-editor detail projection
    (``cms.api.views``) derive ``source`` from here, and the SPA consumes the
    server value rather than re-deriving it from ``scenario_type`` / ``is_default``.
    """
    if scenario_type == RAES_SCENARIO_TYPE:
        return "raes"
    if scenario_type == "ctf":
        return "ctf"
    return "builtin" if is_default else "custom"


def get_catalog_presentation(scenario_id: str) -> dict[str, Any] | None:
    """Return the read-only presentation DTO for a scenario id, or None if absent.

    Uses the unfiltered staff-review projection so a catalog inspector can see
    every entry (including disabled / staff-only) regardless of the requesting
    user. Access filtering for user-facing surfaces stays in the registry.
    """
    entry = get_catalog_entry(scenario_id)
    if entry is None:
        return None
    sources = _raes_source_map([scenario_id]) if _is_raes(entry) else {}
    return _to_presentation(entry, sources)


def list_catalog_presentations(user: User | None = None) -> list[dict[str, Any]]:
    """Return read-only presentation DTOs for all catalog entries.

    Access filtering (``enabled`` / ``staff_only``) is delegated to the registry
    via ``user``; pass ``None`` for the unfiltered staff-review projection.
    """
    entries = list_all_scenarios(user=user)
    raes_ids = [entry["id"] for entry in entries if _is_raes(entry)]
    sources = _raes_source_map(raes_ids)
    return [_to_presentation(entry, sources) for entry in entries]


def _is_raes(entry: Mapping[str, Any]) -> bool:
    """Return True when a catalog projection entry is an RAES package-backed row."""
    return entry.get("scenario_type") == RAES_SCENARIO_TYPE


def _raes_source_map(scenario_ids: list[str]) -> dict[str, RaesPackageSource]:
    """Bulk-load RAES package-source rows keyed by scenario id (avoids N+1)."""
    if not scenario_ids:
        return {}
    from cms.models import RaesPackageSource

    return {source.scenario_id: source for source in RaesPackageSource.objects.filter(scenario_id__in=scenario_ids)}


def _to_presentation(entry: Mapping[str, Any], raes_sources: dict[str, RaesPackageSource]) -> dict[str, Any]:
    """Build the presentation DTO for one catalog entry, attaching the RAES block when present."""
    presentation = _base_presentation(entry)
    if _is_raes(entry):
        source = raes_sources.get(entry["id"])
        if source is not None:
            presentation["raes"] = _raes_block(source)
    return presentation


def _base_presentation(entry: Mapping[str, Any]) -> dict[str, Any]:
    """Build the source-agnostic base DTO (identity, access overlay, launchability, empty raes)."""
    scenario_type = entry.get("scenario_type", "demo")
    is_default = entry.get("is_default", False)
    return {
        "id": entry["id"],
        "name": entry["name"],
        "scenario_type": scenario_type,
        "source": scenario_source(scenario_type, is_default),
        "is_default": is_default,
        "enabled": entry.get("enabled", True),
        "staff_only": entry.get("staff_only", False),
        "launchable": entry.get("launchable", True),
        "raes": None,
    }


def _raes_block(source: RaesPackageSource) -> dict[str, Any]:
    """Build the allowlisted RAES evidence block from a package-source row."""
    return {
        "source_kind": source.source_kind,
        "contract_kind": source.contract_kind,
        "contract_profile": source.contract_profile,
        "package_ref": source.package_ref,
        "package_version": source.package_version,
        "package_digest": source.package_digest,
        "lock_ref": source.lock_ref,
        "lock_digest": source.lock_digest,
        "conformance_status": source.conformance_status,
        "conformance_report_ref": source.conformance_report_ref,
        "provenance_summary": _provenance_summary(source.provenance),
    }


def _provenance_summary(provenance: object) -> dict[str, Any]:
    """Project provenance through the bounded presentation allowlist."""
    if not isinstance(provenance, dict):
        return {}
    return {key: provenance[key] for key in PROVENANCE_SUMMARY_KEYS if key in provenance}
