# GCP native identity integration (#2320)

Status: source implementation reviewed; all review findings are repaired. Local
released-server and PostgreSQL qualification passes. Deployment-specific GCP
renewal and effective-authority evidence is not established by this source delivery.
Application authority activation remains the coordinated S8 cutover.

## Concrete runtime choice

Use the released Google Cloud SQL Auth Proxy v2 with automatic IAM database
authentication, private IP, and attached GKE Workload Identity. Run it as a
Kubernetes native sidecar (`initContainers` with `restartPolicy: Always`), with
startup readiness before the application and Kubernetes-managed shutdown for
Jobs. Its database listener binds only to loopback. The released v2.18.3 image is pinned by its OCI index digest; no mutable image
tag is a deployment input.

This follows Google's [GKE connection pattern](https://docs.cloud.google.com/sql/docs/postgres/connect-kubernetes-engine)
and [automatic IAM login contract](https://docs.cloud.google.com/sql/docs/postgres/iam-logins).
The official proxy owns token renewal and remote TLS. Django, psycopg and the
released OpenFGA binary retain their existing database drivers and connect to
the local listener. No custom database backend, token minting, refresh service,
shared proxy Service, service-account key, or new credential protocol is needed.

Enable the Cloud SQL IAM-authentication flag and register the intended service
accounts as IAM database users. Connector identity and normalized PostgreSQL
username must identify the same GSA. Grant instance-bound connection/login
permissions, then independently assign the existing PostgreSQL duties. Existing
operator IAM bindings remain additive and deliberately assigned broad operator
power remains supported. Application administration is a separate explicit grant.

Preserve migration-owner, application DML, function-bound provisioner and
Guacamole duties. OpenFGA gets a separate database on the supported shared
instance, distinct runtime and migration logins, and no application/provisioner
table access. Do not treat Cloud SQL login or a Cloud IAM role as a SQL grant.
The deployment must explicitly reconcile ownership, PUBLIC/default privileges,
inherited roles and function execution before using the new logins.

## Specific integration gaps and requested source scope

| Existing gap | Bounded integration |
| --- | --- |
| `config._database_settings` selects an AWS backend for `DB_IAM_AUTH`; `entrypoint.sh` still hydrates GCP database passwords. | Add an explicit GCP proxy-auth configuration path using the stock Django PostgreSQL backend and local connection metadata; separate app-secret hydration from password hydration. Keep the AWS path intact. |
| The provisioner uses psycopg; the official Python connector does not provide that driver's connection interface. Its Job admission also forbids init containers. | Retain psycopg and admit exactly one approved native Cloud SQL proxy sidecar for this explicit GCP mode. Update the task-runner manifest, parameter contract, and chart/Kustomize admission policies together. |
| The OpenFGA chart shares one datastore secret reference between runtime and migration and does not configure GCP identity/proxy delivery. | Separate runtime/migration database duties and project the native proxy arrangement into the existing chart. Preserve ordered migration prerequisites and explicit deployment-admin store/model publication. |
| The GCP Kustomize deployment and bootstrap Helm renderer do not deliver the OpenFGA configuration and mounted credential/CA files end to end. | Extend the existing closed installation settings, published contract, runtime inventories, canonical renderers and deployment orchestration; reuse chart-owned resources and provider-secret-to-Kubernetes delivery. |
| IAM conditions, settings descriptions and the existing checker still encode migration-only project equality. | Reconcile those incumbents with persistent explicit single-project and separate-project topologies. Preserve exact static-secret bindings and canonical prefix-conditioned dynamic-secret lifecycle/read access. |
| `GCPDBAuth.generate_auth_token` currently logs/interpolates raw provider exceptions. | Replace that leakage with the existing bounded error boundary and add a regression test containing a synthetic credential marker. |

The provisioner admission change is the security decision requiring explicit
authorization. Keep one canonical application container. Permit only the
digest-pinned native proxy image with fixed arguments derived from trusted
deployment parameters, loopback binding, the expected instance, automatic IAM,
non-root/read-only/seccomp security, bounded resources and the expected startup
probe. Reject arbitrary additional init containers, commands, arguments,
environment injection, mounts, privileged flags and identity substitutions.
The proxy uses the existing provisioner Pod identity; it obtains no operator or
OpenFGA credential. Existing Job environment/secret, placement, runtime-plugin
and guest boundaries continue to apply.

Directory integration reuses Firebase Admin initialization and tenant-aware
calls. Read operations require `firebaseauth.users.get`; supported create,
update/revoke and delete effects require `firebaseauth.users.create`,
`firebaseauth.users.update` and `firebaseauth.users.delete`, respectively.
Grant a write permission only for a delivered operation that needs it, using
the [native API permission map](https://docs.cloud.google.com/identity-platform/docs/access-control).
Do not incidentally grant hash export, provider-configuration access or IAM
administration. Reuse existing lifecycle/audit and uncertain-effect handling.

## Policy and secret trust boundary

Keep S2's pinned OpenFGA server/model, private ClusterIP, native TLS with verified
CA/hostname, preshared authentication, disabled Playground/profiler and bounded
pools. Deliver credential/TLS files through named Secret references outside
Terraform payload outputs, Helm values and generated public manifests. Keep
OpenFGA credentials out of the runtime-secret map that grants unrelated workers
access. Authorize only intended runtime clients and deployment administration;
check effective additive network policies and workload/RBAC mutation rights.

The runtime and administration listeners use separate native preshared keys,
TLS keys, workload identities and PostgreSQL logins. The released server's
runtime database duty permits model/store/assertion reads and tuple/changelog
writes, while withholding administrative object mutation. The separate private
administration listener can perform those mutations. Real released-server tests
exercise each denied runtime operation and the successful administration path.
The runtime client remains a trusted tuple writer: arbitrary code with that
credential can write relationships. This arrangement does not provide per-user
HTTP authorization. Experimental access control and custom proxies remain
excluded.

## Verification and activation

Source acceptance mapping (no formal requirements are in scope):

- [x] Native renewal arrangement: `shared/gcp_native_identity/contract.py:66`,
  stock database drivers, existing ADC service-client renewal and the released
  proxy. Actual GCP expiry/reconnection qualification remains deferred.
- [x] Deliberate operator authority: additive native IAM members in
  `platform/terraform/gcp/modules/portal/iam/native_identity.tf:33`, retained
  CI/WIF purpose identities and existing separate service/application grants.
  Effective inherited operator/impersonation evidence remains deferred.
- [x] Policy/secret/datastore restriction: chart-owned private runtime/admin
  deployments, `files/openfga-duties.sql`, native SQL owner/duty reconciliation,
  named provider-to-Kubernetes secret sync and additive network denial tests.
  Released-server tests prove runtime administrative denial and admin success.
- [x] Native patterns and exact permissions: shared validated installation
  readback, canonical bootstrap/release migration renderer, exact instance
  connector/login roles and portal-only `firebaseauth.users.get`; references
  and permission rationales appear in the implementation contract.
- [x] Enforcement retained: Terraform mock tests, negative IAM/admission tests,
  installation contract drift/packaging checks and the repository's required
  ADR, workflow, Terraform, Kubernetes and import checks.

The checked items identify source coverage for review, not completed live
acceptance. Source publication and hosted checks proceed independently of the
operator's broader live testing session. Deployment qualification and S8
authority activation are not claimed by this delivery.

Use red-green tests for closed settings/rendering, exact proxy admission and
rejection of substitutions, secret-reader selection, both project topologies,
database-duty isolation, and credential-safe errors. Exercise the released
OpenFGA/PostgreSQL integration harness and actual Kubernetes Job startup and
completion. Preserve mandatory ADR guard, Terraform/TFLint, actionlint,
kube-linter/kubeconform, import/layer checks and hosted review/CI gates.

On the user-selected existing installation, pair intended operator cloud/app
successes with denied unrelated workload, plugin and guest access. Inspect
inherited IAM, federation attributes, GSA impersonation/attachment, cross-cluster
KSA bindings, named secrets, policy TLS/auth/network paths and SQL grants.
Sustain both cloud/app requests beyond token expiry and establish fresh database
connections beyond expiry; also test unavailable renewal and disabled admission.
Keep operational identities and redacted acceptance evidence in their existing
private destination. No application S8 activation or cloud apply occurs as part
of this proposed-design artifact.
