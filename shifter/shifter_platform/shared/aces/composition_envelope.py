"""Capability-envelope validation for ACES composition placements (ADR-032).

Split out of ``runtime_target`` (Sonar file-size): fail-closed diagnostics for
``content-placement`` / ``feature-binding`` / ``account-placement`` resources --
content type against ``supported_content_types``, account features (via the shared
``provisioner_account_features``) against ``supported_account_features``, and every
placement's target node present in the plan.

Account features are gated against two independent envelopes (#1563): the manifest
declaration (``supported_account_features``, plan-time vocabulary) and the
hand-authored realization evidence
(``shared.aces.realization_ledger.REALIZED_ACCOUNT_FEATURES``). A requested feature
outside the declaration is an ``unsupported-account-feature``; a feature that is
declared but not evidence-backed is an ``account-feature-not-realized`` -- so the
manifest cannot silently over-claim account realization.
"""

from __future__ import annotations

from collections.abc import Mapping

from aces_backend_protocols.account_features import provisioner_account_features
from aces_backend_protocols.capabilities import ProvisionerCapabilities
from aces_contracts.diagnostics import Diagnostic, Severity
from aces_contracts.planning import ChangeAction, PlannedResource, PlanOperation

from shared.aces.realization_ledger import REALIZED_ACCOUNT_FEATURES, REALIZED_FEATURE_TYPES
from shared.log_sanitize import safe_log_value

_DOMAIN = "provisioning"
CONTENT_PLACEMENT_RESOURCE_TYPE = "content-placement"
FEATURE_BINDING_RESOURCE_TYPE = "feature-binding"
ACCOUNT_PLACEMENT_RESOURCE_TYPE = "account-placement"
#: Composition placement resource types (content/features/accounts), all PROVISIONING.
COMPOSITION_RESOURCE_TYPES: frozenset[str] = frozenset(
    {CONTENT_PLACEMENT_RESOURCE_TYPE, FEATURE_BINDING_RESOURCE_TYPE, ACCOUNT_PLACEMENT_RESOURCE_TYPE}
)

#: Canonical login methods Shifter can genuinely realize on both supported
#: guest dialects. ``aces-sdl`` intentionally leaves ``auth_method`` open, so
#: this backend-owned value policy must fail closed before dispatch.
SUPPORTED_ACCOUNT_AUTH_METHODS: frozenset[str] = frozenset({"password", "publickey"})
SUPPORTED_PASSWORD_STRENGTHS: frozenset[str] = frozenset({"weak", "medium", "strong", "none"})
_RESERVED_ACCOUNT_USERNAMES: frozenset[str] = frozenset({"aces"})


def _diagnostic(code: str, address: str, message: str) -> Diagnostic:
    """Build an ERROR provisioning diagnostic."""
    return Diagnostic(code=code, domain=_DOMAIN, address=address, message=message, severity=Severity.ERROR)


def _placement_target(payload: Mapping[str, object]) -> str:
    """Return the resolved target node address of a composition placement, or ''."""
    for key in ("target_address", "node_address"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _unbound_placement_diagnostics(
    resource: PlannedResource, target: str, node_addresses: set[str]
) -> list[Diagnostic]:
    """Fail closed when a placement's target node is not present in the plan."""
    if target and target in node_addresses:
        return []
    return [
        _diagnostic(
            "shifter-provisioner.unbound-placement",
            resource.address,
            f"placement targets node '{safe_log_value(target)}' not present in this plan",
        )
    ]


def _content_placement_diagnostics(
    resource: PlannedResource,
    payload: Mapping[str, object],
    capabilities: ProvisionerCapabilities,
    node_addresses: set[str],
) -> list[Diagnostic]:
    """Return capability-envelope diagnostics for a content-placement resource."""
    diagnostics: list[Diagnostic] = []
    spec = payload.get("spec")
    content_type = spec.get("type") if isinstance(spec, Mapping) else None
    if isinstance(content_type, str) and content_type.lower() not in capabilities.supported_content_types:
        diagnostics.append(
            _diagnostic(
                "shifter-provisioner.unsupported-content-type",
                resource.address,
                f"unsupported content type '{safe_log_value(content_type)}' "
                f"(supported: {sorted(capabilities.supported_content_types)})",
            )
        )
    diagnostics.extend(_unbound_placement_diagnostics(resource, _placement_target(payload), node_addresses))
    return diagnostics


def _account_identity_diagnostics(address: str, spec: Mapping[str, object]) -> list[Diagnostic]:
    """Reject account names reserved for the management identity."""
    raw_username = spec.get("username")
    if not (isinstance(raw_username, str) and raw_username.casefold() in _RESERVED_ACCOUNT_USERNAMES):
        return []
    return [
        _diagnostic(
            "shifter-provisioner.reserved-account-username",
            address,
            "account username is reserved for the provisioner management identity",
        )
    ]


def _password_strength_diagnostics(address: str, spec: Mapping[str, object]) -> list[Diagnostic]:
    """Validate password strength and disabled-account semantics."""
    raw_strength = spec.get("password_strength", "")
    if raw_strength == "":
        strength = "medium"
    elif not isinstance(raw_strength, str) or raw_strength.strip() != raw_strength:
        return [
            _diagnostic(
                "shifter-provisioner.invalid-password-strength",
                address,
                "password_strength must be an omitted, empty, or canonical string",
            )
        ]
    else:
        strength = raw_strength
    if strength in SUPPORTED_PASSWORD_STRENGTHS and not (strength == "none" and spec.get("disabled") is not True):
        return []
    return [
        _diagnostic(
            "shifter-provisioner.unsupported-password-strength",
            address,
            "password_strength cannot be realized as a safe login credential",
        )
    ]


def _account_auth_diagnostics(address: str, spec: Mapping[str, object]) -> list[Diagnostic]:
    """Validate the account authentication method and its password policy."""
    raw_method = spec.get("auth_method", "")
    if raw_method == "":
        method = "password"
    elif not isinstance(raw_method, str) or raw_method.strip() != raw_method:
        return [
            _diagnostic(
                "shifter-provisioner.invalid-account-auth-method",
                address,
                "account auth_method must be an omitted, empty, or canonical string",
            )
        ]
    else:
        method = raw_method
    if method not in SUPPORTED_ACCOUNT_AUTH_METHODS:
        return [
            _diagnostic(
                "shifter-provisioner.unsupported-account-auth-method",
                address,
                "account auth_method is outside the backend-supported policy",
            )
        ]
    return _password_strength_diagnostics(address, spec) if method == "password" else []


def _account_feature_diagnostics(
    address: str, spec: Mapping[str, object], capabilities: ProvisionerCapabilities
) -> list[Diagnostic]:
    """Fail-closed account-feature diagnostics for one account spec.

    Two independent envelopes (#1563): the manifest declaration
    (``supported_account_features``) and the hand-authored realization evidence
    (``REALIZED_ACCOUNT_FEATURES``). A requested feature outside the declaration is
    ``unsupported-account-feature``; a declared-but-not-evidence-backed feature is
    ``account-feature-not-realized``. The two branches are mutually exclusive so a
    single feature never double-reports.
    """
    diagnostics = [
        *_account_identity_diagnostics(address, spec),
        *_account_auth_diagnostics(address, spec),
    ]
    for feature in sorted(provisioner_account_features(spec)):
        if feature not in capabilities.supported_account_features:
            diagnostics.append(
                _diagnostic(
                    "shifter-provisioner.unsupported-account-feature",
                    address,
                    f"unsupported account feature '{feature}' "
                    f"(supported: {sorted(capabilities.supported_account_features)})",
                )
            )
        elif feature not in REALIZED_ACCOUNT_FEATURES:
            # Independent evidence gate (#1563): the manifest declares this feature
            # but the backend does not genuinely realize it. Fail closed rather than
            # trust the declaration, so a manifest over-claim cannot reach dispatch.
            diagnostics.append(
                _diagnostic(
                    "shifter-provisioner.account-feature-not-realized",
                    address,
                    f"account feature '{feature}' is declared but not evidence-backed; "
                    "this backend does not realize it",
                )
            )
    return diagnostics


def _account_placement_diagnostics(
    resource: PlannedResource,
    payload: Mapping[str, object],
    capabilities: ProvisionerCapabilities,
    node_addresses: set[str],
) -> list[Diagnostic]:
    """Return capability-envelope diagnostics for an account-placement resource."""
    diagnostics: list[Diagnostic] = []
    spec = payload.get("spec")
    spec = spec if isinstance(spec, Mapping) else {}
    if not capabilities.supports_accounts:
        diagnostics.append(
            _diagnostic(
                "shifter-provisioner.accounts-unsupported",
                resource.address,
                "this backend does not realize account placements",
            )
        )
    else:
        diagnostics.extend(_account_feature_diagnostics(resource.address, spec, capabilities))
    diagnostics.extend(_unbound_placement_diagnostics(resource, _placement_target(payload), node_addresses))
    return diagnostics


def _feature_template(payload: Mapping[str, object]) -> Mapping[str, object]:
    """Return one feature-binding's authored template mapping."""
    spec = payload.get("spec")
    template = spec.get("template") if isinstance(spec, Mapping) else None
    return template if isinstance(template, Mapping) else {}


def _feature_source_present(template: Mapping[str, object]) -> bool:
    """True when the template carries a canonical source identity."""
    source = template.get("source")
    if isinstance(source, str):
        return bool(source.strip())
    return isinstance(source, Mapping) and isinstance(source.get("name"), str) and bool(source["name"].strip())


def _feature_shape_diagnostics(address: str, payload: Mapping[str, object]) -> list[Diagnostic]:
    """Fail closed on feature shapes without genuine backend realization."""
    template = _feature_template(payload)
    raw_type = template.get("type")
    feature_type = raw_type.lower() if isinstance(raw_type, str) else ""
    diagnostics: list[Diagnostic] = []
    if feature_type not in REALIZED_FEATURE_TYPES:
        return [
            _diagnostic(
                "shifter-provisioner.unsupported-feature-type",
                address,
                "feature type is outside the backend realization ledger",
            )
        ]
    environment = template.get("environment")
    if environment not in (None, {}, []):
        diagnostics.append(
            _diagnostic(
                "shifter-provisioner.feature-environment-unsupported",
                address,
                "feature environment values have no safe realization contract",
            )
        )
    if not _feature_source_present(template):
        diagnostics.append(
            _diagnostic(
                "shifter-provisioner.feature-source-required",
                address,
                "feature realization requires a canonical source identity",
            )
        )
    destination = template.get("destination")
    if feature_type in {"artifact", "configuration"} and not (
        isinstance(destination, str) and bool(destination.strip())
    ):
        diagnostics.append(
            _diagnostic(
                "shifter-provisioner.feature-destination-required",
                address,
                "delivered feature realization requires a destination",
            )
        )
    return diagnostics


def _feature_binding_diagnostics(
    resource: PlannedResource,
    payload: Mapping[str, object],
    node_addresses: set[str],
) -> list[Diagnostic]:
    """Return realization-ledger and target diagnostics for a feature binding."""
    return [
        *_feature_shape_diagnostics(resource.address, payload),
        *_unbound_placement_diagnostics(resource, _placement_target(payload), node_addresses),
    ]


def account_operation_diagnostics(
    operations: list[PlanOperation], capabilities: ProvisionerCapabilities
) -> list[Diagnostic]:
    """Account-feature diagnostics for materializing account-placement operations (#1563).

    The resource pass gates the plan's resource view; this covers the case where an
    account payload is carried only by a materializing (CREATE / UPDATE) operation, or
    diverges from the resource snapshot, so an over-claimed feature cannot slip past
    the realization ledger via an operation-only payload before the plan is dispatched.
    A DELETE operation removes an account and does not materialize its historical
    features, so it is exempt; UNCHANGED operations are no-ops. The caller
    deduplicates these against the resource-pass diagnostics.
    """
    diagnostics: list[Diagnostic] = []
    for operation in operations:
        if operation.resource_type != ACCOUNT_PLACEMENT_RESOURCE_TYPE:
            continue
        if operation.action not in (ChangeAction.CREATE, ChangeAction.UPDATE):
            continue
        if not capabilities.supports_accounts:
            diagnostics.append(
                _diagnostic(
                    "shifter-provisioner.accounts-unsupported",
                    operation.address,
                    "this backend does not realize account placements",
                )
            )
            continue
        payload = operation.payload
        spec = payload.get("spec") if isinstance(payload, Mapping) else None
        spec = spec if isinstance(spec, Mapping) else {}
        diagnostics.extend(_account_feature_diagnostics(operation.address, spec, capabilities))
    return diagnostics


def feature_operation_diagnostics(operations: list[PlanOperation]) -> list[Diagnostic]:
    """Gate feature shapes carried only by materializing operations (#1565)."""
    diagnostics: list[Diagnostic] = []
    for operation in operations:
        if operation.resource_type != FEATURE_BINDING_RESOURCE_TYPE:
            continue
        if operation.action not in (ChangeAction.CREATE, ChangeAction.UPDATE):
            continue
        payload = operation.payload
        diagnostics.extend(
            _feature_shape_diagnostics(operation.address, payload if isinstance(payload, Mapping) else {})
        )
    return diagnostics


def composition_diagnostics(
    resource: PlannedResource,
    payload: Mapping[str, object],
    capabilities: ProvisionerCapabilities,
    node_addresses: set[str],
) -> list[Diagnostic]:
    """Dispatch envelope validation for one composition placement resource."""
    if resource.resource_type == CONTENT_PLACEMENT_RESOURCE_TYPE:
        return _content_placement_diagnostics(resource, payload, capabilities, node_addresses)
    if resource.resource_type == ACCOUNT_PLACEMENT_RESOURCE_TYPE:
        return _account_placement_diagnostics(resource, payload, capabilities, node_addresses)
    return _feature_binding_diagnostics(resource, payload, node_addresses)
