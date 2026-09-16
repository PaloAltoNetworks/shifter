"""External inventory is data; installation and authorization remain distinct."""

from copy import deepcopy

import pytest
import yaml

from installation import deployment_inventory
from installation.errors import InstallationConfigError


@pytest.fixture
def record():
    return {
        "version": 1,
        "installation": {
            "version": 1,
            "backend": "gcp",
            "deployment": {"name": "unseen-customer", "domain": "range.example.com", "profile": "dev"},
            "settings": {
                "project_id": "customer-runtime",
                "dynamic_secret_project_id": "customer-runtime",
                "region": "us-central1",
            },
            "secrets": {"django_secret_key": "DJANGO_SECRET_KEY"},
        },
        "product": {"repository": "Brad-Edwards/shifter", "revision": "a" * 40},
        "execution": {
            "repository": "example/product",
            "repository_id": "123",
            "owner_id": "456",
            "subject_format": "default",
            "purposes": {
                "deploy": [{"environment": "customer-deploy", "ref": "refs/heads/main", "workflow": "deploy.yml"}],
                "destroy": [
                    {"environment": "customer-destroy", "ref": "refs/heads/main", "workflow": "gcp-dev-destroy.yml"}
                ],
            },
        },
        "state": {
            stack: {"bucket": f"customer-{stack}-state", "prefix": f"deployments/unseen-customer/{stack}"}
            for stack in ("identity", "runner", "platform")
        },
        "secrets": {
            "DJANGO_SECRET_KEY": {
                "store": "gcp-secret-manager",
                "resource": "projects/customer-runtime/secrets/django/versions/1",
            }
        },
        "gcp": {
            "name_prefix": "cust-unseen",
            "evidence_bucket": "customer-unseen-evidence",
            "runner_zone": "us-central1-a",
        },
    }


def test_unseen_deployment_reuses_installation_contract(record):
    result = deployment_inventory.validate_record(record)
    assert result.installation.deployment.name == "unseen-customer"
    assert result.installation.deployment.profile == "dev"
    assert set(result.execution.purposes) == {"deploy", "destroy"}
    assert result.state["identity"].bucket != result.state["platform"].bucket


@pytest.mark.parametrize("profile", ["proof", "customer", "DEV"])
def test_invalid_installation_profiles_fail(record, profile):
    record["installation"]["deployment"]["profile"] = profile
    with pytest.raises(InstallationConfigError):
        deployment_inventory.validate_record(record)


@pytest.mark.parametrize(
    "field,value",
    [
        ("environment", "customer' || true || '"),
        ("environment", "customer:prod"),
        ("ref", "refs/tags/v1"),
        ("ref", "refs/heads/*"),
        ("workflow", "../../deploy.yml"),
        ("workflow", "unreviewed.yml"),
    ],
)
def test_malformed_or_unsupported_execution_context_rejected(record, field, value):
    record["execution"]["purposes"]["deploy"][0][field] = value
    with pytest.raises(InstallationConfigError):
        deployment_inventory.validate_record(record)


def test_purposes_cannot_share_an_environment_even_with_different_refs(record):
    record["execution"]["purposes"]["destroy"][0]["environment"] = "customer-deploy"
    record["execution"]["purposes"]["destroy"][0]["ref"] = "refs/heads/dev"
    with pytest.raises(InstallationConfigError):
        deployment_inventory.validate_record(record)


@pytest.mark.parametrize("mutation", ["purpose", "empty", "mutable", "role", "state", "secret", "project"])
def test_invalid_authority_and_ownership_fail_closed(record, mutation):
    if mutation == "purpose":
        record["execution"]["purposes"]["owner"] = record["execution"]["purposes"].pop("deploy")
    elif mutation == "empty":
        record["execution"]["purposes"] = {}
    elif mutation == "mutable":
        record["product"]["revision"] = "main"
    elif mutation == "role":
        record["gcp"]["roles"] = ["roles/owner"]
    elif mutation == "state":
        record["state"]["platform"] = record["state"]["identity"]
    elif mutation == "secret":
        record["secrets"]["DJANGO_SECRET_KEY"]["resource"] = "plaintext-not-a-reference"
    else:
        record["gcp"]["identity_project_id"] = record["installation"]["settings"]["project_id"]
    with pytest.raises(InstallationConfigError):
        deployment_inventory.validate_record(record)


def test_aws_uses_the_same_envelope_and_reference_convention(record):
    record.pop("gcp")
    record["installation"].update(
        backend="aws",
        settings={"region": "us-east-2"},
        secrets={"django_secret_key": "DJANGO_SECRET_KEY", "db_password": "DB_PASSWORD"},
    )
    record["secrets"] = {
        name: {
            "store": "aws-secrets-manager",
            "resource": f"arn:aws:secretsmanager:us-east-2:123456789012:secret:{name}",
        }
        for name in ("DJANGO_SECRET_KEY", "DB_PASSWORD")
    }
    record["execution"]["purposes"]["destroy"][0]["workflow"] = "aws-env-destroy.yml"
    assert deployment_inventory.validate_record(record).installation.backend == "aws"


def test_loader_rejects_duplicate_keys_and_symlink_escape(tmp_path, record):
    root = tmp_path / "inventory"
    root.mkdir()
    outside = tmp_path / "outside.yaml"
    outside.write_text(yaml.safe_dump(record))
    (root / "escape.yaml").symlink_to(outside)
    with pytest.raises(InstallationConfigError):
        deployment_inventory.load_record(root, "escape.yaml")
    (root / "duplicate.yaml").write_text("version: 1\nversion: 1\n")
    with pytest.raises(InstallationConfigError):
        deployment_inventory.load_record(root, "duplicate.yaml")


def test_error_does_not_echo_private_rejected_values(record):
    record["secrets"]["DJANGO_SECRET_KEY"]["resource"] = "PRIVATE-REJECTED-VALUE"
    with pytest.raises(InstallationConfigError) as failure:
        deployment_inventory.validate_record(record)
    assert "PRIVATE-REJECTED-VALUE" not in str(failure.value)


def test_deployment_project_requires_unique_resource_and_state_ownership(record):
    first = deployment_inventory.validate_record(record)
    second = deepcopy(record)
    second["installation"]["deployment"]["name"] = "another-customer"
    with pytest.raises(InstallationConfigError):
        deployment_inventory.validate_ownership([first, deployment_inventory.validate_record(second)])


def test_loader_bounds_the_input_before_parsing(tmp_path):
    (tmp_path / "large.yaml").write_bytes(b" " * 1_048_577)
    with pytest.raises(InstallationConfigError):
        deployment_inventory.load_record(tmp_path, "large.yaml")


def test_gcp_projection_uses_one_project_and_keeps_purpose_accounts_separate(record):
    from installation.deployment_identity_gcp import identity_tfvars

    result = identity_tfvars(deployment_inventory.validate_record(record))
    assert result["project_id"] == "customer-runtime"
    assert "capability_project_id" not in result
    assert result["environment"] == "unseen-customer"
    assert result["name_prefix"] == "cust-unseen"
    assert result["release_evidence_bucket_name"] == "customer-unseen-evidence"
    assert set(result["purpose_contexts"]) == {"deploy", "destroy"}
    assert result["terraform_state_bucket_name"] == "customer-platform-state"
    assert "roles" not in result


def test_rendered_condition_keeps_tuples_together_and_binds_workflow(record):
    from installation.deployment_identity_gcp import trust_condition

    result = trust_condition(deployment_inventory.validate_record(record).execution)
    assert "assertion.repository_id == '123'" in result
    assert "assertion.repository_owner_id == '456'" in result
    assert "assertion.workflow_ref == 'example/product/.github/workflows/deploy.yml@refs/heads/main'" in result
    assert "assertion.sub == 'repo:example/product:environment:customer-deploy'" in result
    assert "assertion.ref == 'refs/heads/main'" in result
    assert "assertion.event_name == 'workflow_dispatch'" in result


def test_projection_is_order_independent_and_reusable_workflow_is_revision_bound(record):
    from installation.deployment_identity_gcp import identity_tfvars, trust_condition

    context = record["execution"]["purposes"]["deploy"][0]
    context["reusable_workflow"] = "Brad-Edwards/shifter/.github/workflows/_gcp-dev.yml@" + "a" * 40
    first = deployment_inventory.validate_record(record)
    record["execution"]["purposes"] = dict(reversed(list(record["execution"]["purposes"].items())))
    second = deployment_inventory.validate_record(record)
    assert identity_tfvars(first) == identity_tfvars(second)
    assert trust_condition(first.execution) == trust_condition(second.execution)
    assert "assertion.job_workflow_ref == 'Brad-Edwards/shifter/.github/workflows/_gcp-dev.yml@" in trust_condition(
        first.execution
    )


def test_two_deployments_have_their_own_projects_and_state(record):
    first = deployment_inventory.validate_record(record)
    second = deepcopy(record)
    second["installation"]["deployment"]["name"] = "second-customer"
    second["installation"]["settings"]["project_id"] = "second-runtime"
    second["gcp"]["name_prefix"] = "second-customer"
    second["gcp"]["evidence_bucket"] = "second-evidence"
    for stack in second["state"]:
        second["state"][stack]["bucket"] = f"second-{stack}-state"
    for contexts in second["execution"]["purposes"].values():
        for context in contexts:
            context["environment"] = "second-" + context["environment"]
    deployment_inventory.validate_ownership([first, deployment_inventory.validate_record(second)])
    second["installation"]["settings"]["project_id"] = record["installation"]["settings"]["project_id"]
    with pytest.raises(InstallationConfigError):
        deployment_inventory.validate_ownership([first, deployment_inventory.validate_record(second)])
    second["installation"]["settings"]["project_id"] = "second-runtime"
    second["state"]["identity"]["bucket"] = record["state"]["identity"]["bucket"]
    second["state"]["identity"]["prefix"] = "different/prefix"
    with pytest.raises(InstallationConfigError):
        deployment_inventory.validate_ownership([first, deployment_inventory.validate_record(second)])


def test_inventory_parser_rejects_malformed_utf8_and_merge_keys():
    for payload in (b"\xff", b"key: &a {x: 1}\nmerged: {<<: *a}", b"[]", b""):
        with pytest.raises(InstallationConfigError):
            deployment_inventory.parse_record(payload)


def test_loader_rejects_directory_symlinks_and_special_files(tmp_path, record):
    import os

    (tmp_path / "real").mkdir()
    (tmp_path / "real" / "record.yaml").write_text(yaml.safe_dump(record))
    (tmp_path / "link").symlink_to(tmp_path / "real", target_is_directory=True)
    os.mkfifo(tmp_path / "pipe.yaml")
    for path in ("link/record.yaml", "pipe.yaml", "../outside.yaml", str(tmp_path / "real/record.yaml")):
        with pytest.raises(InstallationConfigError):
            deployment_inventory.load_record(tmp_path, path)
    assert (
        deployment_inventory.load_record(tmp_path, "real/record.yaml").installation.deployment.name == "unseen-customer"
    )


@pytest.mark.parametrize("capability", ["build_read_bucket_names", "platform_external_bucket_names"])
def test_bucket_capabilities_cannot_bypass_state_or_evidence_isolation(record, capability):
    record["gcp"][capability] = [record["state"]["identity"]["bucket"]]
    with pytest.raises(InstallationConfigError):
        deployment_inventory.validate_record(record)


@pytest.mark.parametrize("subject_format", ["default", "immutable"])
def test_published_schema_is_a_usable_external_shape_contract(record, subject_format):
    import json
    from pathlib import Path

    import jsonschema

    schema_path = Path(__file__).parents[1] / "published_contract/deployment-inventory.v1.schema.json"
    schema = json.loads(schema_path.read_text())
    jsonschema.Draft202012Validator.check_schema(schema)
    record["execution"]["subject_format"] = subject_format
    jsonschema.validate(record, schema)
    record["execution"]["unrestricted_policy"] = "true"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(record, schema)


def test_single_project_record_owns_identities_runner_and_application(record):
    from installation.deployment_identity_gcp import identity_tfvars

    result = deployment_inventory.validate_record(record)
    deployment_inventory.validate_ownership([result])
    assert identity_tfvars(result)["project_id"] == record["installation"]["settings"]["project_id"]
    assert "identity_project_id" not in result.gcp.model_dump()
    assert "runner_project_id" not in result.gcp.model_dump()


@pytest.mark.parametrize("field", ["identity_project_id", "runner_project_id"])
def test_extra_project_configuration_is_not_supported(record, field):
    record["gcp"][field] = "another-project"
    with pytest.raises(InstallationConfigError):
        deployment_inventory.validate_record(record)


@pytest.mark.parametrize(
    "subject_format,prefix",
    [
        ("default", "repo:example/product"),
        ("immutable", "repo:example@456/product@123"),
    ],
)
def test_subject_format_binds_reviewed_repository_ids(record, subject_format, prefix):
    from installation.deployment_identity_gcp import identity_tfvars, subject, trust_condition

    record["execution"]["subject_format"] = subject_format
    parsed = deployment_inventory.validate_record(record)
    expected = prefix + ":environment:customer-deploy"
    assert subject(parsed.execution, "customer-deploy") == expected
    condition = trust_condition(parsed.execution)
    assert f"assertion.sub == '{expected}'" in condition
    assert "assertion.repository_id == '123'" in condition
    assert "assertion.repository_owner_id == '456'" in condition
    assert identity_tfvars(parsed)["github_subject_format"] == subject_format
