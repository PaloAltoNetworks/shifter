"""Prepared principal/account presentation, with no staff or membership grant inference."""

from dataclasses import dataclass
from uuid import UUID

from shared.authorization import ACTION_CATALOG, AuthorizationProvider, AuthorizationRequest, TargetRef
from shared.credentials import CredentialContext
from shared.identity_scope import ResourceScope
from workspaces.models import Account

from ._account import AccountScopeError
from ._account_policy_admin import AccountAdminPage, AccountAdminView, _active_actor, admin_list_accounts

_SCOPE_UNAVAILABLE = "Scope unavailable"


@dataclass(frozen=True, slots=True)
class AccountPrincipalContext:
    """Display-only policy projection; each resource command still reauthorizes."""

    principal_uuid: UUID
    principal_kind: str
    accounts: AccountAdminPage
    individual_account: AccountAdminView | None
    installation_actions: tuple[str, ...]


def admin_principal_context(
    actor: CredentialContext, provider: AuthorizationProvider, *, offset: int = 0, limit: int = 50
) -> AccountPrincipalContext:
    """An individual has a direct account; a service never impersonates its contact."""
    _active_actor(actor)
    accounts = admin_list_accounts(actor, provider, offset=offset, limit=limit)
    requests = tuple(
        AuthorizationRequest(
            actor.principal, item.code, TargetRef("installation"), ResourceScope("installation"), actor.ceiling
        )
        for item in ACTION_CATALOG
        if item.target_type == "installation" and actor.ceiling.permits(item.code, TargetRef("installation"))
    )
    try:
        decisions = provider.batch_check(requests) if requests else ()
        if len(decisions) != len(requests) or any(decision.kind == "evaluator_error" for decision in decisions):
            raise AccountScopeError(_SCOPE_UNAVAILABLE)
        allowed = tuple(
            request.action for request, decision in zip(requests, decisions, strict=True) if decision.allowed
        )
        individual = _individual_account(actor, provider)
    except Exception as exc:
        raise AccountScopeError(_SCOPE_UNAVAILABLE) from exc
    return AccountPrincipalContext(actor.principal.uuid, actor.principal.kind, accounts, individual, allowed)


def _individual_account(actor: CredentialContext, provider: AuthorizationProvider) -> AccountAdminView | None:
    """Resolve only the current human's own explicitly readable individual account."""
    if actor.principal.kind != "human":
        return None
    row = Account.objects.filter(kind=Account.Kind.INDIVIDUAL, individual_principal_uuid=actor.principal.uuid).first()
    if row is None or not actor.ceiling.permits("account.read", TargetRef("account", row.uuid)):
        return None
    decision = provider.check(
        AuthorizationRequest(
            actor.principal,
            "account.read",
            TargetRef("account", row.uuid),
            ResourceScope("account", row.uuid),
            actor.ceiling,
        )
    )
    if decision.kind == "evaluator_error":
        raise AccountScopeError(_SCOPE_UNAVAILABLE)
    return AccountAdminView(row.uuid, row.name, row.kind) if decision.allowed else None
