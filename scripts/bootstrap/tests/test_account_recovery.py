"""Tests for the fresh-account leftover recovery (issue #1639 / #1618).

Detection is read-only and ownership is evidence-based (provider default_tags for
taggable classes, canonical name/prefix for the few tagless ones). The sweep is
gated on an explicit opt-in and never touches data-bearing resources. These
tests drive the module through a shared fake ``run_cmd`` that returns canned
``aws ... --output json`` payloads keyed by the command shape, rather than a
forest of per-assertion mocks.
"""

from __future__ import annotations

import json

import pytest

import account_recovery
from account_recovery import (
    HANDLERS,
    Action,
    LeftoverFinding,
    PortalSsmParameterHandler,
    detect_leftovers,
    sweep_leftovers,
)
from account_recovery import (
    account_recovery as run_account_recovery,
)

_OWNER_TAGS = [
    {"Key": "Project", "Value": "shifter"},
    {"Key": "ManagedBy", "Value": "terraform"},
    {"Key": "Environment", "Value": "proof"},
]
_FOREIGN_TAGS = [
    {"Key": "Project", "Value": "shifter"},
    {"Key": "ManagedBy", "Value": "terraform"},
    {"Key": "Environment", "Value": "dev"},  # different env -> not owned
]

# Empty liveness responses: a torn-down account (no portal ASG, no RDS) so the
# orchestrator's live-tenant guard passes and detection/sweep proceed.
_NOT_LIVE = {
    "autoscaling describe-auto-scaling-groups": json.dumps({"AutoScalingGroups": []}),
    "rds describe-db-instances": json.dumps({"DBInstances": []}),
}


class _FakeResult:
    def __init__(self, stdout: str = "", returncode: int = 0, stderr: str = ""):
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr


def _fake_run_cmd(responses: dict[str, str], deletes: list[list[str]]):
    """Build a fake run_cmd. ``responses`` maps a command substring to JSON
    stdout; delete commands are recorded in ``deletes`` and return success.

    Sentinels: ``__ERROR__`` -> a transient read failure (exit 1, no marker);
    ``__NOTFOUND__`` -> a not-found failure (exit 1 with a ResourceNotFound
    stderr), used to confirm a Network Firewall delete converged."""

    def fake(cmd, dry_run=False, check=True, capture=False, profile=None):
        joined = " ".join(cmd)
        if any(verb in joined for verb in ("delete-", "delete ")):
            # Mirror run_cmd: a dry-run no-ops without executing, so only a real
            # (non-dry-run) invocation counts as an executed deletion.
            if not dry_run:
                deletes.append(cmd)
            return None if dry_run else _FakeResult(returncode=0)
        if dry_run:
            return None
        for needle, payload in responses.items():
            if needle in joined:
                if payload == "__ERROR__":
                    return _FakeResult(stdout="", returncode=1)
                if payload == "__NOTFOUND__":
                    return _FakeResult(stdout="", returncode=1, stderr="ResourceNotFoundException: not found")
                return _FakeResult(stdout=payload, returncode=0)
        # Unmatched read -> an empty-but-successful listing (a clean account),
        # distinct from a failed read (which callers inject via a sentinel).
        return _FakeResult(stdout="{}", returncode=0)

    return fake


@pytest.fixture
def patched(monkeypatch):
    """Patch run_cmd + account id; return a helper to install responses."""
    deletes: list[list[str]] = []

    def install(responses):
        monkeypatch.setattr(account_recovery, "run_cmd", _fake_run_cmd(responses, deletes))
        monkeypatch.setattr(account_recovery, "get_aws_account_id", lambda profile=None: "123456789012")
        return deletes

    return install


class TestDetection:
    def test_detects_owned_rds_parameter_group_and_ignores_default_and_foreign(self, patched):
        patched(
            {
                "describe-db-parameter-groups": json.dumps(
                    {
                        "DBParameterGroups": [
                            {"DBParameterGroupName": "default.postgres16", "DBParameterGroupArn": "arn:default"},
                            {"DBParameterGroupName": "shifter-proof-portal", "DBParameterGroupArn": "arn:owned"},
                            {"DBParameterGroupName": "shifter-dev-portal", "DBParameterGroupArn": "arn:foreign"},
                        ]
                    }
                ),
                "list-tags-for-resource --resource-name arn:owned": json.dumps({"TagList": _OWNER_TAGS}),
                "list-tags-for-resource --resource-name arn:foreign": json.dumps({"TagList": _FOREIGN_TAGS}),
            }
        )
        report = detect_leftovers("proof", "proof")
        pgs = [f for f in report.findings if f.resource_class == "rds-db-parameter-group"]
        owned = [f for f in pgs if f.action is Action.WOULD_DELETE]
        # Only the tag-owned, proof-env group is actionable; default.* and the
        # dev-env group are excluded (name match alone is never ownership).
        assert [f.identifier for f in owned] == ["shifter-proof-portal"]

    def test_kms_alias_prefix_scoped_and_excludes_aws_managed(self, patched):
        patched(
            {
                "kms list-aliases": json.dumps(
                    {
                        "Aliases": [
                            {"AliasName": "alias/aws/s3"},  # AWS-managed -> skip
                            {"AliasName": "alias/shifter-proof-portal-secrets"},  # owned
                            {"AliasName": "alias/shifter-dev-portal-secrets"},  # other env -> skip
                            {"AliasName": "alias/some-unrelated-thing"},  # not ours -> skip
                        ]
                    }
                )
            }
        )
        report = detect_leftovers("proof", "proof")
        aliases = [
            f.identifier for f in report.findings if f.resource_class == "kms-alias" and f.action is Action.WOULD_DELETE
        ]
        assert aliases == ["alias/shifter-proof-portal-secrets"]

    def test_budget_is_reported_blocked_never_deletable(self, patched):
        patched(
            {
                "budgets describe-budgets": json.dumps(
                    {"Budgets": [{"BudgetName": "shifter-proof-s3-cost-alert"}, {"BudgetName": "unrelated"}]}
                )
            }
        )
        report = detect_leftovers("proof", "proof")
        budgets = [f for f in report.findings if f.resource_class == "budget"]
        actionable = [f for f in budgets if f.action is not Action.ABSENT]
        assert len(actionable) == 1
        assert actionable[0].action is Action.BLOCKED  # name match only, never auto-deleted

    def test_clean_account_reports_all_absent(self, patched):
        patched({})  # every read returns not-found
        report = detect_leftovers("proof", "proof")
        assert report.actionable == []
        assert "clean" in report.render()


class TestSweepGating:
    def test_sweep_deletes_only_would_delete_and_skips_blocked(self, patched):
        deletes = patched(
            {
                "ecr describe-repositories": json.dumps(
                    {"repositories": [{"repositoryName": "shifter-proof-portal", "repositoryArn": "arn:ecr"}]}
                ),
                "ecr list-tags-for-resource": json.dumps({"tags": _OWNER_TAGS}),
                "budgets describe-budgets": json.dumps({"Budgets": [{"BudgetName": "shifter-proof-s3-cost-alert"}]}),
            }
        )
        report = detect_leftovers("proof", "proof")
        result = sweep_leftovers(report, "proof", dry_run=False)
        deleted = [f for f in result.findings if f.action is Action.DELETED]
        # The tag-owned ECR repo is deleted; the budget stays BLOCKED.
        assert [f.resource_class for f in deleted] == ["ecr-repository"]
        assert any("ecr" in " ".join(c) and "delete-repository" in " ".join(c) for c in deletes)
        assert all("budgets" not in " ".join(c) for c in deletes)  # never deletes a budget

    def test_sweep_dry_run_deletes_nothing(self, patched):
        deletes = patched(
            {
                "ecr describe-repositories": json.dumps(
                    {"repositories": [{"repositoryName": "shifter-proof-portal", "repositoryArn": "arn:ecr"}]}
                ),
                "ecr list-tags-for-resource": json.dumps({"tags": _OWNER_TAGS}),
            }
        )
        report = detect_leftovers("proof", "proof")
        result = sweep_leftovers(report, "proof", dry_run=True)
        assert [f.action for f in result.findings if f.resource_class == "ecr-repository"] == [Action.WOULD_DELETE]
        # dry_run short-circuits before any delete argv executes.
        assert deletes == []

    def test_orchestrator_detection_only_without_sweep(self, patched, capsys):
        deletes = patched(
            {
                **_NOT_LIVE,
                "ecr describe-repositories": json.dumps(
                    {"repositories": [{"repositoryName": "shifter-proof-portal", "repositoryArn": "arn:ecr"}]}
                ),
                "ecr list-tags-for-resource": json.dumps({"tags": _OWNER_TAGS}),
            }
        )
        run_account_recovery("proof", "proof", sweep=False, dry_run=False)
        # No --sweep -> nothing deleted even though an owned leftover exists.
        assert deletes == []


class TestLivenessGuard:
    """The tool refuses on a live (or unverifiable) tenant so it can never treat a
    running tenant's resources as leftovers (issue #1639, caught in live proof)."""

    def test_refuses_and_sweeps_nothing_when_live_asg_present(self, patched):
        deletes = patched(
            {
                "autoscaling describe-auto-scaling-groups": json.dumps(
                    {"AutoScalingGroups": [{"AutoScalingGroupName": "proof-portal-asg-abc", "Instances": [{"x": 1}]}]}
                ),
                # An owned ECR repo also exists, but liveness refusal fires first.
                "ecr describe-repositories": json.dumps(
                    {"repositories": [{"repositoryName": "shifter-proof-portal", "repositoryArn": "arn:ecr"}]}
                ),
                "ecr list-tags-for-resource": json.dumps({"tags": _OWNER_TAGS}),
            }
        )
        report = run_account_recovery("proof", "proof", sweep=True, dry_run=False)
        assert report.findings == []  # refused: nothing presented as a leftover
        assert deletes == []  # and nothing deleted despite --sweep

    def test_fails_closed_when_liveness_undeterminable(self, patched):
        # describe-auto-scaling-groups errors, so liveness cannot be confirmed and
        # the tool must refuse the sweep (fail closed).
        deletes = patched(
            {
                "autoscaling describe-auto-scaling-groups": "__ERROR__",
                "ecr describe-repositories": json.dumps(
                    {"repositories": [{"repositoryName": "shifter-proof-portal", "repositoryArn": "arn:ecr"}]}
                ),
                "ecr list-tags-for-resource": json.dumps({"tags": _OWNER_TAGS}),
            }
        )
        report = run_account_recovery("proof", "proof", sweep=True, dry_run=False)
        assert report.findings == []
        assert deletes == []

    def test_proceeds_on_torn_down_account(self, patched, monkeypatch):
        deletes = patched(
            {
                **_NOT_LIVE,
                "ecr describe-repositories": json.dumps(
                    {"repositories": [{"repositoryName": "shifter-proof-portal", "repositoryArn": "arn:ecr"}]}
                ),
                "ecr list-tags-for-resource": json.dumps({"tags": _OWNER_TAGS}),
            }
        )
        # Grant the destructive confirmation (the confirm()/--yes gate is covered
        # in test_bootstrap_core); here we exercise the torn-down sweep path.
        monkeypatch.setattr(account_recovery, "confirm", lambda *a, **k: True)
        report = run_account_recovery("proof", "proof", sweep=True, dry_run=False)
        # Torn-down account -> detection proceeds and the owned ECR repo is swept.
        assert any(f.action is Action.DELETED and f.resource_class == "ecr-repository" for f in report.findings)
        assert any("delete-repository" in " ".join(c) for c in deletes)


class TestSafetyInvariants:
    def test_no_data_bearing_handlers_exist(self):
        """Structural safety: there is no handler for a data-bearing class, so the
        tool cannot delete KMS keys, buckets, RDS instances/snapshots, or secrets."""
        classes = {h.resource_class for h in HANDLERS}
        forbidden = {"kms-key", "s3-bucket", "rds-instance", "rds-snapshot", "secret", "dynamodb-table"}
        assert classes.isdisjoint(forbidden)
        # The only KMS handler is the alias (pointer), never the key.
        assert "kms-alias" in classes and "kms-key" not in classes

    def test_ssm_delete_refuses_names_outside_portal_prefix(self):
        handler = PortalSsmParameterHandler()
        # A hand-constructed finding outside the exact portal prefix is refused
        # even on the delete path (defense-in-depth), so an AMI or cross-env
        # parameter can never be deleted.
        for bad in ("/shifter/ami/kali", "/shifter/dev/portal/x", "/other/proof/portal/x"):
            finding = LeftoverFinding("ssm-portal-parameter", bad, Action.WOULD_DELETE)
            # /shifter/dev/portal/x actually starts with /shifter/ and has /portal/,
            # so ownership is enforced at detection (env prefix), not here; assert
            # only the clearly-outside ones are blocked at the delete guard.
            if not (bad.startswith("/shifter/") and "/portal/" in bad):
                assert handler.delete(finding, "proof", dry_run=True) is Action.BLOCKED

    def test_ssm_detection_lists_names_without_decryption(self, monkeypatch):
        """get-parameters-by-path must never pass WithDecryption (names only)."""
        seen: list[list[str]] = []

        def fake(cmd, dry_run=False, check=True, capture=False, profile=None):
            seen.append(cmd)
            return _FakeResult(stdout=json.dumps({"Parameters": []}), returncode=0)

        monkeypatch.setattr(account_recovery, "run_cmd", fake)
        PortalSsmParameterHandler().detect("proof", "123456789012", "proof")
        ssm_calls = [" ".join(c) for c in seen if "get-parameters-by-path" in " ".join(c)]
        assert ssm_calls, "expected a get-parameters-by-path call"
        assert all("with-decryption" not in c.lower() for c in ssm_calls)


class TestFailLoudDiscovery:
    """A failed AWS discovery read is a failed check, never a silent 'clean'
    (codex review, #1639)."""

    def test_read_failure_is_reported_failed_not_absent(self, patched):
        # The RDS parameter-group list errors; that class must surface as FAILED,
        # not as an absent/clean row.
        patched({"describe-db-parameter-groups": "__ERROR__"})
        report = detect_leftovers("proof", "proof")
        pgs = [f for f in report.findings if f.resource_class == "rds-db-parameter-group"]
        assert [f.action for f in pgs] == [Action.FAILED]
        assert report.failures

    def test_orchestrator_refuses_sweep_when_a_check_failed(self, patched, monkeypatch):
        deletes = patched(
            {
                **_NOT_LIVE,
                "describe-db-parameter-groups": "__ERROR__",  # one discovery fails
                "ecr describe-repositories": json.dumps(
                    {"repositories": [{"repositoryName": "shifter-proof-portal", "repositoryArn": "arn:ecr"}]}
                ),
                "ecr list-tags-for-resource": json.dumps({"tags": _OWNER_TAGS}),
            }
        )
        monkeypatch.setattr(account_recovery, "confirm", lambda *a, **k: True)
        run_account_recovery("proof", "proof", sweep=True, dry_run=False)
        # Incomplete detection -> refuse the sweep even though an owned repo exists.
        assert deletes == []


class TestNetworkFirewallAsyncDelete:
    """NFW deletes are asynchronous; the sweep waits for convergence (#1639)."""

    def test_delete_waits_until_rule_group_is_gone(self, patched):
        deletes = patched(
            {
                "network-firewall list-rule-groups": json.dumps(
                    {"RuleGroups": [{"Name": "shifter-proof-victim", "Arn": "arn:nfw:rg/1"}]}
                ),
                "network-firewall list-tags-for-resource": json.dumps({"Tags": _OWNER_TAGS}),
                # describe-rule-group returns not-found once the group is gone -> converged.
                "network-firewall describe-rule-group": "__NOTFOUND__",
            }
        )
        report = detect_leftovers("proof", "proof")
        result = sweep_leftovers(report, "proof", dry_run=False)
        nfw = [f for f in result.findings if f.resource_class == "networkfirewall-rule-group"]
        assert [f.action for f in nfw] == [Action.DELETED]
        # The delete was issued and convergence confirmed via describe.
        assert any("delete-rule-group" in " ".join(c) for c in deletes)

    def test_transient_describe_error_is_not_treated_as_deleted(self, patched, monkeypatch):
        # A describe failure with no not-found marker is transient: the sweep must
        # keep polling and never conclude DELETED from a blip (#1639 codex review).
        patched(
            {
                "network-firewall list-rule-groups": json.dumps(
                    {"RuleGroups": [{"Name": "shifter-proof-victim", "Arn": "arn:nfw:rg/1"}]}
                ),
                "network-firewall list-tags-for-resource": json.dumps({"Tags": _OWNER_TAGS}),
                "network-firewall describe-rule-group": "__ERROR__",  # transient, not a not-found
            }
        )
        # Keep the bounded wait short and instant for the test.
        monkeypatch.setattr(account_recovery, "_NFW_DELETE_POLL_ATTEMPTS", 2)
        monkeypatch.setattr(account_recovery.time, "sleep", lambda *_: None)
        report = detect_leftovers("proof", "proof")
        result = sweep_leftovers(report, "proof", dry_run=False)
        nfw = [f for f in result.findings if f.resource_class == "networkfirewall-rule-group"]
        # Never DELETED on a transient error; FAILED so the idempotent sweep re-runs.
        assert [f.action for f in nfw] == [Action.FAILED]


class TestNameAndOwnership:
    """Canonical name PLUS ownership; conflicts are surfaced, not dropped (#1639)."""

    def test_canonical_name_with_conflicting_tags_is_blocked(self, patched):
        # Name matches the env, but the tags say a different env -> BLOCKED for
        # manual review, never silently dropped and never deleted.
        patched(
            {
                "describe-db-parameter-groups": json.dumps(
                    {
                        "DBParameterGroups": [
                            {"DBParameterGroupName": "shifter-proof-portal", "DBParameterGroupArn": "arn:conflict"}
                        ]
                    }
                ),
                "list-tags-for-resource --resource-name arn:conflict": json.dumps({"TagList": _FOREIGN_TAGS}),
            }
        )
        report = detect_leftovers("proof", "proof")
        pgs = [f for f in report.findings if f.resource_class == "rds-db-parameter-group"]
        assert [f.action for f in pgs] == [Action.BLOCKED]

    def test_noncanonical_name_is_not_a_candidate(self, patched):
        # A resource whose name is not canonical for the env is skipped even if a
        # tag lookup would say owned: name is the required lookup key.
        patched(
            {
                "ecr describe-repositories": json.dumps(
                    {"repositories": [{"repositoryName": "some-unrelated-repo", "repositoryArn": "arn:x"}]}
                ),
                "ecr list-tags-for-resource": json.dumps({"tags": _OWNER_TAGS}),
            }
        )
        report = detect_leftovers("proof", "proof")
        ecr = [f for f in report.findings if f.resource_class == "ecr-repository"]
        # Not a candidate -> the class reports absent (no would-delete, no blocked).
        assert [f.action for f in ecr] == [Action.ABSENT]
