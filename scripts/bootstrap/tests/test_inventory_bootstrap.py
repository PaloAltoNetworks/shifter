"""Exercise inventory bootstrap at the process and policy boundaries."""

import json
import subprocess
from pathlib import Path

import pytest
from installation.deployment_inventory import validate_record
from installation.errors import InstallationConfigError

import inventory_bootstrap

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def record():
    return validate_record(json.loads((ROOT / "shifter/installation/examples/deployment-inventory.json").read_text()))


def test_explicit_authority_must_match_inventory_before_any_command(record, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("invalid authority must fail before authentication or mutation")

    monkeypatch.setattr(subprocess, "run", forbidden)
    with pytest.raises(InstallationConfigError):
        inventory_bootstrap.authorize_record(record, execution_repository="attacker/product", project_id="other")


def test_private_process_failure_suppresses_provider_payload(monkeypatch, capsys):
    def failed(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 1, "PRIVATE-TOKEN", "PRIVATE-TOKEN")

    monkeypatch.setattr(subprocess, "run", failed)
    with pytest.raises(InstallationConfigError) as failure:
        inventory_bootstrap.private_command(["gcloud", "version"])
    assert "PRIVATE-TOKEN" not in str(failure.value)
    assert "PRIVATE-TOKEN" not in capsys.readouterr().out


def test_checkov_requires_exact_rule_discovery_and_no_skips():
    with pytest.raises(InstallationConfigError):
        inventory_bootstrap.validate_checkov_result({"summary": {"passed": 0, "failed": 0}, "results": {}})
    valid = {
        "summary": {"failed": 0, "parsing_errors": 0},
        "results": {
            "passed_checks": [{"check_id": "CKV_GCP_125", "resource": "module.identity.provider"}],
            "skipped_checks": [],
            "failed_checks": [],
            "parsing_errors": [],
        },
    }
    inventory_bootstrap.validate_checkov_result(valid)
    valid["results"]["skipped_checks"] = [{"check_id": "CKV_GCP_125"}]
    with pytest.raises(InstallationConfigError):
        inventory_bootstrap.validate_checkov_result(valid)


def test_generated_inputs_are_private_and_do_not_include_secret_payloads(record, tmp_path):
    inventory_bootstrap.write_identity_inputs(record, tmp_path, project_number="789")
    path = tmp_path / "inventory.auto.tfvars.json"
    data = json.loads(path.read_text())
    assert path.stat().st_mode & 0o077 == 0
    assert data["project_number"] == "789"
    assert "secrets" not in data
    assert "DJANGO_SECRET_KEY" not in path.read_text()


def test_execution_environment_readback_rejects_unprotected_or_extra_branches(record):
    policy = {"deployment_branch_policy": {"protected_branches": False, "custom_branch_policies": True}}
    with pytest.raises(InstallationConfigError):
        inventory_bootstrap.validate_environment(policy, [{"name": "*", "type": "branch"}], {"main"})
    inventory_bootstrap.validate_environment(policy, [{"name": "main", "type": "branch"}], {"main"})


def test_plan_verification_runs_before_apply_and_refuses_mutated_saved_plan(record, tmp_path):
    plan_path = tmp_path / "identity.plan"
    plan_path.write_bytes(b"reviewed-plan")
    digest = inventory_bootstrap.file_digest(plan_path)
    plan_path.write_bytes(b"different-plan")
    with pytest.raises(InstallationConfigError):
        inventory_bootstrap.assert_plan_unchanged(plan_path, digest)


def test_common_secret_resolver_checks_scope_and_never_prints_payload(record, monkeypatch, capsys):
    from inventory_secrets import resolve_secret

    commands = []

    def process(argv, **kwargs):
        commands.append(argv)
        return subprocess.CompletedProcess(argv, 0, "private-runtime-value", "")

    monkeypatch.setattr(subprocess, "run", process)
    value = resolve_secret(
        record.secrets["DJANGO_SECRET_KEY"], repository="example/product", environment="customer-deploy"
    )
    assert value == "private-runtime-value"
    assert "projects/customer-runtime/secrets/django/versions/1" in commands[0]
    assert "private-runtime-value" not in capsys.readouterr().out


def test_execution_secret_is_unavailable_outside_its_exact_scope(monkeypatch):
    from installation.deployment_inventory_types import SecretReference

    from inventory_secrets import resolve_secret

    reference = SecretReference(
        store="github-environment",
        resource="EXAMPLE_SECRET",
        repository="example/product",
        environment="deployment-one",
    )
    monkeypatch.setenv("EXAMPLE_SECRET", "private-value")
    with pytest.raises(InstallationConfigError):
        resolve_secret(reference, repository="example/product", environment="deployment-two")


def test_runner_projection_uses_the_same_inventory_and_dedicated_state(record):
    from inventory_runner import runner_tfvars

    values = runner_tfvars(record)
    assert values["project_id"] == "customer-runtime"
    assert values["environment"] == "unseen-customer"
    assert values["name_prefix"] == "cust-unseen"
    assert "runner_version" not in values
    assert "secrets" not in values


def test_credential_bearing_runner_cannot_register_to_public_repository(record, monkeypatch):
    from inventory_github import verify_github_actor

    responses = iter(
        [
            {"login": "operator"},
            {"id": 123, "owner": {"id": 456}, "permissions": {"admin": True}, "private": False},
            {"use_default": True, "use_immutable_subject": False},
        ]
    )
    monkeypatch.setattr(
        subprocess, "run", lambda argv, **kwargs: subprocess.CompletedProcess(argv, 0, json.dumps(next(responses)), "")
    )
    with pytest.raises(InstallationConfigError):
        verify_github_actor(record, "operator")


def test_operator_credentials_cannot_silently_impersonate_another_account(monkeypatch):
    from inventory_cloud import operator_environment

    def process(argv, **kwargs):
        if "get-value" in argv:
            output = "privileged@example.iam.gserviceaccount.com"
        elif "list" in argv:
            output = "operator@example.com"
        else:
            output = "private-token"
        return subprocess.CompletedProcess(argv, 0, output, "")

    monkeypatch.setattr(subprocess, "run", process)
    with pytest.raises(InstallationConfigError):
        operator_environment("operator@example.com")


def test_verified_environment_flows_through_existing_runner_process_helpers(monkeypatch):
    from bootstrap_core import _subprocess_env, run_cmd_secret_stdin, verified_command_environment

    monkeypatch.setenv("GOOGLE_OAUTH_ACCESS_TOKEN", "ambient-credential")
    captured = []

    def process(argv, **kwargs):
        captured.append(kwargs)
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(subprocess, "run", process)
    with (
        pytest.raises(RuntimeError),
        verified_command_environment({"GOOGLE_OAUTH_ACCESS_TOKEN": "verified-credential"}),
    ):
        run_cmd_secret_stdin(["gcloud", "version"], secret_stdin="registration-token")
        assert captured[0]["env"]["GOOGLE_OAUTH_ACCESS_TOKEN"] == "verified-credential"
        raise RuntimeError("registration failed")
    assert _subprocess_env()["GOOGLE_OAUTH_ACCESS_TOKEN"] == "ambient-credential"


@pytest.mark.parametrize("subject_format", ["default", "immutable"])
def test_new_repository_subject_configuration_requires_exact_readback(record, monkeypatch, subject_format):
    from inventory_github import reconcile_subject

    data = record.model_dump(mode="json")
    data["execution"]["subject_format"] = subject_format
    record = validate_record(data)
    owner, repo = record.execution.repository.split("/")
    prefix = (
        f"repo:{owner}@{record.execution.owner_id}/{repo}@{record.execution.repository_id}"
        if subject_format == "immutable"
        else "repo:" + record.execution.repository
    )
    calls = []

    def process(argv, **kwargs):
        calls.append((argv, kwargs))
        response = (
            ""
            if "PUT" in argv
            else json.dumps(
                {
                    "use_default": True,
                    "use_immutable_subject": subject_format == "immutable",
                    "sub_claim_prefix": prefix,
                }
            )
        )
        return subprocess.CompletedProcess(argv, 0, response, "")

    monkeypatch.setattr(subprocess, "run", process)
    reconcile_subject(record, apply=True)
    assert json.loads(calls[0][1]["input"]) == {
        "use_default": True,
        "use_immutable_subject": subject_format == "immutable",
    }
    assert len(calls) == 2
    for response in [
        {},
        {"use_default": True, "use_immutable_subject": subject_format == "immutable", "sub_claim_prefix": prefix + "9"},
        {"use_default": True, "use_immutable_subject": subject_format != "immutable", "sub_claim_prefix": prefix},
        {"use_default": False, "use_immutable_subject": subject_format == "immutable", "sub_claim_prefix": prefix},
    ]:
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda argv, response=response, **kw: subprocess.CompletedProcess(argv, 0, json.dumps(response), ""),
        )
        with pytest.raises(InstallationConfigError):
            reconcile_subject(record, apply=False)


def identity_plan(record):
    expected = inventory_bootstrap.expected_identity_policy(record, "789")
    provider = {
        "attribute_condition": expected["attribute_condition"],
        "project": expected["project_id"],
        "workload_identity_pool_id": expected["name_prefix"] + "-github",
        "workload_identity_pool_provider_id": "github",
        "attribute_mapping": {"google.subject": "assertion.sub"},
        "oidc": [{"issuer_uri": "https://token.actions.githubusercontent.com", "allowed_audiences": []}],
    }
    resources = [
        {"type": "google_iam_workload_identity_pool_provider", "change": {"actions": ["create"], "after": provider}}
    ]
    for purpose, subjects in expected["purpose_subjects"].items():
        for subject in subjects:
            resources.append(
                {
                    "type": "google_service_account_iam_member",
                    "change": {
                        "actions": ["create"],
                        "after": {
                            "service_account_id": expected["service_accounts"][purpose],
                            "role": "roles/iam.workloadIdentityUser",
                            "member": "principal://iam.googleapis.com/projects/789/locations/global/workloadIdentityPools/"
                            + expected["name_prefix"]
                            + "-github/subject/"
                            + subject,
                        },
                    },
                }
            )
    return {"resource_changes": resources}


@pytest.mark.parametrize("failure", ["trust", "scanner", "changed-plan", None])
def test_saved_plan_pipeline_cannot_apply_until_both_policy_gates_pass(record, monkeypatch, tmp_path, capsys, failure):
    calls = []
    evidence = tmp_path / "evidence"
    evidence.mkdir(mode=0o700)
    plan = identity_plan(record)
    if failure == "trust":
        plan["resource_changes"][0]["change"]["after"]["attribute_condition"] = "true"

    def process(argv, **kwargs):
        calls.append(argv)
        output = ""
        if argv[:2] == ["terraform", "plan"]:
            (tmp_path / "identity.plan").write_bytes(b"saved-plan")
        elif argv[:2] == ["terraform", "show"]:
            output = json.dumps(plan)
        elif argv[0] == "uv":
            assert (
                argv[argv.index("--from") + 1]
                == "git+https://github.com/bridgecrewio/checkov.git@73dac2f77484ea73f1740ea7bf91ffc67808b1b2"
            )
            if failure == "changed-plan":
                (tmp_path / "identity.plan").write_bytes(b"changed-plan")
            output = json.dumps({"results": {"passed_checks": [{"check_id": "CKV_GCP_125"}]}, "summary": {}})
            if failure == "scanner":
                return subprocess.CompletedProcess(argv, 1, "private failed policy", "")
        elif argv[:2] == ["terraform", "apply"]:
            assert (evidence / "identity.plan").read_bytes() == b"saved-plan"
            assert json.loads((evidence / "identity.plan.json").read_text()) == plan
            assert json.loads(capsys.readouterr().out)["stage"] == "identity"
        return subprocess.CompletedProcess(argv, 0, output, "")

    monkeypatch.setattr(subprocess, "run", process)
    if failure:
        with pytest.raises(InstallationConfigError):
            inventory_bootstrap.plan_identity(
                record,
                directory=tmp_path,
                product_root=ROOT,
                project_number="789",
                env={},
                plan_output=evidence,
                apply=True,
            )
        assert not any(call[:2] == ["terraform", "apply"] for call in calls)
    else:
        result = inventory_bootstrap.plan_identity(
            record,
            directory=tmp_path,
            product_root=ROOT,
            project_number="789",
            env={},
            plan_output=evidence,
            apply=True,
        )
        assert result["applied"] is True
        assert calls[-1] == ["terraform", "apply", "-input=false", "-lock-timeout=120s", "identity.plan"]


@pytest.mark.parametrize("payload", ["exact-password", "ends-with-newline\n", None])
def test_aws_secret_resolution_preserves_payload_and_rejects_binary_secret(monkeypatch, payload):
    from installation.deployment_inventory_types import SecretReference

    from inventory_secrets import resolve_secret

    reference = SecretReference(
        store="aws-secrets-manager", resource="arn:aws:secretsmanager:us-east-2:123456789012:secret:example"
    )

    def process(argv, **kwargs):
        response = json.dumps(payload) + "\n" if argv[-1] == "json" else str(payload) + "\n"
        return subprocess.CompletedProcess(argv, 0, response, "")

    monkeypatch.setattr(subprocess, "run", process)
    if payload is None:
        with pytest.raises(InstallationConfigError):
            resolve_secret(reference, repository="example/product", environment="customer-deploy")
    else:
        assert resolve_secret(reference, repository="example/product", environment="customer-deploy") == payload


def test_repository_canonical_name_is_part_of_initial_authority(record, monkeypatch):
    from inventory_github import verify_github_actor

    response = {
        "id": 123,
        "owner": {"id": 456},
        "permissions": {"admin": True},
        "private": True,
        "full_name": record.execution.repository,
    }

    def process(argv, **kwargs):
        data = {"login": "operator"} if argv[-1] == "user" else response
        return subprocess.CompletedProcess(argv, 0, json.dumps(data), "")

    monkeypatch.setattr(subprocess, "run", process)
    verify_github_actor(record, "operator")
    response["full_name"] = record.execution.repository.upper()
    with pytest.raises(InstallationConfigError):
        verify_github_actor(record, "operator")


def test_inventory_repository_must_be_private_before_bootstrap(record, monkeypatch):
    from inventory_github import verify_github_actor

    def process(argv, **kwargs):
        if argv[-1] == "user":
            value = {"login": "operator"}
        elif argv[-1].endswith(record.execution.repository):
            value = {
                "id": 123,
                "owner": {"id": 456},
                "permissions": {"admin": True},
                "private": True,
                "full_name": record.execution.repository,
            }
        else:
            value = {"private": False, "full_name": "example/inventory", "permissions": {"pull": True}}
        return subprocess.CompletedProcess(argv, 0, json.dumps(value), "")

    monkeypatch.setattr(subprocess, "run", process)
    with pytest.raises(InstallationConfigError):
        verify_github_actor(record, "operator", inventory_repository="example/inventory")
