"""Fresh-account leftover detection and recovery for AWS tenant standup.

Issue #1639 friction point 3, which is the automated bootstrap-CLI leftover
recovery deferred from #1472 to #1618. Implements the design record in
``docs/architecture/aws-dirty-account-lifecycle-preflight-1472.md``.

A previously-deployed AWS environment that was incompletely torn down leaves
control-plane residue whose Terraform state is gone (Budgets, RDS parameter
groups and event subscriptions, EventBridge Scheduler schedules, ECR repos, KMS
aliases, Network Firewall rule groups, Portal SSM parameters). On the next
``terraform apply`` each collides and fails the run one resource at a time. This
module surfaces them all up front (read-only detection) and, with an explicit
opt-in, sweeps the replaceable ones.

Safety contract (from the #1472 design):

- Terraform state is authoritative; this is a NARROW FALLBACK for state-absent,
  replaceable control-plane residue, not a replacement for ``terraform destroy``.
- Detection is READ-ONLY. Mutation requires an explicit ``sweep`` action AND an
  interactive confirmation (or ``--yes``); a non-TTY alone never authorizes it.
- A matching name is a lookup key, not ownership proof. A resource is swept only
  when the strongest available evidence agrees: for taggable resources, the
  provider ``default_tags`` (``Project=shifter``, ``Environment=<env>``,
  ``ManagedBy=terraform``); for the few tagless classes, the canonical name /
  path prefix scoped to the resolved account and region. Missing or conflicting
  evidence fails closed (reported, never deleted).
- Data-bearing resources are never touched. There is deliberately NO handler for
  KMS keys, S3 buckets, RDS instances/snapshots, Secrets Manager values, or SSM
  SecureString values, so this tool structurally cannot delete them. KMS
  *aliases* (pointers, not keys) and SSM parameter *names* below the exact portal
  prefix are safe; values are never read.
- Every AWS call is an argv list through ``run_cmd`` (no ``shell=True``); reports
  carry names/ids and the account/env/region only, never secret values or raw
  AWS response bodies.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from enum import StrEnum

from bootstrap_core import confirm, error, get_aws_account_id, info, run_cmd, subheader, success, warn

AWS_REGION = "us-east-2"

# Bounded wait for the asynchronous Network Firewall rule-group delete to
# converge before the sweep reports success (delete-rule-group returns while the
# group is still DELETING). ~2.5 minutes total; a still-present group after that
# is reported FAILED so the idempotent sweep can be re-run.
_NFW_DELETE_POLL_ATTEMPTS = 30
_NFW_DELETE_POLL_DELAY_SECONDS = 5

# Provider default_tags that mark a resource as Terraform-owned for an env.
_OWNER_PROJECT = ("Project", "shifter")
_OWNER_MANAGED_BY = ("ManagedBy", "terraform")


class Action(StrEnum):
    """The per-resource outcome recorded in a recovery report."""

    ABSENT = "absent"  # nothing found for this class
    WOULD_DELETE = "would-delete"  # owned + safe; detection-only run
    DELETED = "deleted"  # swept
    BLOCKED = "blocked"  # matched a name but ownership evidence failed closed
    FAILED = "failed"  # AWS call errored during a sweep


@dataclass(frozen=True)
class LeftoverFinding:
    """One detected residual resource (or the absence of any for a class)."""

    resource_class: str
    identifier: str
    action: Action
    detail: str = ""


@dataclass
class RecoveryReport:
    """Detection/sweep results for one account + environment."""

    account_id: str
    environment: str
    region: str
    findings: list[LeftoverFinding] = field(default_factory=list)

    @property
    def actionable(self) -> list[LeftoverFinding]:
        """Findings that represent real residue (present, not ``absent``)."""
        return [f for f in self.findings if f.action is not Action.ABSENT]

    @property
    def blocked(self) -> list[LeftoverFinding]:
        """Name-matched residue that failed the ownership check (never swept)."""
        return [f for f in self.findings if f.action is Action.BLOCKED]

    @property
    def failures(self) -> list[LeftoverFinding]:
        """Sweep operations that errored."""
        return [f for f in self.findings if f.action is Action.FAILED]

    def render(self) -> str:
        """Render a bounded, value-free report grouped by resource class."""
        symbol = {
            Action.ABSENT: "[ ok ]",
            Action.WOULD_DELETE: "[find]",
            Action.DELETED: "[ del]",
            Action.BLOCKED: "[BLOCK]",
            Action.FAILED: "[FAIL]",
        }
        lines = [
            f"Account leftover recovery: account={self.account_id} env={self.environment} region={self.region}",
        ]
        for f in self.findings:
            suffix = f" ({f.detail})" if f.detail else ""
            lines.append(f"  {symbol[f.action]} {f.resource_class}: {f.identifier}{suffix}")
        would_delete = sum(1 for f in self.findings if f.action is Action.WOULD_DELETE)
        deleted = sum(1 for f in self.findings if f.action is Action.DELETED)
        parts: list[str] = []
        if would_delete:
            parts.append(f"{would_delete} leftover(s)")
        if deleted:
            parts.append(f"{deleted} deleted")
        if self.blocked:
            parts.append(f"{len(self.blocked)} blocked (ownership unproven)")
        if self.failures:
            parts.append(f"{len(self.failures)} check(s) failed")
        lines.append(f"Result: {', '.join(parts) if parts else 'clean'}")
        return "\n".join(lines)


class AwsQueryError(RuntimeError):
    """A read-only AWS discovery query failed, so its result is unknown.

    Distinguishes a genuine failure (permissions, throttling, wrong region) from
    an empty-but-successful listing, so a failed check is never silently reported
    as a clean/absent resource, i.e. a false "the account is clean" certification
    (codex review, #1639).
    """


def _aws_json(args: list[str], profile: str) -> dict | list:
    """Run a read-only ``aws ... --output json`` query and parse the result.

    Raises :class:`AwsQueryError` on a non-zero exit or unparseable output. A
    successful-but-empty listing returns valid empty JSON (for example
    ``{"Budgets": []}``), so "nothing here" and "could not check" are never
    conflated: an errored discovery must surface as a failed check, not as
    "absent".
    """
    cmd = ["aws", "--profile", profile, "--region", AWS_REGION, *args, "--output", "json"]
    result = run_cmd(cmd, capture=True, check=False, profile=None)
    if result is None or result.returncode != 0:
        rc = getattr(result, "returncode", "n/a")
        raise AwsQueryError(f"`aws {' '.join(args)}` failed (exit {rc})")
    if not result.stdout.strip():
        raise AwsQueryError(f"`aws {' '.join(args)}` returned no output")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise AwsQueryError(f"`aws {' '.join(args)}` returned unparseable JSON") from exc


def _name_matches_env(name: str, environment: str) -> bool:
    """True when a resource name follows the canonical Terraform env naming.

    Resources are named from ``${var.name_prefix}`` as ``shifter-<env>-*`` or
    ``<env>-*`` (for example ``shifter-proof-s3-cost-alert``, ``proof-portal-*``).
    A name match is a lookup key only; ownership is confirmed separately by tags.
    """
    return name.startswith((f"shifter-{environment}-", f"{environment}-"))


def _tags_owned_by_env(tags: dict[str, str], environment: str) -> bool:
    """True when the provider default_tags mark this resource as env-owned."""
    return (
        tags.get(_OWNER_PROJECT[0]) == _OWNER_PROJECT[1]
        and tags.get(_OWNER_MANAGED_BY[0]) == _OWNER_MANAGED_BY[1]
        and tags.get("Environment") == environment
    )


def _tag_list_to_dict(tag_list: list[dict] | None) -> dict[str, str]:
    """Normalize the ``[{"Key":..,"Value":..}]`` tag shape to a dict."""
    return {t["Key"]: t.get("Value", "") for t in (tag_list or []) if "Key" in t}


class ResourceHandler:
    """Base class for one residual resource class.

    Subclasses implement :meth:`detect` (read-only) and :meth:`delete` (mutation).
    The base ``detect`` templates the taggable-resource flow: list, resolve tags,
    classify as owned (``WOULD_DELETE``) or name-matched-but-unowned (``BLOCKED``).
    Tagless subclasses override :meth:`detect` entirely.
    """

    resource_class = "resource"

    def detect(self, environment: str, account_id: str, profile: str) -> list[LeftoverFinding]:
        raise NotImplementedError

    def delete(self, finding: LeftoverFinding, profile: str, dry_run: bool) -> Action:
        raise NotImplementedError

    def _absent(self) -> list[LeftoverFinding]:
        return [LeftoverFinding(self.resource_class, "(none)", Action.ABSENT)]


class _TaggedHandler(ResourceHandler):
    """Handler for a taggable resource classified by canonical NAME plus ownership.

    Per the #1472 design, a matching name is a lookup key, not ownership proof:
    a resource is deleted only when its identity is derived from the canonical
    Terraform naming (``shifter-<env>-*`` / ``<env>-*``) AND the provider
    ``default_tags`` confirm the environment owns it. A canonically-named
    resource whose tags do not agree (missing, foreign, or unreadable) is
    surfaced as BLOCKED for manual review, never silently dropped and never
    deleted. A resource that does not match the canonical name is not a candidate.
    """

    def _list(self, profile: str) -> list[tuple[str, str]]:
        """Return ``(name, arn)`` pairs for every resource of this class."""
        raise NotImplementedError

    def _fetch_tags(self, arn: str, profile: str) -> dict[str, str]:
        raise NotImplementedError

    def _delete_cmd(self, identifier: str) -> list[str]:
        raise NotImplementedError

    def _name_matches(self, name: str, environment: str) -> bool:
        """Canonical env naming. Override for a resource-specific pattern."""
        return _name_matches_env(name, environment)

    def _finding_identifier(self, name: str, _arn: str) -> str:
        """What to record/delete by. Name for most; overridden to ARN where the
        delete API addresses the resource by ARN (Network Firewall)."""
        return name

    def detect(self, environment: str, account_id: str, profile: str) -> list[LeftoverFinding]:
        # A failed _list() raises AwsQueryError and propagates to detect_leftovers,
        # which records the whole class as a failed check (never silently "absent").
        findings: list[LeftoverFinding] = []
        for name, arn in self._list(profile):
            if not self._name_matches(name, environment):
                continue  # not a canonical env-named resource -> not a candidate
            identifier = self._finding_identifier(name, arn)
            try:
                tags = self._fetch_tags(arn, profile)
            except AwsQueryError:
                # Ownership cannot be read -> fail closed: surface it, never delete.
                findings.append(
                    LeftoverFinding(self.resource_class, identifier, Action.BLOCKED, "ownership check failed")
                )
                continue
            if _tags_owned_by_env(tags, environment):
                findings.append(LeftoverFinding(self.resource_class, identifier, Action.WOULD_DELETE))
            else:
                # Canonical name but ownership evidence disagrees -> block, never drop.
                findings.append(
                    LeftoverFinding(
                        self.resource_class,
                        identifier,
                        Action.BLOCKED,
                        "canonical name but ownership tags do not agree",
                    )
                )
        return findings or self._absent()

    def delete(self, finding: LeftoverFinding, profile: str, dry_run: bool) -> Action:
        cmd = ["aws", "--profile", profile, "--region", AWS_REGION, *self._delete_cmd(finding.identifier)]
        result = run_cmd(cmd, dry_run=dry_run, check=False, profile=None)
        if dry_run:
            return Action.WOULD_DELETE
        return Action.DELETED if result is not None and result.returncode == 0 else Action.FAILED


class RdsParameterGroupHandler(_TaggedHandler):
    """RDS DB parameter groups (``modules/portal/rds``)."""

    resource_class = "rds-db-parameter-group"

    def _list(self, profile: str) -> list[tuple[str, str]]:
        data = _aws_json(["rds", "describe-db-parameter-groups"], profile)
        groups = (data or {}).get("DBParameterGroups", []) if isinstance(data, dict) else []
        # The default.* AWS-managed families are never ours and cannot be deleted.
        return [
            (g["DBParameterGroupName"], g["DBParameterGroupArn"])
            for g in groups
            if not g["DBParameterGroupName"].startswith("default.")
        ]

    def _fetch_tags(self, arn: str, profile: str) -> dict[str, str]:
        data = _aws_json(["rds", "list-tags-for-resource", "--resource-name", arn], profile)
        return _tag_list_to_dict((data or {}).get("TagList") if isinstance(data, dict) else None)

    def _delete_cmd(self, identifier: str) -> list[str]:
        return ["rds", "delete-db-parameter-group", "--db-parameter-group-name", identifier]


class RdsEventSubscriptionHandler(_TaggedHandler):
    """RDS event subscriptions (``modules/portal/backup-alerts``)."""

    resource_class = "rds-event-subscription"

    def _list(self, profile: str) -> list[tuple[str, str]]:
        data = _aws_json(["rds", "describe-event-subscriptions"], profile)
        subs = (data or {}).get("EventSubscriptionsList", []) if isinstance(data, dict) else []
        return [(s["CustSubscriptionId"], s["EventSubscriptionArn"]) for s in subs]

    def _fetch_tags(self, arn: str, profile: str) -> dict[str, str]:
        data = _aws_json(["rds", "list-tags-for-resource", "--resource-name", arn], profile)
        return _tag_list_to_dict((data or {}).get("TagList") if isinstance(data, dict) else None)

    def _delete_cmd(self, identifier: str) -> list[str]:
        return ["rds", "delete-event-subscription", "--subscription-name", identifier]


class SchedulerScheduleHandler(_TaggedHandler):
    """EventBridge Scheduler schedules (RDS rotation reminder, etc.)."""

    resource_class = "scheduler-schedule"

    def _list(self, profile: str) -> list[tuple[str, str]]:
        data = _aws_json(["scheduler", "list-schedules"], profile)
        schedules = (data or {}).get("Schedules", []) if isinstance(data, dict) else []
        return [(s["Name"], s["Arn"]) for s in schedules]

    def _fetch_tags(self, arn: str, profile: str) -> dict[str, str]:
        data = _aws_json(["scheduler", "list-tags-for-resource", "--resource-arn", arn], profile)
        return _tag_list_to_dict((data or {}).get("Tags") if isinstance(data, dict) else None)

    def _delete_cmd(self, identifier: str) -> list[str]:
        return ["scheduler", "delete-schedule", "--name", identifier]


class EcrRepositoryHandler(_TaggedHandler):
    """ECR repositories. Images are rebuilt by the deploy, so the repo is
    replaceable control-plane residue; ``--force`` covers a repo left with
    images from the prior tenant."""

    resource_class = "ecr-repository"

    def _list(self, profile: str) -> list[tuple[str, str]]:
        data = _aws_json(["ecr", "describe-repositories"], profile)
        repos = (data or {}).get("repositories", []) if isinstance(data, dict) else []
        return [(r["repositoryName"], r["repositoryArn"]) for r in repos]

    def _fetch_tags(self, arn: str, profile: str) -> dict[str, str]:
        data = _aws_json(["ecr", "list-tags-for-resource", "--resource-arn", arn], profile)
        return _tag_list_to_dict((data or {}).get("tags") if isinstance(data, dict) else None)

    def _delete_cmd(self, identifier: str) -> list[str]:
        return ["ecr", "delete-repository", "--repository-name", identifier, "--force"]


class NetworkFirewallRuleGroupHandler(_TaggedHandler):
    """AWS Network Firewall rule groups. Deletes are asynchronous and
    dependency-heavy; the caller drains the firewall policy first via the normal
    teardown. Reported/deleted by tag ownership."""

    resource_class = "networkfirewall-rule-group"

    def _list(self, profile: str) -> list[tuple[str, str]]:
        data = _aws_json(["network-firewall", "list-rule-groups"], profile)
        groups = (data or {}).get("RuleGroups", []) if isinstance(data, dict) else []
        return [(g["Name"], g["Arn"]) for g in groups]

    def _fetch_tags(self, arn: str, profile: str) -> dict[str, str]:
        data = _aws_json(["network-firewall", "list-tags-for-resource", "--resource-arn", arn], profile)
        return _tag_list_to_dict((data or {}).get("Tags") if isinstance(data, dict) else None)

    def _delete_cmd(self, identifier: str) -> list[str]:
        # Rule groups are addressed by ARN for delete; identifier here is the ARN.
        return ["network-firewall", "delete-rule-group", "--rule-group-arn", identifier]

    def _finding_identifier(self, name: str, arn: str) -> str:
        # Delete addresses rule groups by ARN, so carry the ARN as the identifier;
        # the canonical-name check in the base handler still runs against the name.
        return arn

    def delete(self, finding: LeftoverFinding, profile: str, dry_run: bool) -> Action:
        # Network Firewall deletes are ASYNCHRONOUS: delete-rule-group only starts
        # the delete and the group lingers in DELETING for a while. Returning
        # DELETED immediately would let a following apply collide with a
        # still-present group (#1639 codex review), so wait for it to actually go
        # away before reporting success.
        arn = finding.identifier
        cmd = [
            "aws",
            "--profile",
            profile,
            "--region",
            AWS_REGION,
            "network-firewall",
            "delete-rule-group",
            "--rule-group-arn",
            arn,
        ]
        result = run_cmd(cmd, dry_run=dry_run, check=False, profile=None)
        if dry_run:
            return Action.WOULD_DELETE
        if result is None or result.returncode != 0:
            return Action.FAILED
        return self._await_deletion(arn, profile)

    def _await_deletion(self, arn: str, profile: str) -> Action:
        """Poll until the rule group is CONFIRMED gone.

        describe-rule-group returns success while the group still exists
        (DELETING), a not-found error once it is actually gone, and other errors
        transiently (throttling, blips). Only a not-found concludes DELETED; a
        transient error keeps polling, so an API blip is never mistaken for a
        completed delete (#1639 codex review). Still present after the bounded
        wait -> FAILED (the idempotent sweep can be re-run).
        """
        for _ in range(_NFW_DELETE_POLL_ATTEMPTS):
            if self._describe_state(arn, profile) == "gone":
                return Action.DELETED
            time.sleep(_NFW_DELETE_POLL_DELAY_SECONDS)
        return Action.FAILED

    def _describe_state(self, arn: str, profile: str) -> str:
        """Return ``present`` | ``gone`` | ``unknown`` for a rule group.

        ``gone`` only when the describe error is specifically a not-found; any
        other non-zero result is ``unknown`` (transient) so the caller retries
        rather than concluding the group was deleted.
        """
        cmd = [
            "aws",
            "--profile",
            profile,
            "--region",
            AWS_REGION,
            "network-firewall",
            "describe-rule-group",
            "--rule-group-arn",
            arn,
            "--output",
            "json",
        ]
        result = run_cmd(cmd, capture=True, check=False, profile=None)
        if result is not None and result.returncode == 0:
            return "present"
        stderr = ((getattr(result, "stderr", "") or "") if result is not None else "").lower()
        if "resourcenotfoundexception" in stderr or "does not exist" in stderr or "not found" in stderr:
            return "gone"
        return "unknown"


class KmsAliasHandler(ResourceHandler):
    """KMS *aliases* (pointers), scoped by the canonical ``alias/shifter-<env>``
    and ``alias/<env>-`` name prefixes. Aliases are tagless; deleting an alias
    never deletes the underlying key, so no data is at risk. AWS-managed
    ``alias/aws/*`` aliases are excluded."""

    resource_class = "kms-alias"

    def _prefixes(self, environment: str) -> tuple[str, ...]:
        return (f"alias/shifter-{environment}-", f"alias/{environment}-", f"alias/ecr-{environment}-")

    def detect(self, environment: str, account_id: str, profile: str) -> list[LeftoverFinding]:
        data = _aws_json(["kms", "list-aliases"], profile)
        aliases = (data or {}).get("Aliases", []) if isinstance(data, dict) else []
        prefixes = self._prefixes(environment)
        findings = [
            LeftoverFinding(self.resource_class, a["AliasName"], Action.WOULD_DELETE)
            for a in aliases
            if not a["AliasName"].startswith("alias/aws/") and a["AliasName"].startswith(prefixes)
        ]
        return findings or self._absent()

    def delete(self, finding: LeftoverFinding, profile: str, dry_run: bool) -> Action:
        cmd = [
            "aws",
            "--profile",
            profile,
            "--region",
            AWS_REGION,
            "kms",
            "delete-alias",
            "--alias-name",
            finding.identifier,
        ]
        result = run_cmd(cmd, dry_run=dry_run, check=False, profile=None)
        if dry_run:
            return Action.WOULD_DELETE
        return Action.DELETED if result is not None and result.returncode == 0 else Action.FAILED


class PortalSsmParameterHandler(ResourceHandler):
    """Portal SSM parameters below the EXACT ``/shifter/<env>/portal/`` prefix.

    Names only: ``get-parameters-by-path`` lists names without decryption, and
    delete is by name. The AMI prefix (``/shifter/ami/*``) and every other
    environment's prefix are outside this path and never touched."""

    resource_class = "ssm-portal-parameter"

    def _path(self, environment: str) -> str:
        return f"/shifter/{environment}/portal/"

    def detect(self, environment: str, account_id: str, profile: str) -> list[LeftoverFinding]:
        path = self._path(environment)
        # get-parameters-by-path lists NAMES (WithDecryption is never passed).
        data = _aws_json(["ssm", "get-parameters-by-path", "--path", path, "--recursive"], profile)
        params = (data or {}).get("Parameters", []) if isinstance(data, dict) else []
        findings = [
            LeftoverFinding(self.resource_class, p["Name"], Action.WOULD_DELETE)
            for p in params
            if p["Name"].startswith(path)  # defense-in-depth: exact prefix only
        ]
        return findings or self._absent()

    def delete(self, finding: LeftoverFinding, profile: str, dry_run: bool) -> Action:
        # Fail closed: never delete a name outside the portal prefix even if a
        # finding is hand-constructed. The prefix is re-derived from the name.
        if "/portal/" not in finding.identifier or not finding.identifier.startswith("/shifter/"):
            return Action.BLOCKED
        cmd = [
            "aws",
            "--profile",
            profile,
            "--region",
            AWS_REGION,
            "ssm",
            "delete-parameter",
            "--name",
            finding.identifier,
        ]
        result = run_cmd(cmd, dry_run=dry_run, check=False, profile=None)
        if dry_run:
            return Action.WOULD_DELETE
        return Action.DELETED if result is not None and result.returncode == 0 else Action.FAILED


class BudgetHandler(ResourceHandler):
    """AWS Budgets (account/global service). Budgets are effectively tagless for
    ownership here, so a budget is only ever *reported* by canonical name prefix
    and left BLOCKED rather than auto-deleted: a wrong delete removes a real cost
    guardrail, and name alone is not ownership proof (per the #1472 design)."""

    resource_class = "budget"

    def detect(self, environment: str, account_id: str, profile: str) -> list[LeftoverFinding]:
        data = _aws_json(["budgets", "describe-budgets", "--account-id", account_id], profile)
        budgets = (data or {}).get("Budgets", []) if isinstance(data, dict) else []
        prefix = f"shifter-{environment}-"
        findings = [
            LeftoverFinding(
                self.resource_class,
                b["BudgetName"],
                Action.BLOCKED,
                detail="name match only; delete manually to avoid removing a real budget",
            )
            for b in budgets
            if b.get("BudgetName", "").startswith((prefix, f"{environment}-"))
        ]
        return findings or self._absent()

    def delete(self, finding: LeftoverFinding, profile: str, dry_run: bool) -> Action:
        # Deliberately never auto-deletes; detection reports it for manual action.
        return Action.BLOCKED


# Ordered so dependency-sensitive classes are swept before what they reference
# (per the #1472 design: consumers before groups; schedule before its role;
# event subscription before its topic/key teardown; SSM cleanup last).
HANDLERS: list[ResourceHandler] = [
    EcrRepositoryHandler(),
    NetworkFirewallRuleGroupHandler(),
    SchedulerScheduleHandler(),
    RdsEventSubscriptionHandler(),
    RdsParameterGroupHandler(),
    KmsAliasHandler(),
    PortalSsmParameterHandler(),
    BudgetHandler(),
]


def detect_leftovers(
    environment: str, profile: str, *, handlers: list[ResourceHandler] | None = None
) -> RecoveryReport:
    """Read-only detection of state-absent residue for ``environment``."""
    account_id = get_aws_account_id(profile)
    report = RecoveryReport(account_id=account_id, environment=environment, region=AWS_REGION)
    for handler in handlers or HANDLERS:
        try:
            report.findings.extend(handler.detect(environment, account_id, profile))
        except AwsQueryError as exc:
            # A failed discovery is recorded as a FAILED check, never dropped or
            # silently treated as "absent" (which would false-certify the account
            # as clean). The orchestrator refuses to sweep when any check failed.
            report.findings.append(LeftoverFinding(handler.resource_class, "(check failed)", Action.FAILED, str(exc)))
    return report


def sweep_leftovers(
    report: RecoveryReport,
    profile: str,
    *,
    dry_run: bool,
    handlers: list[ResourceHandler] | None = None,
) -> RecoveryReport:
    """Delete the ``would-delete`` findings; leave ``blocked`` ones untouched.

    Returns a new report reflecting the post-sweep actions. Idempotent: an
    already-absent resource deletes cleanly, so a partial run can be re-run.
    """
    by_class = {h.resource_class: h for h in (handlers or HANDLERS)}
    swept: list[LeftoverFinding] = []
    for finding in report.findings:
        if finding.action is not Action.WOULD_DELETE:
            swept.append(finding)
            continue
        handler = by_class.get(finding.resource_class)
        if handler is None:
            swept.append(LeftoverFinding(finding.resource_class, finding.identifier, Action.BLOCKED, "no handler"))
            continue
        outcome = handler.delete(finding, profile, dry_run)
        swept.append(LeftoverFinding(finding.resource_class, finding.identifier, outcome, finding.detail))
    return RecoveryReport(report.account_id, report.environment, report.region, swept)


def tenant_is_live(environment: str, profile: str) -> bool:
    """True when a running tenant still occupies ``environment`` in this account.

    Leftover recovery targets a TORN-DOWN account whose Terraform state is gone
    (the #1472 narrow fallback). If the tenant is still live, everything that
    matches the environment naming is the RUNNING tenant's, not an orphan, and
    must never be presented as sweepable, so the tool refuses. A portal ASG
    carrying instances, or an RDS instance for the environment, is a strong
    "this is not a fresh account" signal.

    Fails CLOSED: if the liveness queries cannot be evaluated (an API error, so
    :func:`_aws_json` raises :class:`AwsQueryError`), the account is treated as
    live so a destructive sweep is never authorized on an account we cannot
    confirm is torn down. An empty account returns valid empty lists, so a
    genuinely clean account is correctly treated as not-live.
    """
    try:
        asgs = _aws_json(["autoscaling", "describe-auto-scaling-groups"], profile)
        dbs = _aws_json(["rds", "describe-db-instances"], profile)
    except AwsQueryError:
        return True  # cannot confirm -> fail closed

    asg_prefixes = (f"{environment}-portal", f"shifter-{environment}")
    for asg in asgs.get("AutoScalingGroups", []) if isinstance(asgs, dict) else []:
        if asg.get("AutoScalingGroupName", "").startswith(asg_prefixes) and asg.get("Instances"):
            return True

    db_prefixes = (f"{environment}-", f"shifter-{environment}")
    for db in dbs.get("DBInstances", []) if isinstance(dbs, dict) else []:
        if db.get("DBInstanceIdentifier", "").startswith(db_prefixes):
            return True
    return False


def _perform_sweep(report: RecoveryReport, environment: str, profile: str, *, dry_run: bool) -> RecoveryReport:
    """Confirm and execute the sweep of the owned (would-delete) findings.

    Explicit destructive confirmation names the account so an operator cannot
    sweep the wrong one; confirm() returns True under --yes but the --sweep flag
    is still the required explicit destructive intent.
    """
    deletable = [f for f in report.findings if f.action is Action.WOULD_DELETE]
    if not deletable:
        info("Nothing owned to sweep (only blocked/absent findings).")
        return report

    if not dry_run and not confirm(
        f"Delete {len(deletable)} owned leftover(s) in account {report.account_id} ({environment})?"
    ):
        warn("Sweep declined; nothing deleted.")
        return report

    result = sweep_leftovers(report, profile, dry_run=dry_run)
    info(result.render())
    if result.failures:
        error(f"{len(result.failures)} deletion(s) failed; re-run to retry (deletes are idempotent).")
    else:
        success("Sweep complete." if not dry_run else "Dry-run complete; no resources deleted.")
    return result


def account_recovery(environment: str, profile: str, *, sweep: bool, dry_run: bool) -> RecoveryReport:
    """CLI entrypoint: detect residue, print the report, optionally sweep.

    Detection always runs and is read-only. The sweep is gated on an explicit
    ``--sweep`` AND :func:`bootstrap_core.confirm` (which honors ``--yes`` but
    still requires the explicit sweep intent), so a non-TTY alone never deletes.

    Refuses entirely when a live tenant is present (issue #1639): recovery is only
    for a torn-down account, so it must not treat a running tenant's resources as
    leftovers. Use ``terraform destroy`` to tear down a live tenant first.
    """
    subheader(f"Account leftover recovery: {environment} ({AWS_REGION})")

    if tenant_is_live(environment, profile):
        warn(
            f"A live (or unverifiable) tenant is present in {environment}; refusing. Leftover recovery is only "
            "for a torn-down account whose Terraform state is gone. Run `terraform destroy` for a live tenant."
        )
        return RecoveryReport(get_aws_account_id(profile), environment, AWS_REGION, [])

    report = detect_leftovers(environment, profile)
    info(report.render())

    if report.failures:
        # A discovery call failed, so detection is incomplete: the account cannot
        # be certified clean and a sweep would run on a partial picture. Fail loud
        # and refuse to sweep (#1639 codex review).
        warn(
            f"{len(report.failures)} discovery check(s) failed; detection is incomplete and the account cannot be "
            "certified clean. Refusing to sweep. Fix access/credentials and re-run."
        )
        return report

    if not report.actionable:
        success("No state-absent leftovers detected; the account is clean for a standup.")
        return report
    if report.blocked:
        warn(f"{len(report.blocked)} resource(s) matched by name but not ownership; review and remove them manually.")

    if not sweep:
        info("Detection only. Re-run with --sweep to delete the owned leftovers (blocked ones are never auto-deleted).")
        return report

    return _perform_sweep(report, environment, profile, dry_run=dry_run)
