"""Realize ACES-authored account credentials over the management SSH channel."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from aces_plan import AcesPlanAccount
from executors.base import Executor
from executors.factory import GuestExecutionContext, build_guest_execution_context
from gcp_guest_secrets import (
    delete_aces_account_secret,
    ensure_aces_account_password_secret,
    ensure_aces_account_public_key_secret,
)
from orchestrators.setup_orchestrator import SetupOrchestrator
from plans.set_authorized_key import SetAuthorizedKeyPlan
from plans.set_local_password import SetLocalPasswordPlan


class AcesAccountCredentialError(RuntimeError):
    """Bounded failure for one authored-account credential realization."""


@dataclass(frozen=True)
class AcesAccountCredentialOps:
    """Injectable Secret Manager operations for authored-account credentials."""

    ensure_password: Callable[[int, str, str, str], tuple[str, str]]
    ensure_public_key: Callable[[int, str, str], tuple[str, str]]
    delete: Callable[[int, str, str, str], None]
    execution_builder: Callable[..., GuestExecutionContext] = build_guest_execution_context
    orchestrator_factory: Callable[[Executor], SetupOrchestrator] = SetupOrchestrator


def default_account_credential_ops() -> AcesAccountCredentialOps:
    """Return the production authored-account Secret Manager bindings."""
    return AcesAccountCredentialOps(
        ensure_password=ensure_aces_account_password_secret,
        ensure_public_key=ensure_aces_account_public_key_secret,
        delete=delete_aces_account_secret,
    )


def _run_password_strategy(
    orchestrator: SetupOrchestrator,
    execution: GuestExecutionContext,
    range_id: int,
    instance_key: str,
    platform: str,
    account: AcesPlanAccount,
    secret_ops: AcesAccountCredentialOps,
) -> None:
    """Install one authored account's password through the setup orchestrator."""
    _secret_ref, password = secret_ops.ensure_password(
        range_id, instance_key, account.username, account.password_strength
    )
    plan = SetLocalPasswordPlan(platform=platform)
    context = plan.get_context({"rdp_username": account.username, "rdp_password": password})
    result = orchestrator.orchestrate(execution.target, plan, context, execution.document_name)
    if not result.success:
        raise RuntimeError("password setup plan did not complete")


def _run_public_key_strategy(
    orchestrator: SetupOrchestrator,
    execution: GuestExecutionContext,
    range_id: int,
    instance_key: str,
    platform: str,
    account: AcesPlanAccount,
    secret_ops: AcesAccountCredentialOps,
) -> None:
    """Install one authored account's public key through the setup orchestrator."""
    _secret_ref, public_key = secret_ops.ensure_public_key(range_id, instance_key, account.username)
    plan = SetAuthorizedKeyPlan(platform=platform)
    context = plan.get_context({"account_username": account.username, "account_public_key": public_key})
    result = orchestrator.orchestrate(execution.target, plan, context, execution.document_name)
    if not result.success:
        raise RuntimeError("public-key setup plan did not complete")


def install_instance_account_credentials(
    *,
    range_id: int,
    instance_key: str,
    platform: str,
    instance_output: dict[str, Any],
    accounts: Iterable[AcesPlanAccount],
    secret_ops: AcesAccountCredentialOps,
) -> None:
    """Install and verify every enabled authored-account credential on one guest."""
    enabled_accounts = tuple(account for account in accounts if not account.disabled)
    if not enabled_accounts:
        return
    try:
        execution = secret_ops.execution_builder(instance_output, provider="gcp", os_type=platform, role="aces-node")
    except Exception:
        raise AcesAccountCredentialError(
            f"failed to establish credential setup channel for instance {instance_key!r}"
        ) from None
    try:
        try:
            execution.wait_for_ready(timeout_seconds=300)
        except Exception:
            raise AcesAccountCredentialError(
                f"failed to establish credential setup channel for instance {instance_key!r}"
            ) from None
        orchestrator = secret_ops.orchestrator_factory(execution.executor)
        for account in enabled_accounts:
            try:
                if account.auth_method == "password":
                    _run_password_strategy(
                        orchestrator, execution, range_id, instance_key, platform, account, secret_ops
                    )
                elif account.auth_method == "publickey":
                    _run_public_key_strategy(
                        orchestrator, execution, range_id, instance_key, platform, account, secret_ops
                    )
                # Defense in depth; the plan parser rejects this first.
                else:
                    raise ValueError("unsupported authored-account credential strategy")
            except Exception:
                raise AcesAccountCredentialError(
                    f"failed to realize {account.auth_method} credential for account "
                    f"{account.username!r} on instance {instance_key!r}"
                ) from None
    finally:
        execution.close()


def delete_instance_account_credentials(
    range_id: int,
    instance_key: str,
    accounts: Iterable[AcesPlanAccount],
    secret_ops: AcesAccountCredentialOps,
) -> None:
    """Delete every deterministic credential secret reconstructible from the plan."""
    for account in accounts:
        secret_ops.delete(range_id, instance_key, account.username, account.auth_method)
