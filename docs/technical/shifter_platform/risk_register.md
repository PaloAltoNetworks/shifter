# Risk Register (technical)

The `risk_register` Django app owns the Risk Register domain.

## Domain

- **Models** (`risk_register/models.py`): `Risk`, `Comment`, and `AuditLog`.
  `Risk` and `Comment` use the shared soft-delete managers
  (`shared.db.SoftDeleteManager`); `objects` is active-only and `all_objects` is
  the explicit full-table escape hatch.
- **API** (`risk_register/api/`): a DRF `DefaultRouter` exposes
  `RiskViewSet`, `AuditLogViewSet`, and a nested `CommentViewSet` under
  `/api/v1/` (`/risks/`, `/risks/{id}/restore/`, `/risks/{risk_pk}/comments/`,
  `/audit/`). List filters: `status`, `severity`, `include_deleted`.
- **Serializers**: `RiskSerializer` (read), `RiskCreateSerializer`,
  `RiskUpdateSerializer`, `CommentSerializer`, `AuditLogSerializer`. Field
  validation (including STRIDE-category validation) is shared across the read,
  create, and update serializers via `RiskValidatorsMixin`.
- **Authorization** (`risk_register/access.py`, `risk_register/api/permissions.py`):
  risk-register group membership plus a staff session or a scoped API token
  (`risk:read` / `risk:write`); audit reads require an admin session.
- **Audit** (`risk_register/services.py`): new mutations record through the audit
  facade so request id, trusted source IP, and log redaction stay centralized.

## SPA (ADR-029 / #1302)

The Risk Register is the first SPA module of the SPA cutover. The React +
TypeScript + Vite frontend lives at `shifter/shifter_platform/frontend/` and is
built into `static/spa/` (WhiteNoise-served). It consumes only `/api/v1/`
(session cookie + `X-CSRFToken`, no browser tokens), typed from the
drf-spectacular schema, and loads shell state from the `/api/v1/bootstrap/`
endpoint. A flag-gated Django host view (`risk_register/spa_views.py`, behind
`RISK_REGISTER_SPA_ENABLED`) serves the SPA shell for the GET page paths while
the legacy Django routes remain for compatibility and rollback.

See the architecture and design records for the full contract:
`docs/architecture/spa-cutover-architecture-1300.md` and
`docs/design/spa-risk-register-workspace-1301.md`. Audit internals are covered in
[Platform Audit System Architecture](../../risk/audit-system-architecture.md).
