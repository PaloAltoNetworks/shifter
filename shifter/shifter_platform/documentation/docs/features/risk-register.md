# Risk Register

The Risk Register tracks security risks with severity, status, likelihood and
impact scores, STRIDE categories, mitigation notes, comments, and an audit
history.

## Access

Access requires a session (or a scoped API token) whose principal is in a
configured risk-register group (`RISK_REGISTER_ALLOWED_COGNITO_GROUPS`).
Creating and editing risks additionally requires a staff session. Audit history
is visible to administrators. The API enforces these rules; the UI only reflects
them.

## Workflows

- **Browse and filter.** List risks and filter by severity, status, and whether
  to include soft-deleted rows. Filters are preserved in the URL so a refresh or
  shared link keeps the same view.
- **Create and edit.** Capture title, description, severity, status, likelihood
  and impact (1–5), STRIDE categories, attack vector, affected assets, and
  mitigation status. Server-side validation is authoritative.
- **Close and reopen.** Close a risk with a resolution reason; reopen returns it
  to open.
- **Delete and restore.** Delete is a soft delete; a deleted risk can be
  restored from the list or its detail view.
- **Comment.** Add and delete comments on a risk.
- **History.** Administrators can review the audit trail for a risk.

## Rollout

The workspace ships as a single-page application (SPA) behind the
`RISK_REGISTER_SPA_ENABLED` feature flag. When the flag is off (the default),
the portal serves the existing Django Risk Register pages unchanged. When it is
on, the pages under `/risk-register/` are served by the SPA while the legacy
form-action URLs remain available for compatibility and rollback. Turning the
flag back off restores the Django pages.
