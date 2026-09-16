"""Inventory provenance and bootstrap orchestration at external process boundaries."""

import argparse
import json
import subprocess
from pathlib import Path

import pytest
import yaml
from installation.deployment_inventory import validate_record
from installation.errors import InstallationConfigError

from inventory_cli import handle, stage_product, verified_inventory
from inventory_cloud import bootstrap_lock, ensure_state_buckets, operator_environment, verify_projects
from inventory_github import publish_execution_bindings, reconcile_environments
from inventory_scaffold import scaffold_checks

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def record_data():
    return json.loads((ROOT / "shifter/installation/examples/deployment-inventory.json").read_text())


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout.strip()


def commit(root):
    git(root, "add", ".")
    git(root, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.com", "commit", "-m", "inventory fixture")
    return git(root, "rev-parse", "HEAD")


@pytest.fixture
def inventory(tmp_path, record_data):
    git(tmp_path, "init", "--initial-branch=main")
    git(tmp_path, "remote", "add", "origin", "https://github.com/example/inventory.git")
    (tmp_path / "deployments").mkdir()
    (tmp_path / "deployments/customer.json").write_text(json.dumps(record_data))
    revision = commit(tmp_path)
    return argparse.Namespace(
        inventory_root=tmp_path,
        inventory_repository="example/inventory",
        inventory_revision=revision,
        record="deployments/customer.json",
    )


def test_committed_inventory_validates_and_drives_scaffold(inventory, tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    inventory.action = "validate"
    handle(inventory)
    assert json.loads(capsys.readouterr().out)["valid"] is True
    inventory.action = "scaffold"
    inventory.output = tmp_path / "starter"
    handle(inventory)
    files = sorted((inventory.output / ".github/workflows").glob("*.yml"))
    assert [file.name for file in files] == ["deploy.yml", "gcp-dev-destroy.yml"]
    workflow = yaml.safe_load(files[0].read_text())
    assert set(workflow["on"]) == {"workflow_dispatch"}
    job = next(iter(workflow["jobs"].values()))
    assert job["environment"] == "customer-deploy"
    assert job["runs-on"] == "unseen-customer"
    assert len([step for step in job["steps"] if step.get("continue-on-error")]) == 2
    assert job["steps"][-1]["run"].count("= failure") == 2
    with pytest.raises(InstallationConfigError):
        scaffold_checks(verified_inventory(inventory), inventory.output)


@pytest.mark.parametrize("mutation", ["revision", "origin", "dirty", "symlink", "untracked"])
def test_provenance_rejects_unreviewed_or_nonregular_record(inventory, mutation):
    path = inventory.inventory_root / inventory.record
    if mutation == "revision":
        inventory.inventory_revision = "main"
    elif mutation == "origin":
        inventory.inventory_repository = "another/repository"
    elif mutation == "dirty":
        path.write_text("{}")
    elif mutation == "untracked":
        inventory.record = "deployments/untracked.json"
        (inventory.inventory_root / inventory.record).write_text("{}")
    else:
        path.unlink()
        path.symlink_to("../untracked-target")
        inventory.inventory_revision = commit(inventory.inventory_root)
    with pytest.raises(InstallationConfigError):
        verified_inventory(inventory)


def test_product_staging_uses_only_pinned_code_and_lockfiles(tmp_path):
    product = tmp_path / "product"
    product.mkdir()
    git(product, "init", "--initial-branch=main")
    root = product / "platform/terraform/gcp/global/cicd-oidc"
    root.mkdir(parents=True)
    (root / "main.tf").write_text("# pinned code\n")
    (root / "local.auto.tfvars").write_text("private operational fixture")
    revision = commit(product)
    (root / "untracked.tf").write_text("# must not execute\n")
    target = stage_product(product, revision, tmp_path / "staged")
    assert [path.name for path in target.iterdir()] == ["main.tf"]
    (root / "main.tf").write_text("# modified code\n")
    with pytest.raises(InstallationConfigError):
        stage_product(product, revision, tmp_path / "another")


def test_operator_and_projects_are_explicit_and_token_stays_in_environment(record_data, monkeypatch):
    record = validate_record(record_data)
    calls = []

    def process(argv, **kwargs):
        calls.append((argv, kwargs))
        if "get-value" in argv:
            response = "(unset)"
        elif argv[:3] == ["gcloud", "auth", "list"]:
            response = "operator@example.com"
        elif "print-access-token" in argv:
            response = "private-token"
        else:
            response = json.dumps({"projectId": argv[3], "lifecycleState": "ACTIVE", "projectNumber": "789"})
        return subprocess.CompletedProcess(argv, 0, response, "")

    monkeypatch.setattr(subprocess, "run", process)
    env = operator_environment("operator@example.com")
    assert verify_projects(record, env) == "789"
    project_calls = [argv for argv, _ in calls if argv[:3] == ["gcloud", "projects", "describe"]]
    assert project_calls == [["gcloud", "projects", "describe", "customer-runtime", "--format=json"]]
    assert all("private-token" not in argv for argv, _ in calls)
    assert calls[-1][1]["env"]["GOOGLE_OAUTH_ACCESS_TOKEN"] == "private-token"


@pytest.mark.parametrize("acquire_fails", [True, False])
def test_bootstrap_lock_never_deletes_another_writers_lock(record_data, monkeypatch, tmp_path, acquire_fails):
    calls = []

    def process(argv, **kwargs):
        calls.append(argv)
        code = 1 if "cp" in argv and acquire_fails else 0
        return subprocess.CompletedProcess(argv, code, "42" if "describe" in argv else "", "")

    monkeypatch.setattr(subprocess, "run", process)
    if acquire_fails:
        with pytest.raises(InstallationConfigError), bootstrap_lock(validate_record(record_data), tmp_path, {}):
            pytest.fail("lock acquisition must fail")
        assert not any("rm" in call for call in calls)
    else:
        with pytest.raises(RuntimeError), bootstrap_lock(validate_record(record_data), tmp_path, {}):
            raise RuntimeError("bootstrap crashed")
        assert "--if-generation-match=42" in calls[-1]


@pytest.mark.parametrize("apply", [False, True])
def test_state_buckets_require_isolated_ownership_and_security_readback(record_data, monkeypatch, apply):
    record = validate_record(record_data)
    calls = []

    def process(argv, **kwargs):
        calls.append(argv)
        if "list" in argv:
            response = [] if apply else [{"name": state.bucket} for state in record.state.values()]
        elif argv[:3] == ["gcloud", "projects", "describe"]:
            response = {"projectNumber": "789"}
        elif "describe" in argv:
            response = {
                "name": argv[4].removeprefix("gs://"),
                "projectNumber": "789",
                "iamConfiguration": {
                    "uniformBucketLevelAccess": {"enabled": True},
                    "publicAccessPrevention": "enforced",
                },
                "versioning": {"enabled": True},
            }
        else:
            response = {}
        return subprocess.CompletedProcess(argv, 0, json.dumps(response), "")

    monkeypatch.setattr(subprocess, "run", process)
    ensure_state_buckets(record, {}, apply=apply)
    assert len([call for call in calls if "create" in call]) == (3 if apply else 0)
    assert len([call for call in calls if "--raw" in call]) == 3


def test_environment_reconciliation_preserves_reviewers_and_removes_wildcards(record_data, monkeypatch):
    record = validate_record(record_data)
    calls = []
    updated = set()

    def process(argv, **kwargs):
        calls.append((argv, kwargs))
        endpoint = next((arg for arg in argv if arg.startswith("repos/")), "")
        if endpoint.endswith("/environments"):
            response = [
                {
                    "environments": [
                        {
                            "name": ctx.environment,
                            "protection_rules": [{"type": "wait_timer", "wait_timer": 5}],
                            "can_admins_bypass": False,
                        }
                        for contexts in record.execution.purposes.values()
                        for ctx in contexts
                    ]
                }
            ]
        elif "/branches/" in endpoint:
            response = {"protected": True}
        elif "PUT" in argv:
            assert json.loads(kwargs["input"])["wait_timer"] == 5
            response = {}
        elif "DELETE" in argv:
            response = {}
        elif "POST" in argv:
            updated.add(endpoint)
            response = {}
        elif endpoint.endswith("deployment-branch-policies"):
            policies = [{"id": 1, "name": "main" if endpoint in updated else "*", "type": "branch"}]
            response = [{"branch_policies": policies}]
        else:
            response = {
                "deployment_branch_policy": {"protected_branches": False, "custom_branch_policies": True},
                "protection_rules": [{"type": "wait_timer", "wait_timer": 5}],
                "can_admins_bypass": False,
            }
        return subprocess.CompletedProcess(argv, 0, json.dumps(response), "")

    monkeypatch.setattr(subprocess, "run", process)
    reconcile_environments(record, apply=True)
    assert len([call for call, _ in calls if "DELETE" in call]) == 2


def test_execution_variables_are_read_back_per_environment(record_data, monkeypatch):
    values = {}

    def process(argv, **kwargs):
        if "set" in argv:
            values[argv[3]] = kwargs["input"]
            response = ""
        else:
            response = json.dumps({"value": values[argv[-1].rsplit("/", 1)[-1]]})
        return subprocess.CompletedProcess(argv, 0, response, "")

    monkeypatch.setattr(subprocess, "run", process)
    publish_execution_bindings(validate_record(record_data), "789")
    assert values["GCP_SERVICE_ACCOUNT"] != values["GCP_DENIED_SERVICE_ACCOUNT"]


def test_required_services_are_read_back_before_provisioning(record_data, monkeypatch):
    from inventory_cloud import ensure_services

    enabled = {}

    def process(argv, **kwargs):
        project = argv[argv.index("--project") + 1]
        if "enable" in argv:
            enabled[project] = argv[3 : argv.index("--project")]
            response = ""
        else:
            response = json.dumps([{"config": {"name": name}} for name in enabled.get(project, [])])
        return subprocess.CompletedProcess(argv, 0, response, "")

    monkeypatch.setattr(subprocess, "run", process)
    record = validate_record(record_data)
    with pytest.raises(InstallationConfigError):
        ensure_services(record, {}, apply=False)
    ensure_services(record, {}, apply=True)
    ensure_services(record, {}, apply=False)
    assert set(enabled) == {"customer-runtime"}
    assert {
        "compute.googleapis.com",
        "iamcredentials.googleapis.com",
        "sts.googleapis.com",
        "iap.googleapis.com",
    }.issubset(enabled["customer-runtime"])


@pytest.mark.parametrize("replacement", [False, True])
def test_runner_plan_preserves_hosts_and_registers_with_verified_credentials(
    record_data, monkeypatch, tmp_path, capsys, replacement
):
    from inventory_runner import bootstrap_runner

    record = validate_record(record_data)
    calls = []
    registered = False
    evidence = tmp_path / "evidence"
    evidence.mkdir(mode=0o700)

    def process(argv, **kwargs):
        nonlocal registered
        calls.append((argv, kwargs))
        response = ""
        if argv[:2] == ["terraform", "plan"]:
            (tmp_path / "runner.plan").write_bytes(b"runner-plan")
        elif argv[:2] == ["terraform", "show"]:
            response = json.dumps(
                {"resource_changes": [{"change": {"actions": ["delete", "create"] if replacement else ["create"]}}]}
            )
        elif argv[:2] == ["terraform", "apply"]:
            assert (evidence / "runner.plan").read_bytes() == b"runner-plan"
            assert json.loads(capsys.readouterr().out)["stage"] == "runner"
        elif argv[:2] == ["terraform", "output"]:
            response = json.dumps(
                {
                    "runner_instance_names": {"value": ["cust-unseen-runner-1"]},
                    "runner_names": {"value": ["unseen-customer-runner-1"]},
                }
            )
        elif argv[0] == "gh" and ".runners" in argv:
            response = json.dumps(
                [{"name": "unseen-customer-runner-1", "status": "online", "labels": [{"name": "unseen-customer"}]}]
                if registered
                else []
            )
        elif ".token" in argv:
            response = "private-registration-token"
        elif argv[0] == "gcloud" and kwargs.get("input"):
            registered = True
            assert kwargs["env"]["GOOGLE_OAUTH_ACCESS_TOKEN"] == "verified-token"
            assert "private-registration-token" not in argv
        return subprocess.CompletedProcess(argv, 0, response, "")

    monkeypatch.setattr(subprocess, "run", process)
    if replacement:
        with pytest.raises(InstallationConfigError):
            bootstrap_runner(record, tmp_path, {}, apply=True, plan_output=evidence)
        assert not any(argv[:2] == ["terraform", "apply"] for argv, _ in calls)
    else:
        bootstrap_runner(
            record, tmp_path, {"GOOGLE_OAUTH_ACCESS_TOKEN": "verified-token"}, apply=True, plan_output=evidence
        )
        assert registered


@pytest.mark.parametrize("widen", [False, True])
def test_installed_policy_readback_rejects_live_drift(record_data, monkeypatch, widen):
    from inventory_bootstrap import expected_identity_policy
    from inventory_readback import verify_installed_identity

    record = validate_record(record_data)
    expected = expected_identity_policy(record, "789")

    def process(argv, **kwargs):
        if "providers" in argv:
            response = {
                "attributeCondition": "true" if widen else expected["attribute_condition"],
                "attributeMapping": {"google.subject": "assertion.sub"},
                "oidc": {"issuerUri": "https://token.actions.githubusercontent.com"},
            }
        else:
            purpose = next(p for p, account in expected["service_accounts"].items() if account.endswith(argv[4]))
            response = {
                "bindings": [
                    {
                        "role": "roles/iam.workloadIdentityUser",
                        "members": [
                            "principal://iam.googleapis.com/projects/789/locations/global/workloadIdentityPools/"
                            + record.gcp.name_prefix
                            + "-github/subject/"
                            + subject
                            for subject in expected["purpose_subjects"][purpose]
                        ],
                    }
                ]
            }
        return subprocess.CompletedProcess(argv, 0, json.dumps(response), "")

    monkeypatch.setattr(subprocess, "run", process)
    if widen:
        with pytest.raises(InstallationConfigError):
            verify_installed_identity(record, "789", {}, ROOT)
    else:
        verify_installed_identity(record, "789", {}, ROOT)


@pytest.mark.parametrize("lose_protection", [False, True])
def test_environment_case_alias_preserves_and_verifies_approvals(record_data, monkeypatch, lose_protection):
    record_data["execution"]["purposes"] = {"deploy": record_data["execution"]["purposes"]["deploy"]}
    record = validate_record(record_data)
    protections = {
        "name": "CUSTOMER-DEPLOY",
        "can_admins_bypass": False,
        "protection_rules": [
            {"type": "wait_timer", "wait_timer": 5},
            {
                "type": "required_reviewers",
                "prevent_self_review": True,
                "reviewers": [{"type": "Team", "reviewer": {"id": 42}}],
            },
        ],
    }
    writes = []

    def process(argv, **kwargs):
        endpoint = next((arg for arg in argv if arg.startswith("repos/")), "")
        if endpoint.endswith("/environments"):
            response = [{"environments": [protections]}]
        elif "/branches/" in endpoint:
            response = {"protected": True}
        elif "PUT" in argv:
            writes.append(json.loads(kwargs["input"]))
            response = {}
        elif endpoint.endswith("deployment-branch-policies"):
            response = [{"branch_policies": [{"id": 1, "name": "main", "type": "branch"}]}]
        else:
            response = {
                **({} if lose_protection else protections),
                "deployment_branch_policy": {"protected_branches": False, "custom_branch_policies": True},
            }
        return subprocess.CompletedProcess(argv, 0, json.dumps(response), "")

    monkeypatch.setattr(subprocess, "run", process)
    if lose_protection:
        with pytest.raises(InstallationConfigError):
            reconcile_environments(record, apply=True)
    else:
        reconcile_environments(record, apply=True)
    assert writes[0]["reviewers"] == [{"type": "Team", "id": 42}]
    assert writes[0]["prevent_self_review"] is True
    assert writes[0]["can_admins_bypass"] is False
    assert writes[0]["wait_timer"] == 5


def test_plan_cli_retains_both_stack_results_after_execution_cleanup(record_data, monkeypatch, tmp_path, capsys):
    from contextlib import nullcontext

    import inventory_cli
    import inventory_runner
    from inventory_plan import publish_plan

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("shutil.which", lambda tool: f"/mock-bin/{tool}")
    record = validate_record(record_data)
    monkeypatch.setattr(inventory_cli, "verified_inventory", lambda args: record)
    monkeypatch.setattr(inventory_cli, "get_repo_root", lambda: ROOT)
    monkeypatch.setattr(inventory_cli, "stage_product", lambda root, revision, target: target)
    monkeypatch.setattr(inventory_cli, "operator_environment", lambda operator: {})
    monkeypatch.setattr(inventory_cli, "verify_projects", lambda *args: "789")
    for name in (
        "verify_github_actor",
        "ensure_services",
        "ensure_state_buckets",
        "reconcile_environments",
        "reconcile_subject",
    ):
        monkeypatch.setattr(inventory_cli, name, lambda *args, **kwargs: None)
    monkeypatch.setattr(inventory_cli, "bootstrap_lock", lambda *args: nullcontext())
    execution_directories = []

    def plan_stack(stack, directory, plan_output):
        directory.mkdir(parents=True, exist_ok=True)
        execution_directories.append(directory)
        binary = directory / f"{stack}.plan"
        binary.write_bytes(stack.encode())
        plan = {"resource_changes": [{"address": f"module.{stack}.resource", "change": {"actions": ["no-op"]}}]}
        return publish_plan(stack, plan, binary, plan_output)

    def identity(record, *, directory, plan_output, **kwargs):
        assert kwargs["apply"] is False
        return {"plan": plan_stack("identity", directory, plan_output), "applied": False}

    def runner(record, directory, env, *, apply, plan_output):
        assert apply is False
        return plan_stack("runner", directory, plan_output)

    monkeypatch.setattr(inventory_cli, "plan_identity", identity)
    monkeypatch.setattr(inventory_runner, "bootstrap_runner", runner)
    args = argparse.Namespace(
        action="plan",
        operator="operator@example.com",
        github_actor="operator",
        execution_repository=record.execution.repository,
        project="customer-runtime",
        inventory_repository="example/inventory",
        inventory_revision="b" * 40,
        plan_output=tmp_path / "private-review",
        apply=False,
    )
    handle(args)
    result = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert result["plan"]["has_changes"] is False
    assert result["runner_plan"]["has_changes"] is False
    assert not any(path.exists() for path in execution_directories)
    assert (args.plan_output / "identity.plan").read_bytes() == b"identity"
    assert (args.plan_output / "runner.plan").read_bytes() == b"runner"
    assert json.loads((args.plan_output / "provenance.json").read_text())["inventory_revision"] == "b" * 40


def test_scaffold_rejects_output_path_traversal(record_data, monkeypatch, tmp_path):
    """--output escaping the working directory is refused (S8707 path traversal)."""
    import inventory_cli

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(inventory_cli, "verified_inventory", lambda args: validate_record(record_data))
    args = argparse.Namespace(action="scaffold", output=Path("../escape"))
    with pytest.raises(SystemExit):
        handle(args)
    assert not (tmp_path.parent / "escape").exists()


def test_resolve_secret_rejects_output_path_traversal(record_data, monkeypatch, tmp_path):
    """--secret-output escaping the working directory is refused before any fetch."""
    import inventory_cli
    import inventory_secrets

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(inventory_cli, "verified_inventory", lambda args: validate_record(record_data))
    monkeypatch.setattr(inventory_secrets, "resolve_secret", lambda *a, **k: pytest.fail("must reject before fetch"))
    args = argparse.Namespace(
        action="resolve-secret",
        secret_name="DJANGO_SECRET_KEY",
        secret_output=Path("../escape"),
        execution_repository="example/product",
        execution_environment="customer-deploy",
    )
    with pytest.raises(SystemExit):
        handle(args)
    assert not (tmp_path.parent / "escape").exists()


def test_plan_rejects_plan_output_traversal(record_data, monkeypatch, tmp_path):
    """--plan-output escaping the working directory is refused (S8707 path traversal)."""
    import inventory_cli

    record = validate_record(record_data)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(inventory_cli, "verified_inventory", lambda args: record)
    monkeypatch.setattr("shutil.which", lambda tool: f"/mock-bin/{tool}")
    args = argparse.Namespace(
        action="plan",
        operator="operator@example.com",
        github_actor="operator",
        execution_repository=record.execution.repository,
        project=record.installation.settings["project_id"],
        plan_output=Path("../escape"),
        apply=False,
    )
    with pytest.raises(SystemExit):
        handle(args)
    assert not (tmp_path.parent / "escape").exists()
