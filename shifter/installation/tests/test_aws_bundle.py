"""Tests for the AWS (EKS) backend bundle parity work (#1828).

These cover the parts the AWS parity build fills in over the earlier entry: the full
generated-output projection derived from the AWS runtime inventory (classified and in
agreement with the inventory), the enriched validation checks that give ``shifter-config
doctor`` real pre-deploy prerequisite detection, and the secret reference grammar. The
provisional/complete split of the generic bundle invariants lives in ``test_registry.py``.

Unlike GCP, the AWS platform runtime env is not enumerated in full: the complete env is
assembled from the Terraform ``runtime_env`` output at deploy time. The contract-owned
projection is therefore the guaranteed set — the renderer-validated required keys plus the
renderer-owned keys — and deliberately excludes the provisioner-forwarding set (a value
hydrated from a secret reference after startup is not a renderer output and must never enter
a ConfigMap).
"""

from __future__ import annotations

from installation import runtime_inventory_aws
from installation.contract import (
    PROMPT_REFERENCE,
    OutputDestination,
    OutputKind,
    OutputSensitivity,
    ProcessRole,
)
from installation.registry import get_backend_bundle

# The complete RUNTIME_ENV projection the renderer emits into the ConfigMap: required,
# renderer-owned, and the range/portal topology the Terraform provisioner_env re-supplies,
# minus hydrated-secret keys. This is the drift-proof mirror the bundle is built from; the
# oracle test in scripts/bootstrap/tests/test_aws_eks.py confirms a representative render
# emits exactly this set.
_EXPECTED_RUNTIME_ENV_KEYS = set(runtime_inventory_aws.AWS_GENERATED_RUNTIME_ENV_KEYS)


def _aws():
    return get_backend_bundle("aws")


def _secret(logical_name):
    return next(s for s in _aws().required_secrets if s.logical_name == logical_name)


class TestAwsSecretReferencePattern:
    def test_aws_declares_the_operator_supplied_app_and_db_secrets(self):
        assert {s.logical_name for s in _aws().required_secrets} == {"django_secret_key", "db_password"}

    def test_both_secrets_have_a_reference_pattern(self):
        for name in ("django_secret_key", "db_password"):
            assert _secret(name).reference_pattern is not None, name

    def test_prompt_is_always_a_valid_reference(self):
        assert _secret("django_secret_key").matches_reference(PROMPT_REFERENCE) is True
        assert _secret("db_password").matches_reference(PROMPT_REFERENCE) is True

    def test_secrets_manager_name_or_arn_matches(self):
        secret = _secret("django_secret_key")
        assert secret.matches_reference("shifter/prod/django-secret-key") is True
        assert (
            secret.matches_reference(
                "arn:aws:secretsmanager:us-east-2:123456789012:secret:shifter/prod/django-secret-key-AbCdEf"
            )
            is True
        )

    def test_github_actions_secret_or_env_var_name_matches(self):
        secret = _secret("db_password")
        assert secret.matches_reference("DB_PASSWORD") is True
        assert secret.matches_reference("db_password") is True

    def test_malformed_references_are_rejected(self):
        secret = _secret("django_secret_key")
        # A reference with whitespace is not a single-line reference token.
        assert secret.matches_reference("has spaces") is False
        assert secret.matches_reference("") is False

    def test_the_shipped_example_references_are_valid(self):
        # examples/aws.yaml uses Secrets Manager path-style references.
        assert _secret("django_secret_key").matches_reference("shifter/prod/django-secret-key") is True
        assert _secret("db_password").matches_reference("shifter/prod/db-password") is True


class TestAwsGeneratedOutputs:
    def _by_name(self):
        return {o.name: o for o in _aws().generated_outputs}

    def test_runtime_env_outputs_agree_with_the_runtime_inventory_key_set(self):
        # The RUNTIME_ENV projection is the single, drift-proof mirror of the AWS runtime
        # inventory's guaranteed key set (renderer-validated required + renderer-owned).
        names = {o.name for o in _aws().generated_outputs if o.kind is OutputKind.RUNTIME_ENV}
        assert names == _EXPECTED_RUNTIME_ENV_KEYS

    def test_oidc_secret_id_is_a_runtime_env_secret_reference(self):
        output = self._by_name()["OIDC_SECRET_ID"]
        assert output.kind is OutputKind.RUNTIME_ENV
        assert output.sensitivity is OutputSensitivity.SECRET_REFERENCE
        # A reference rides the runtime env; the value stays in the secret store.
        assert output.destination is OutputDestination.RUNTIME_ENV

    def test_secret_arn_aliases_are_compat_alias_references(self):
        outputs = self._by_name()
        for name in ("APP_SECRET_ARN", "DB_SECRET_ARN"):
            assert outputs[name].kind is OutputKind.COMPAT_ALIAS, name
            assert outputs[name].sensitivity is OutputSensitivity.SECRET_REFERENCE, name

    def test_non_secret_runtime_outputs_are_public(self):
        outputs = self._by_name()
        for name in ("CLOUD_PROVIDER", "SITE_URL", "AWS_REGION", "STORAGE_BUCKET_NAME", "AUTH_PROVIDER"):
            assert outputs[name].sensitivity is OutputSensitivity.PUBLIC, name

    def test_no_generated_output_is_a_secret_value(self):
        # Secret *values* never ride a ConfigMap-bound runtime env — only references.
        assert all(o.sensitivity is not OutputSensitivity.SECRET_VALUE for o in _aws().generated_outputs)

    def test_cloud_provider_reaches_all_runtime_roles_including_provisioner(self):
        # The standalone provisioner reads CLOUD_PROVIDER to select its adapter family.
        assert ProcessRole.PROVISIONER in self._by_name()["CLOUD_PROVIDER"].process_roles

    def test_every_runtime_output_declares_at_least_portal_and_worker(self):
        for output in _aws().generated_outputs:
            assert ProcessRole.PORTAL in output.process_roles, output.name
            assert ProcessRole.WORKER in output.process_roles, output.name

    def test_process_roles_reflect_actual_consumers_not_blanket(self):
        outputs = self._by_name()
        # A projection key that is also in the provisioner-forwarding set declares the
        # provisioner consumer (AWS_REGION, ENVIRONMENT, and the range/portal topology keys
        # are forwarded to the Job).
        assert ProcessRole.PROVISIONER in outputs["AWS_REGION"].process_roles
        assert ProcessRole.PROVISIONER in outputs["ENVIRONMENT"].process_roles
        assert ProcessRole.PROVISIONER in outputs["DB_HOST"].process_roles
        assert ProcessRole.PROVISIONER in outputs["KALI_AMI_ID"].process_roles
        # A projection key not in the forwarding set is portal/worker only — it is not
        # published to the provisioner (the Job sources its bucket keys from the forwarded
        # AGENT_S3_BUCKET / STATE_BUCKET_URL, not STORAGE_BUCKET_NAME).
        assert set(outputs["STORAGE_BUCKET_NAME"].process_roles) == {ProcessRole.PORTAL, ProcessRole.WORKER}
        assert set(outputs["SITE_URL"].process_roles) == {ProcessRole.PORTAL, ProcessRole.WORKER}
        assert set(outputs["OIDC_ISSUER_URL"].process_roles) == {ProcessRole.PORTAL, ProcessRole.WORKER}

    def test_no_projection_key_declares_a_kubernetes_range_task_consumer(self):
        # AWS ranges are delivered on ECS/VM, not as Kubernetes range-task pods, so unlike the
        # GCP bundle no AWS generated output declares the range-task consumer.
        assert all(ProcessRole.RANGE_TASK not in o.process_roles for o in _aws().generated_outputs)

    def test_projection_includes_forwarded_topology_but_excludes_hydrated_secrets(self):
        # The complete projection enumerates the range/portal topology the renderer emits into
        # the ConfigMap (so every emitted key carries classification), but a value hydrated
        # from a secret reference after startup (DC_DOMAIN_PASSWORD) is never a ConfigMap value.
        names = {o.name for o in _aws().generated_outputs}
        assert "DB_HOST" in names
        assert "KALI_AMI_ID" in names
        assert "RANGE_VPC_ID" in names
        assert "DC_DOMAIN_PASSWORD" not in names
        # DB_PASSWORD / FIELD_ENCRYPTION_KEY are not forwarded at all (RDS IAM auth).
        assert "DB_PASSWORD" not in names


class TestAwsPublishedSettingsSchemaConstraints:
    """The published settings_schema carries the same region constraint the model enforces,
    so a contract consumer validating against the published schema cannot accept a region
    load_root_config would reject."""

    def _validator(self):
        import jsonschema

        from installation.publication import build_contract_artifact

        schema = build_contract_artifact()["backends"]["aws"]["settings_schema"]
        return jsonschema.Draft202012Validator(schema)

    def test_valid_settings_pass_the_published_schema(self):
        assert self._validator().is_valid({"region": "us-east-2"})

    def test_published_schema_rejects_what_the_model_rejects(self):
        validator = self._validator()
        # Malformed region (uppercase / underscore / missing number); unknown key; missing
        # required region — all rejected by the published schema, matching AwsSettings.
        assert not validator.is_valid({"region": "US-East-2"})
        assert not validator.is_valid({"region": "us_east_2"})
        assert not validator.is_valid({"region": "useast"})
        assert not validator.is_valid({"region": "us-east-2", "bogus": "x"})
        assert not validator.is_valid({})


class TestAwsValidationChecks:
    def _check_names(self):
        return {c.name for c in _aws().validation_checks}

    def test_declares_the_canonical_aws_validation_front_doors(self):
        assert self._check_names() >= {"root-config", "terraform-fmt", "helm-template"}

    def test_wires_doctor_to_the_canonical_eks_preflight(self):
        # doctor must connect to the shared preflight spec (component=eks, profile derived from
        # the root config) rather than only protecting the deploy command or duplicating its
        # checks (ADR-011 lifecycle boundary; #1828 codex cycle 2).
        checks = {c.name: c.command.argv for c in _aws().validation_checks}
        assert "eks-preflight" in checks
        argv = checks["eks-preflight"]
        assert argv[0] == "python3"
        assert "scripts/bootstrap/preflight.py" in argv
        assert "--config" in argv
        assert "shifter.yaml" in argv
        # --component eks selects the isolated EKS root prerequisites, not the legacy defaults.
        assert argv[argv.index("--component") + 1] == "eks"

    def test_every_check_executable_is_a_required_tool(self):
        tool_names = {t.name for t in _aws().required_tools}
        for check in _aws().validation_checks:
            assert check.command.argv[0] in tool_names, check.name

    def test_checks_target_aws_owned_paths(self):
        checks = {c.name: c.command.argv for c in _aws().validation_checks}
        assert "platform/terraform/environments" in checks["terraform-fmt"]
        assert "platform/charts/shifter" in checks["helm-template"]
        # helm-template renders with the AWS profile values so it catches AWS value-shape
        # errors before deploy, not just default-values template errors.
        assert "platform/charts/shifter/values-aws-dev.yaml" in checks["helm-template"]

    def test_does_not_declare_gcp_specific_checks(self):
        # AWS has no platform/k8s/aws overlay; its k8s surface is the shared chart, validated
        # by helm-template. kustomize-render / kube-linter are GCP-overlay-specific.
        names = self._check_names()
        assert "kustomize-render" not in names
