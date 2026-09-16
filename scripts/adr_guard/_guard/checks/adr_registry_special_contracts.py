"""Specialized executable ADR interface-contract validators."""

from __future__ import annotations

from .adr_registry_contract_support import (
    validate_closed_mapping,
    validate_exact_string_members,
)

CTF_COMMUNICATION_SOURCES = frozenset(
    {
        "manual",
        "static-scenario",
        "dynamic-platform",
        "timed",
        "raes-runtime",
        "range-signal",
    }
)
CTF_COMMUNICATION_AUDIENCES = frozenset(
    {"participant", "participant-set", "teams", "event", "events"}
)
CTF_COMMUNICATION_RAES_KINDS = frozenset(
    {"disclosure", "external-direction", "intervention"}
)
CTF_COMMUNICATION_RANGE_REQUEST_FIELDS = frozenset(
    {"protocol_version", "declaration_id", "occurrence", "nonce"}
)
CTF_COMMUNICATION_RANGE_FORBIDDEN_AUTHORITY = frozenset(
    {
        "workspace",
        "event",
        "scenario",
        "campaign",
        "subject",
        "body",
        "locale",
        "link",
        "channel",
        "user",
        "email",
        "team",
        "participant",
        "schedule",
        "policy",
        "control",
    }
)
CTF_COMMUNICATION_DELIVERY_STATES = frozenset(
    {
        "in-app-available",
        "email-backend-accepted",
        "websocket-published",
        "socket-written",
        "read",
        "acknowledged",
        "control-effect",
    }
)
CTF_COMMUNICATION_VERIFICATION_CLASSES = frozenset(
    {
        "authorization-isolation",
        "content-safety",
        "raes-conformance",
        "adversarial-ingress-replay",
        "credential-lifecycle",
        "postgresql-concurrency-recovery",
        "delivery-load",
        "retention-redaction",
        "configuration-parity",
        "migration-api-contract",
        "browser",
    }
)
CTF_COMMUNICATION_DOCUMENTATION_CLASSES = frozenset(
    {
        "participant",
        "organizer",
        "scenario-author",
        "technical",
        "operator",
        "api-client",
    }
)
CTF_RANGE_INGRESS_SHOW_ONCE_FIELD = "credential"

DEDICATED_CUSTOMER_AUTHORITY_SCOPES = frozenset(
    {
        "deployment-customer",
        "organization",
        "workspace",
        "event",
        "participant",
        "application-operator",
        "cloud-operator",
        "external-client",
    }
)
DEDICATED_CUSTOMER_AUTHORITY_VERIFICATION = frozenset(
    {
        "session-token-parity",
        "revoked-authority",
        "cross-event-denial",
        "event-binding-migration",
        "remote-access-revocation",
        "audited-platform-override",
        "effective-iam-network-denial",
        "dependency-outage-behavior",
    }
)

ACCESSIBILITY_WCAG_TAGS = frozenset(
    {"wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"}
)
ACCESSIBILITY_SURFACE_KINDS = frozenset(
    {"spa-route", "django-html-route", "mkdocs-page", "enabled-third-party-ui"}
)
ACCESSIBILITY_FIXED_SECTIONS: dict[str, dict[str, object]] = {
    "standard": {
        "target": "wcag-2.2-aa",
        "governed_scope": "complete-human-facing-pages-and-processes",
        "automated_conformance_claim": False,
    },
    "toolchain": {
        "static": "eslint-plugin-jsx-a11y",
        "component": "vitest-axe",
        "browser": "@axe-core/playwright",
        "runner": "playwright",
        "parallel_conformance_runners": False,
    },
    "cadence": {
        "pull_request": "complete-registered-pr-matrix",
        "nightly": "same-matrix-expanded-browser-projects",
        "on_demand": "same-runner-allowlisted-deployed-target",
        "manual": "material-release-and-annual",
    },
    "coverage": {
        "source": "test-owned-surface-state-matrix",
        "new_surface": "fail-until-registered",
        "removed_surface": "fail-until-pruned",
    },
    "baseline": {
        "comparison": "trusted-base-exact-finding-set",
        "additions": "forbidden",
        "resolved_entries": "must-be-removed",
        "counts_or_thresholds": False,
        "raw_dom": False,
        "tool_upgrade": "remediate-or-separately-waive",
    },
    "manual_audit": {
        "method": "wcag-em",
        "initial_trigger": "before-first-conforming-release",
        "release_trigger": "new-or-materially-changed-surface-or-process",
        "incident_trigger": "accessibility-critical-incident",
        "maximum_interval_days": 365,
        "reviewer": "accessibility-trained-independent-when-practicable",
        "record": "docs/audit/accessibility",
        "release_gate": "before-write-capable-release",
    },
    "waivers": {
        "registry": "docs/adr/exceptions.yaml",
        "scope": "exact-fingerprint",
        "approval": "adr-codeowner-no-self-approval",
        "expiry": "no-later-than-next-planned-release",
        "conformance_effect": "release-only-not-conformance",
    },
    "security": {
        "pr_permissions": "contents-read",
        "normal_auth_boundaries": True,
        "csp_relaxation": False,
        "free_form_target_url": False,
        "sensitive_artifacts": False,
    },
}
ACCESSIBILITY_STRING_SET_SECTIONS = {
    "toolchain": {"wcag_tags": ACCESSIBILITY_WCAG_TAGS},
    "coverage": {"surface_kinds": ACCESSIBILITY_SURFACE_KINDS},
}


def _contract_key_errors(
    contract: dict[str, object], adr_id: str, expected_keys: set[str]
) -> list[str]:
    """Report an interface contract whose top-level keys differ from its schema."""
    actual_keys = set(contract)
    if actual_keys == expected_keys:
        return []
    return [
        f"{adr_id} interface_contract must contain exactly {sorted(expected_keys)}; got {sorted(actual_keys)}"
    ]


def _validate_ctf_sections(contract: dict[str, object], prefix: str) -> list[str]:
    """Validate the scope, immutable intent, and RAES CTF communication sections."""
    errors = validate_closed_mapping(
        contract.get("scope"),
        f"{prefix}.scope",
        fixed={
            "campaign_workspace_count": 1,
            "event_authorization": "every-target-event",
            "recipient_authority": "event-scoped-ctf-participant",
            "platform_root": "audited-django-superuser-single-workspace",
        },
    )
    errors.extend(
        validate_closed_mapping(
            contract.get("intent"),
            f"{prefix}.intent",
            fixed={"type": "CommunicationIntent", "immutable": True},
            string_sets={
                "sources": CTF_COMMUNICATION_SOURCES,
                "audiences": CTF_COMMUNICATION_AUDIENCES,
            },
        )
    )
    errors.extend(
        validate_closed_mapping(
            contract.get("raes"),
            f"{prefix}.raes",
            fixed={
                "interpreter": "shared.raes",
                "unsupported": "reject-before-persistence-delivery-effect",
            },
            string_sets={"delivery_kinds": CTF_COMMUNICATION_RAES_KINDS},
        )
    )
    return errors


def _validate_ctf_ingress_content_delivery(
    contract: dict[str, object], prefix: str
) -> list[str]:
    """Validate CTF range ingress, content controls, and delivery semantics."""
    errors = validate_closed_mapping(
        contract.get("range_ingress"),
        f"{prefix}.range_ingress",
        fixed={
            "trust": "compromised",
            "authentication": "dedicated-generation-fenced-range-trigger",
            CTF_RANGE_INGRESS_SHOW_ONCE_FIELD: "opaque-show-once-revocable",
            "binding": "issuer-deployment-audience-expiry-current-generation",
            "replay_fence": "database-unique-occurrence",
            "rate_limit": "shared-fail-closed",
            "audit_order": "before-effect",
        },
        string_sets={
            "request_fields": CTF_COMMUNICATION_RANGE_REQUEST_FIELDS,
            "forbidden_authority": CTF_COMMUNICATION_RANGE_FORBIDDEN_AUTHORITY,
        },
    )
    errors.extend(
        validate_closed_mapping(
            contract.get("content"),
            f"{prefix}.content",
            fixed={
                "profile": "ctf-communication-markdown/v1",
                "subject_codepoints": 200,
                "source_bytes": 65536,
                "rendered_bytes": 131072,
                "link_policy": "relative-or-allowlisted-https",
                "raw_html": False,
                "remote_media": False,
                "executable_behavior": False,
            },
        )
    )
    errors.extend(
        validate_closed_mapping(
            contract.get("delivery"),
            f"{prefix}.delivery",
            fixed={
                "workflow_truth": "postgresql",
                "semantics": "at-least-once",
                "timing": "ctf-scheduler",
                "aggregate_overclaim": False,
            },
            string_sets={"states": CTF_COMMUNICATION_DELIVERY_STATES},
        )
    )
    return errors


def validate_ctf_communications_contract(
    contract: dict[str, object], adr_id: str
) -> list[str]:
    """Validate ADR-051's closed communications security and realization contract."""
    expected_keys = {
        "kind",
        "scope",
        "intent",
        "raes",
        "range_ingress",
        "content",
        "delivery",
        "verification",
        "documentation",
    }
    prefix = f"{adr_id} interface_contract"
    errors = _contract_key_errors(contract, adr_id, expected_keys)
    errors.extend(_validate_ctf_sections(contract, prefix))
    errors.extend(_validate_ctf_ingress_content_delivery(contract, prefix))
    errors.extend(
        validate_exact_string_members(
            contract.get("verification"),
            CTF_COMMUNICATION_VERIFICATION_CLASSES,
            f"{prefix}.verification",
        )
    )
    errors.extend(
        validate_exact_string_members(
            contract.get("documentation"),
            CTF_COMMUNICATION_DOCUMENTATION_CLASSES,
            f"{prefix}.documentation",
        )
    )
    return errors


def validate_dedicated_customer_authority_contract(
    contract: dict[str, object], adr_id: str
) -> list[str]:
    """Validate ADR-054's dedicated-customer and internal-authority contract."""
    expected_keys = {
        "kind",
        "deployment",
        "authorities",
        "event_transition",
        "ownership",
        "outages",
        "verification",
    }
    prefix = f"{adr_id} interface_contract"
    errors = _contract_key_errors(contract, adr_id, expected_keys)
    errors.extend(
        validate_closed_mapping(
            contract.get("deployment"),
            f"{prefix}.deployment",
            fixed={
                "customer_count": 1,
                "unrelated_customer_shared_control_plane": False,
                "isolation_proof": "effective-config-identity-network-data-secret-evidence",
            },
        )
    )
    errors.extend(
        validate_closed_mapping(
            contract.get("authorities"),
            f"{prefix}.authorities",
            fixed={
                "composition": "owning-service-boundaries",
                "workspace_membership_grants_event_authority": False,
                "external_client_effect_ownership": False,
            },
            string_sets={"scopes": DEDICATED_CUSTOMER_AUTHORITY_SCOPES},
        )
    )
    errors.extend(
        validate_closed_mapping(
            contract.get("event_transition"),
            f"{prefix}.event_transition",
            fixed={
                "pre_migration": "deployment-global-event-records",
                "activation": "issue-2048-required-backfill-and-schema",
                "post_migration": "required-immutable-workspace-binding",
                "unresolved_backfill": "fail-closed",
                "event_authority": "event-native-before-and-after",
            },
        )
    )
    errors.extend(
        validate_closed_mapping(
            contract.get("ownership"),
            f"{prefix}.ownership",
            fixed={
                "api_services": "versioned-api-to-domain-service-facades",
                "iam": "deployment-operator-provider-policy",
                "datastore": "domain-owned-postgresql",
                "secrets": "deployment-local-secret-authority",
                "network": "platform-and-range-infrastructure",
                "evidence": "shared-audit-and-provider-observations",
            },
        )
    )
    errors.extend(
        validate_closed_mapping(
            contract.get("outages"),
            f"{prefix}.outages",
            fixed={
                "identity_provider": "deny-new-idp-session",
                "datastore": "deny-state-dependent-admission",
                "registry": "deny-new-acquisition-without-validated-local-state",
                "secret_store": "deny-secret-dependent-effect",
                "model_provider": "fail-dependent-capability-without-authority-change",
                "provider_api": "retain-failed-or-indeterminate-truth",
                "audit": "strict-mutation-fails-or-degraded-state-visible",
            },
        )
    )
    errors.extend(
        validate_exact_string_members(
            contract.get("verification"),
            DEDICATED_CUSTOMER_AUTHORITY_VERIFICATION,
            f"{prefix}.verification",
        )
    )
    return errors


def validate_accessibility_enforcement_contract(
    contract: dict[str, object], adr_id: str
) -> list[str]:
    """Validate ADR-055's closed accessibility governance contract."""
    errors = _contract_key_errors(
        contract, adr_id, set(ACCESSIBILITY_FIXED_SECTIONS) | {"kind"}
    )
    prefix = f"{adr_id} interface_contract"
    for section, fixed in ACCESSIBILITY_FIXED_SECTIONS.items():
        errors.extend(
            validate_closed_mapping(
                contract.get(section),
                f"{prefix}.{section}",
                fixed=fixed,
                string_sets=ACCESSIBILITY_STRING_SET_SECTIONS.get(section),
            )
        )
    return errors
