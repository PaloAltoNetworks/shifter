"""Contract tests for the backend-neutral Shifter Helm chart."""

from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml


CHART_DIR = Path(__file__).resolve().parents[1]
VALUES_FILES = {
    path.stem.removeprefix("values-"): path
    for path in CHART_DIR.glob("values-*.yaml")
}

# Placeholder AWS edge identity carried by the non-operational values-aws-dev.yaml
# scaffold. Production values are projected by scripts/bootstrap/aws_eks.py from
# Terraform outputs; these are the checked-in stand-ins (account 000000000000).
AWS_DEV_CERTIFICATE_ARN = (
    "arn:aws:acm:us-east-2:000000000000:certificate/"
    "00000000-0000-0000-0000-000000000000"
)
AWS_DEV_WAF_ACL_ARN = (
    "arn:aws:wafv2:us-east-2:000000000000:regional/webacl/shifter-dev/"
    "00000000-0000-0000-0000-000000000000"
)

# GCP rendering is a literal byte contract (#1823): the AWS edge work must not
# change either GCP profile's rendered bytes. Frozen with Helm 3.15.4 and release
# name "contract-test"; regenerate deliberately only when GCP output is meant to
# change.
# Regenerated for #1311 after removing the retired fleet-wide RAES cutover
# selector variables from the shared runtime ConfigMap.
# Regenerated for #28 after adding the warm-pool reconciler worker Deployment.
# Regenerated for #2098 after adding the CTF communication delivery-worker Deployment.
# Regenerated for #2083 after admitting the deployment-scoped dynamic-secret project id.
# Regenerated for #1583 after qualifying portal memory headroom and maintenance-worker startup capacity.
# Regenerated for #2179 after adding the GKE metadata-server egress NetworkPolicy
# (allow-platform/jobs-metadata-server-egress) so the Helm path matches the kustomize base.
GCP_RENDER_SHA256 = {
    "gcp-dev": "dd50c4107538fe50f899160bb8cbb02bf17ed7d0041e8261e8f4ab2d4caf0c9e",
    "gcp-prod": "c92cfb146e141c1acfe4e7b2ef6d2f4738250dc84331465cbade25cf4474d885",
}


def _helm(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["helm", *args],
        check=check,
        cwd=CHART_DIR.parents[2],
        capture_output=True,
        text=True,
    )


def _render(*values_files: Path) -> tuple[str, list[dict[str, object]]]:
    args = ["template", "contract-test", str(CHART_DIR)]
    for values_file in values_files:
        args.extend(["-f", str(values_file)])
    rendered = _helm(*args).stdout
    documents = [
        document
        for document in yaml.safe_load_all(rendered)
        if isinstance(document, dict)
    ]
    return rendered, documents


def _identity(document: dict[str, object]) -> tuple[str, str]:
    metadata = document.get("metadata", {})
    assert isinstance(metadata, dict)
    return str(document.get("kind")), str(metadata.get("name"))


class BackendNeutralChartContractTests(unittest.TestCase):
    def test_chart_has_schema_and_all_backend_profiles(self) -> None:
        schema = json.loads((CHART_DIR / "values.schema.json").read_text())
        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertEqual(
            set(VALUES_FILES),
            {"aws-dev", "aws-proof", "aws-prod", "gcp-dev", "gcp-prod"},
        )

    def test_neutral_defaults_have_no_provider_specific_artifacts(self) -> None:
        rendered, _ = _render()
        forbidden = (
            "cloud.google.com/",
            "networking.gke.io/",
            "gce",
            "35.191.0.0/16",
            "130.211.0.0/22",
            "199.36.153.",
            "us-docker.pkg.dev",
            "amazonaws.com",
        )
        for marker in forbidden:
            self.assertNotIn(marker, rendered)

    def test_every_profile_renders_digest_pinned_images(self) -> None:
        for profile, values_file in VALUES_FILES.items():
            with self.subTest(profile=profile):
                _, documents = _render(values_file)
                deployments = [
                    doc for doc in documents if doc.get("kind") == "Deployment"
                ]
                self.assertTrue(deployments, f"{profile}: no Deployments rendered")
                for document in deployments:
                    pod_template = document["spec"]["template"]
                    containers = pod_template["spec"]["containers"]
                    for container in containers:
                        image = container["image"]
                        self.assertRegex(
                            image,
                            r"^[^@\s]+@sha256:[0-9a-f]{64}$",
                            f"{profile}: {image}",
                        )

    def test_aws_profiles_include_kubernetes_job_launcher_capability(self) -> None:
        """#1826: AWS (EKS) dispatches the provisioner as a Kubernetes Job, so every
        AWS profile renders the dedicated launcher identity, RBAC, ServiceAccounts,
        and the fail-closed admission policy bound to the AWS task-runner contract."""
        required = {
            ("Deployment", "worker-provisioner-launcher"),
            ("ServiceAccount", "provisioner-launcher"),
            ("ServiceAccount", "provisioner"),
            ("Role", "job-launcher"),
            ("RoleBinding", "job-launcher-provisioner-launcher"),
            ("ValidatingAdmissionPolicy", "restrict-provisioner-jobs"),
            ("ValidatingAdmissionPolicyBinding", "restrict-provisioner-jobs"),
        }
        for profile in ("aws-dev", "aws-proof", "aws-prod"):
            with self.subTest(profile=profile):
                rendered, documents = _render(VALUES_FILES[profile])
                identities = {_identity(document) for document in documents}
                self.assertTrue(required.issubset(identities))
                # AWS binds the admission policy to its own task-runner contract,
                # never the GCP one (the AWS-derived env allowlist, not a GCP copy).
                self.assertIn("shifter.dev/task-runner'] == 'aws'", rendered)
                self.assertNotIn("shifter.dev/task-runner'] == 'gcp'", rendered)

    def test_gcp_profiles_retain_compatible_provider_capabilities(self) -> None:
        for profile in ("gcp-dev", "gcp-prod"):
            with self.subTest(profile=profile):
                rendered, documents = _render(VALUES_FILES[profile])
                identities = {_identity(document) for document in documents}
                self.assertIn(("BackendConfig", "portal-web"), identities)
                self.assertIn(("Deployment", "worker-provisioner-launcher"), identities)
                self.assertIn(("Role", "job-launcher"), identities)
                self.assertIn("cloud.google.com/neg", rendered)

    def test_aws_generated_projection_wires_edge_identity_and_secret_references(self) -> None:
        digest = "a" * 64
        generated = {
            "provider": {"name": "aws"},
            "deployment": {"name": "shifter", "profile": "dev"},
            "edge": {
                "hostname": "shifter.example.com",
                "certificateArn": "arn:aws:acm:us-east-2:123456789012:certificate/example",
                "wafAclArn": "arn:aws:wafv2:us-east-2:123456789012:regional/webacl/example/id",
                "ingress": {
                    "enabled": True,
                    "className": "alb",
                    "annotations": {
                        "alb.ingress.kubernetes.io/certificate-arn": (
                            "arn:aws:acm:us-east-2:123456789012:certificate/example"
                        ),
                        "alb.ingress.kubernetes.io/wafv2-acl-arn": (
                            "arn:aws:wafv2:us-east-2:123456789012:regional/webacl/example/id"
                        ),
                        "alb.ingress.kubernetes.io/inbound-cidrs": "203.0.113.0/24",
                    },
                    "host": "shifter.example.com",
                    "tls": {"enabled": False, "secretName": ""},
                    "gcpManagedTls": {
                        "enabled": False,
                        "certificateName": "platform-managed-cert",
                        "frontendConfigName": "platform-frontend-config",
                    },
                },
            },
            "identity": {
                "serviceAccountRoleArns": {
                    "portal": "arn:aws:iam::123456789012:role/shifter-dev-portal",
                    "workers": "arn:aws:iam::123456789012:role/shifter-dev-workers",
                    "ctfScheduler": "arn:aws:iam::123456789012:role/shifter-dev-ctf-scheduler",
                }
            },
            "runtimeEnv": {
                "AUTH_PROVIDER": "oidc",
                "CLOUD_PROVIDER": "aws",
                "ENGINE_TASK_CLUSTER": "arn:aws:ecs:us-east-2:123456789012:cluster/shifter-dev",
                "ENVIRONMENT": "development",
                "OIDC_SECRET_ID": "shifter/dev/cognito",
                "QUEUE_ENGINE_CONSUMER_ID": "https://sqs.us-east-2.amazonaws.com/123456789012/engine",
                "STORAGE_BUCKET_NAME": "shifter-dev-storage",
            },
            "runtime": {
                "secretReferences": {
                    "app": "shifter/dev/app",
                    "database": "shifter/dev/database",
                }
            },
            "images": {
                "platform": f"example.invalid/shifter/platform@sha256:{digest}",
                "guacd": f"example.invalid/shifter/guacd@sha256:{digest}",
                "guacamoleClient": f"example.invalid/shifter/guacamole-client@sha256:{digest}",
                "provisioner": f"example.invalid/shifter/provisioner@sha256:{digest}",
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            generated_path = Path(directory) / "generated.json"
            generated_path.write_text(json.dumps(generated), encoding="utf-8")
            rendered, documents = _render(VALUES_FILES["aws-dev"], generated_path)

        self.assertIn('ingressClassName: "alb"', rendered)
        self.assertIn('host: "shifter.example.com"', rendered)
        self.assertIn("eks.amazonaws.com/role-arn", rendered)
        self.assertIn('CLOUD_PROVIDER: "aws"', rendered)
        self.assertIn('ENVIRONMENT: "development"', rendered)
        self.assertIn('OIDC_SECRET_ID: "shifter/dev/cognito"', rendered)
        self.assertIn('APP_SECRET_ID: "shifter/dev/app"', rendered)
        self.assertIn('DB_SECRET_ID: "shifter/dev/database"', rendered)
        self.assertNotIn("kind: Secret", rendered)
        # #1826: AWS dispatches the provisioner as a Kubernetes Job, so the
        # dedicated launcher renders alongside the edge/secret projection.
        self.assertIn(("Deployment", "worker-provisioner-launcher"), {_identity(d) for d in documents})

    def test_aws_dev_scaffold_renders_alb_edge_with_acm_and_waf(self) -> None:
        rendered, documents = _render(VALUES_FILES["aws-dev"])
        identities = {_identity(document) for document in documents}
        kinds = {kind for kind, _ in identities}

        # A single standard Ingress carrying the ALB class -- no second ingress
        # template, no provider.name branch.
        self.assertIn(("Ingress", "platform-external"), identities)
        ingress = next(
            document
            for document in documents
            if _identity(document) == ("Ingress", "platform-external")
        )
        self.assertEqual(ingress["spec"]["ingressClassName"], "alb")

        # ACM certificate + AWS WAF association ride on ALB controller
        # annotations (Terraform-owned identity, not invented K8s objects), and
        # the public listener is HTTPS only.
        annotations = ingress["metadata"]["annotations"]
        self.assertEqual(
            annotations["alb.ingress.kubernetes.io/certificate-arn"],
            AWS_DEV_CERTIFICATE_ARN,
        )
        self.assertEqual(
            annotations["alb.ingress.kubernetes.io/wafv2-acl-arn"],
            AWS_DEV_WAF_ACL_ARN,
        )
        self.assertEqual(
            annotations["alb.ingress.kubernetes.io/listen-ports"],
            '[{"HTTPS":443}]',
        )
        self.assertEqual(
            annotations["alb.ingress.kubernetes.io/inbound-cidrs"],
            "203.0.113.0/24",
        )

        # No GCP edge objects or identifiers when the GCP capabilities are off.
        for gcp_kind in ("BackendConfig", "ManagedCertificate", "FrontendConfig"):
            self.assertNotIn(gcp_kind, kinds)
        self.assertNotIn("cloud.google.com/", rendered)
        self.assertNotIn("networking.gke.io/", rendered)

        # IRSA is projected onto the workload service accounts.
        self.assertIn("eks.amazonaws.com/role-arn", rendered)

    def test_aws_dev_edge_identity_fields_match_alb_annotations(self) -> None:
        # The renderer and this scaffold keep the explicit edge identity fields
        # equal to their ALB annotation copies; there is no third representation.
        values = yaml.safe_load(VALUES_FILES["aws-dev"].read_text())
        edge = values["edge"]
        annotations = edge["ingress"]["annotations"]
        self.assertEqual(
            edge["certificateArn"],
            annotations["alb.ingress.kubernetes.io/certificate-arn"],
        )
        self.assertEqual(
            edge["wafAclArn"],
            annotations["alb.ingress.kubernetes.io/wafv2-acl-arn"],
        )
        self.assertEqual(edge["hostname"], edge["ingress"]["host"])

    def test_aws_alb_edge_fails_closed_on_incomplete_config(self) -> None:
        # An ALB edge missing its certificate, WAF, hostname, HTTPS-only
        # listener, or the ALB class itself must be rejected by the schema
        # rather than rendering a silently-insecure Ingress.
        base = ["template", "contract-test", str(CHART_DIR), "-f", str(VALUES_FILES["aws-dev"])]
        cases = {
            "missing certificate": ["--set-string", "edge.certificateArn="],
            "missing waf": ["--set-string", "edge.wafAclArn="],
            "missing hostname": ["--set-string", "edge.hostname="],
            "non-https listener": [
                "--set-string",
                r'edge.ingress.annotations.alb\.ingress\.kubernetes\.io/listen-ports=[{"HTTP":80}]',
            ],
            "certificate without alb class": ["--set-string", "edge.ingress.className=nginx"],
            # The ALB controller consumes the annotation values, not the parallel
            # edge.* identity fields, so an empty/malformed annotation value must
            # fail closed even while edge.certificateArn/wafAclArn stay populated.
            "empty certificate annotation": [
                "--set-string",
                r"edge.ingress.annotations.alb\.ingress\.kubernetes\.io/certificate-arn=",
            ],
            "empty waf annotation": [
                "--set-string",
                r"edge.ingress.annotations.alb\.ingress\.kubernetes\.io/wafv2-acl-arn=",
            ],
            "malformed certificate annotation": [
                "--set-string",
                r"edge.ingress.annotations.alb\.ingress\.kubernetes\.io/certificate-arn=not-an-arn",
            ],
        }
        for label, overrides in cases.items():
            with self.subTest(case=label):
                result = _helm(*base, *overrides, check=False)
                self.assertNotEqual(
                    result.returncode,
                    0,
                    f"incomplete AWS edge ({label}) should fail schema validation",
                )

    def test_gcp_renders_are_byte_identical_to_frozen_baseline(self) -> None:
        for profile, expected in GCP_RENDER_SHA256.items():
            with self.subTest(profile=profile):
                rendered, _ = _render(VALUES_FILES[profile])
                actual = hashlib.sha256(rendered.encode("utf-8")).hexdigest()
                self.assertEqual(
                    actual,
                    expected,
                    f"{profile} render drifted from the frozen GCP byte contract",
                )

    def test_security_and_default_deny_are_preserved_for_every_profile(self) -> None:
        for profile, values_file in VALUES_FILES.items():
            with self.subTest(profile=profile):
                _, documents = _render(values_file)
                identities = {_identity(document) for document in documents}
                self.assertIn(("NetworkPolicy", "default-deny-platform"), identities)
                self.assertIn(("NetworkPolicy", "default-deny-jobs"), identities)
                deployments = [
                    doc for doc in documents if doc.get("kind") == "Deployment"
                ]
                self.assertTrue(deployments, f"{profile}: no Deployments rendered")
                for document in deployments:
                    pod_spec = document["spec"]["template"]["spec"]
                    self.assertEqual(
                        pod_spec["securityContext"]["seccompProfile"]["type"],
                        "RuntimeDefault",
                    )
                    for container in pod_spec["containers"]:
                        context = container["securityContext"]
                        self.assertFalse(context["allowPrivilegeEscalation"])
                        self.assertTrue(context["readOnlyRootFilesystem"])
                        self.assertTrue(context["runAsNonRoot"])
                        self.assertIn("ALL", context["capabilities"]["drop"])
                        self.assertIn("requests", container["resources"])
                        self.assertIn("limits", container["resources"])

    def test_access_node_pool_placement_is_scoped_to_the_gcp_dialers(self) -> None:
        # #1711 / ADR-039-R9: the access-workload isolation depends on portal + guacd
        # (and only those) landing on the exclusive access pool. Assert the actual
        # pod-spec placement rather than trusting the opaque byte-hash contract: a
        # wrong selector key, a dropped toleration, or a NoExecute/NoSchedule slip
        # would silently regain a green hash after regeneration.
        expected_selector = {"node-restriction.kubernetes.io/shifter-pool": "access"}
        expected_toleration = {
            "key": "dedicated",
            "operator": "Equal",
            "value": "access",
            "effect": "NoSchedule",
        }

        def _pod_spec(documents: list[dict[str, object]], name: str) -> dict[str, object]:
            for document in documents:
                if _identity(document) == ("Deployment", name):
                    return document["spec"]["template"]["spec"]
            raise AssertionError(f"Deployment {name} not rendered")

        for profile in ("gcp-dev", "gcp-prod"):
            with self.subTest(profile=profile):
                _, documents = _render(VALUES_FILES[profile])
                for dialer in ("portal-web", "guacd"):
                    pod_spec = _pod_spec(documents, dialer)
                    self.assertEqual(pod_spec.get("nodeSelector"), expected_selector)
                    self.assertIn(expected_toleration, pod_spec.get("tolerations", []))
                # Non-dialers must never carry the access placement.
                for other in ("guacamole-client", "worker-engine"):
                    pod_spec = _pod_spec(documents, other)
                    self.assertNotIn(
                        "node-restriction.kubernetes.io/shifter-pool",
                        pod_spec.get("nodeSelector", {}),
                    )

        # AWS/neutral profiles (gcpAccessNodePool false) never acquire the GCP label.
        for profile in ("aws-dev", "aws-proof", "aws-prod"):
            with self.subTest(profile=profile):
                _, documents = _render(VALUES_FILES[profile])
                for dialer in ("portal-web", "guacd"):
                    pod_spec = _pod_spec(documents, dialer)
                    self.assertNotIn(
                        "node-restriction.kubernetes.io/shifter-pool",
                        pod_spec.get("nodeSelector", {}),
                    )

    def test_schema_rejects_tag_shaped_image_identity(self) -> None:
        result = _helm(
            "template",
            "contract-test",
            str(CHART_DIR),
            "--set-string",
            "images.platform=latest",
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        # Helm names the offending field with either dot ("images.platform") or
        # JSON-pointer ("/images/platform") path syntax depending on the schema
        # validator its build links; match both so the check is not brittle to a
        # helm patch/build difference between local and CI.
        self.assertRegex(result.stderr, r"images[./]platform")

    def test_schema_rejects_provider_feature_without_capability(self) -> None:
        result = _helm(
            "template",
            "contract-test",
            str(CHART_DIR),
            "--set",
            "services.portal.backendConfig.enabled=true",
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("gcpBackendConfig", result.stderr)

    def test_ctf_communication_worker_renders_for_every_profile(self) -> None:
        """#2098: the scoped-communication delivery worker must ship in every backend
        profile (not just render incidentally under the GCP byte hash), with its
        least-privilege identity, worker command, and heartbeat liveness probe."""
        expected_args = [
            "python",
            "manage.py",
            "drain_ctf_communication_deliveries",
            "--loop",
            "--interval",
            "10",
        ]
        for profile, values_file in VALUES_FILES.items():
            with self.subTest(profile=profile):
                _, documents = _render(values_file)
                deployment = next(
                    (d for d in documents if _identity(d) == ("Deployment", "ctf-communication-worker")),
                    None,
                )
                self.assertIsNotNone(
                    deployment, f"{profile}: ctf-communication-worker Deployment must render"
                )
                assert deployment is not None  # for type-narrowing
                pod_spec = deployment["spec"]["template"]["spec"]
                # Least-privilege worker identity, no provisioner Job privileges, tokenless.
                self.assertEqual(pod_spec["serviceAccountName"], "workers")
                self.assertFalse(pod_spec["automountServiceAccountToken"])
                container = pod_spec["containers"][0]
                self.assertEqual(container["args"], expected_args)
                self.assertIn(
                    "ctf-communication-worker-heartbeat",
                    " ".join(container["livenessProbe"]["exec"]["command"]),
                )
                self.assertEqual(container["envFrom"][0]["configMapRef"]["name"], "platform-runtime")
        # The neutral (provider-agnostic) defaults also render the worker.
        _, neutral = _render()
        self.assertIn(("Deployment", "ctf-communication-worker"), {_identity(d) for d in neutral})


if __name__ == "__main__":
    unittest.main()
