"""Tests for the completed GCP backend bundle (#729).

These cover the parts the GCP migration fills in over the provisional entry: the secret
reference grammar, the full generated-output projection (classified and in agreement with
the runtime inventory), and the validation checks. The provisional/complete split of the
generic bundle invariants lives in ``test_registry.py``.
"""

from __future__ import annotations

from installation import runtime_inventory
from installation.contract import (
    PROMPT_REFERENCE,
    OutputDestination,
    OutputKind,
    OutputSensitivity,
    ProcessRole,
)
from installation.registry import get_backend_bundle

# Secret-reference keys among the GCP generated runtime env: only the reference id rides
# the ConfigMap-bound runtime env; the value stays in Secret Manager.
_GCP_SECRET_ID_KEYS = frozenset(
    {
        "APP_SECRET_ID",
        "DB_SECRET_ID",
        "REDIS_SECRET_ID",
        "GUACAMOLE_SECRET_ID",
        "GDC_ACCESS_SECRET_ID",
        "DC_DOMAIN_PASSWORD_SECRET_ID",
        "EMAIL_API_KEY_SECRET_ID",
    }
)


def _gcp():
    return get_backend_bundle("gcp")


def _django_secret():
    return next(s for s in _gcp().required_secrets if s.logical_name == "django_secret_key")


class TestGcpSecretReferencePattern:
    def test_gcp_declares_only_the_operator_supplied_django_secret(self):
        # DB / Redis / Guacamole / GDC / DC / email secrets are Terraform-created and owned;
        # they are generated-output references, not a second root reference.
        assert {s.logical_name for s in _gcp().required_secrets} == {"django_secret_key"}

    def test_django_secret_has_a_reference_pattern(self):
        assert _django_secret().reference_pattern is not None

    def test_prompt_is_always_a_valid_reference(self):
        assert _django_secret().matches_reference(PROMPT_REFERENCE) is True

    def test_secret_manager_resource_name_matches(self):
        secret = _django_secret()
        assert secret.matches_reference("projects/acme-shifter/secrets/django-secret-key/versions/latest") is True
        assert secret.matches_reference("projects/acme/secrets/django/versions/3") is True

    def test_github_actions_secret_or_env_var_name_matches(self):
        secret = _django_secret()
        assert secret.matches_reference("DJANGO_SECRET_KEY") is True
        assert secret.matches_reference("django_secret_key") is True

    def test_aws_style_path_and_malformed_refs_are_rejected(self):
        secret = _django_secret()
        # An AWS Secrets Manager path is not a valid GCP reference.
        assert secret.matches_reference("shifter/prod/django-secret-key") is False
        # A partial resource name or one with whitespace is rejected.
        assert secret.matches_reference("projects/acme/secrets/django") is False
        assert secret.matches_reference("has spaces") is False

    def test_the_shipped_example_reference_is_valid(self):
        # examples/gcp.yaml uses a full Secret Manager resource name.
        secret = _django_secret()
        assert (
            secret.matches_reference("projects/your-gcp-project/secrets/shifter-django-secret-key/versions/latest")
            is True
        )

    def test_published_reference_pattern_is_anchored_against_substring_garbage(self):
        # reference_pattern is published in the backend contract and documented as anchored.
        # It must enforce the same full-string grammar an external consumer's re.match/search
        # would apply as the in-process re.fullmatch — i.e. prefix/suffix garbage is rejected
        # (#729 codex cycle 3 finding).
        import re

        from installation.publication import build_contract_artifact

        gcp = build_contract_artifact()["backends"]["gcp"]
        pattern = next(
            s["reference_pattern"] for s in gcp["required_secrets"] if s["logical_name"] == "django_secret_key"
        )
        assert pattern.startswith("^") and pattern.endswith("$")
        rx = re.compile(pattern)
        # Bare valid references match at the start.
        assert rx.match("DJANGO_SECRET_KEY")
        assert rx.match("projects/p/secrets/n/versions/latest")
        # Prefix and suffix garbage are rejected because the published pattern is anchored.
        assert rx.match("DJANGO_SECRET_KEY and more") is None
        assert rx.match("garbage projects/p/secrets/n/versions/latest") is None
        assert rx.search("leading-junk DJANGO_SECRET_KEY trailing-junk") is None


class TestGcpGeneratedOutputs:
    def _by_name(self):
        return {o.name: o for o in _gcp().generated_outputs}

    def test_runtime_env_outputs_agree_with_the_runtime_inventory_key_set(self):
        # The GeneratedOutput RUNTIME_ENV projection is the single, drift-proof mirror of
        # runtime_inventory's authoritative GCP key set (required + optional).
        names = {o.name for o in _gcp().generated_outputs if o.kind is OutputKind.RUNTIME_ENV}
        expected = set(runtime_inventory.GCP_GENERATED_RUNTIME_ENV_KEYS) | set(
            runtime_inventory.GCP_OPTIONAL_GENERATED_RUNTIME_ENV_KEYS
        )
        assert names == expected

    def test_secret_id_outputs_are_classified_as_secret_references(self):
        outputs = self._by_name()
        for name in _GCP_SECRET_ID_KEYS:
            assert outputs[name].sensitivity is OutputSensitivity.SECRET_REFERENCE, name
            # A reference rides the runtime env; the value stays in the secret store.
            assert outputs[name].destination is OutputDestination.RUNTIME_ENV, name

    def test_non_secret_runtime_outputs_are_public(self):
        outputs = self._by_name()
        # IDENTITY_PLATFORM_API_KEY is browser client configuration, not an auth secret.
        assert outputs["IDENTITY_PLATFORM_API_KEY"].sensitivity is OutputSensitivity.PUBLIC
        for name in ("CLOUD_PROVIDER", "SITE_URL", "STORAGE_BUCKET_NAME", "DB_HOST"):
            assert outputs[name].sensitivity is OutputSensitivity.PUBLIC, name

    def test_no_generated_output_is_a_secret_value(self):
        # Secret *values* never ride a ConfigMap-bound runtime env — only references.
        assert all(o.sensitivity is not OutputSensitivity.SECRET_VALUE for o in _gcp().generated_outputs)

    def test_cloud_provider_reaches_all_runtime_roles_including_provisioner(self):
        outputs = self._by_name()
        # The standalone provisioner reads CLOUD_PROVIDER to select its adapter family.
        assert ProcessRole.PROVISIONER in outputs["CLOUD_PROVIDER"].process_roles

    def test_every_runtime_output_declares_at_least_portal_and_worker(self):
        for output in _gcp().generated_outputs:
            assert ProcessRole.PORTAL in output.process_roles, output.name
            assert ProcessRole.WORKER in output.process_roles, output.name

    def test_process_roles_reflect_actual_consumers_not_blanket(self):
        outputs = self._by_name()
        # A forwarded operational key reaches the provisioner Job but is not range-guest config.
        assert set(outputs["DB_HOST"].process_roles) == {
            ProcessRole.PORTAL,
            ProcessRole.WORKER,
            ProcessRole.PROVISIONER,
        }
        # A GCP_RANGE_* guest-configuration key additionally declares the range-task consumer.
        linux_image = set(outputs["GCP_RANGE_LINUX_IMAGE"].process_roles)
        assert linux_image >= {ProcessRole.PROVISIONER, ProcessRole.RANGE_TASK}
        # A non-forwarded key is portal/worker only — it is not published to the provisioner.
        assert set(outputs["SITE_URL"].process_roles) == {ProcessRole.PORTAL, ProcessRole.WORKER}

    def test_forwarded_role_set_is_a_subset_of_the_generated_keys(self):
        # The forwarded manifest must not name a key the bundle does not generate.
        generated = {o.name for o in _gcp().generated_outputs if o.kind is OutputKind.RUNTIME_ENV}
        assert generated >= runtime_inventory.GCP_PROVISIONER_FORWARDED_RUNTIME_ENV_KEYS


class TestGcpPublishedSettingsSchemaConstraints:
    """The published settings_schema carries the same identifier constraints the model
    enforces, so a contract consumer validating against the published schema cannot accept
    an identifier load_root_config would reject (#729 codex cycle 2 finding 2)."""

    def _validator(self):
        import jsonschema

        from installation.publication import build_contract_artifact

        schema = build_contract_artifact()["backends"]["gcp"]["settings_schema"]
        return jsonschema.Draft202012Validator(schema)

    def test_valid_settings_pass_the_published_schema(self):
        assert self._validator().is_valid({"project_id": "acme-shifter", "region": "us-central1"})

    def test_published_schema_rejects_what_the_model_rejects(self):
        validator = self._validator()
        # project_id too short / uppercase; region malformed; unknown key — all rejected by
        # the published schema, matching GcpBackendSettings.
        assert not validator.is_valid({"project_id": "acme", "region": "us-central1"})
        assert not validator.is_valid({"project_id": "ACME-shifter", "region": "us-central1"})
        assert not validator.is_valid({"project_id": "acme-shifter", "region": "US-Central1"})
        assert not validator.is_valid({"project_id": "acme-shifter", "region": "us-central1", "bogus": "x"})
        # required fields
        assert not validator.is_valid({"region": "us-central1"})


class TestGcpValidationChecks:
    def _check_names(self):
        return {c.name for c in _gcp().validation_checks}

    def test_declares_the_canonical_gcp_validation_front_doors(self):
        assert self._check_names() >= {
            "root-config",
            "terraform-fmt",
            "helm-template",
            "kustomize-render",
            "kube-linter",
        }

    def test_every_check_executable_is_a_required_tool(self):
        tool_names = {t.name for t in _gcp().required_tools}
        for check in _gcp().validation_checks:
            assert check.command.argv[0] in tool_names, check.name

    def test_kube_linter_is_a_required_tool(self):
        assert "kube-linter" in {t.name for t in _gcp().required_tools}

    def test_checks_target_gcp_owned_paths(self):
        checks = {c.name: c.command.argv for c in _gcp().validation_checks}
        assert "platform/terraform/gcp" in checks["terraform-fmt"]
        assert "platform/charts/shifter" in checks["helm-template"]
        assert "platform/k8s/gcp/overlays/gcp-dev" in checks["kustomize-render"]
