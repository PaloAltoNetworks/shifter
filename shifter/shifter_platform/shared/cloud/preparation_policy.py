"""Fail-closed CEL admission for separately installed preparation Job identities."""

import json
from typing import Any

from shared.cloud.preparation_installation import PreparationInstallation
from shared.preparation_grant import PreparationGrantConfiguration


def preparation_policy(installation: PreparationInstallation) -> dict[str, Any]:
    """The operator owns this policy; adapter installers cannot edit its authority."""
    from shared.cloud.preparation_installation import _resource

    grant = installation.grant
    accounts = {
        grant.builder_service_account: grant.approved_worker_images,
        grant.verifier_service_account: grant.approved_verifier_images,
        grant.cleanup_service_account: [grant.cleanup_image],
    }
    actor = f"system:serviceaccount:{installation.platform_namespace}:{installation.controller_name}"
    uuid = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    pull_check = (
        "variables.p.imagePullSecrets == " + json.dumps([{"name": name} for name in grant.image_pull_secrets])
        if grant.image_pull_secrets
        else "!has(variables.p.imagePullSecrets) || size(variables.p.imagePullSecrets) == 0"
    )
    checks = _identity_checks(grant, accounts, actor, uuid) + _sandbox_checks(pull_check)
    return _resource(
        "ValidatingAdmissionPolicy",
        grant.namespace,
        api="admissionregistration.k8s.io/v1",
        spec={
            "failurePolicy": "Fail",
            "matchConstraints": {
                "resourceRules": [
                    {
                        "apiGroups": ["batch"],
                        "apiVersions": ["v1"],
                        "operations": ["CREATE", "UPDATE"],
                        "resources": ["jobs"],
                    }
                ]
            },
            "variables": [
                {"name": "j", "expression": "object.spec"},
                {"name": "p", "expression": "object.spec.template.spec"},
                {"name": "c", "expression": "object.spec.template.spec.containers[0]"},
            ],
            "validations": [
                {"expression": expression, "message": message, "reason": "Forbidden"} for expression, message in checks
            ],
        },
    )


def _identity_checks(
    grant: PreparationGrantConfiguration,
    accounts: dict[str, list[str]],
    actor: str,
    uuid: str,
) -> list[tuple[str, str]]:
    """Handle identity checks."""
    quote = json.dumps
    return [
        (
            """
            variables.p.nodeSelector == {'iam.gke.io/gke-metadata-server-enabled':'true'} &&
            !has(variables.p.nodeName) && (!has(variables.p.dnsPolicy) || variables.p.dnsPolicy == 'ClusterFirst')
        """,
            "Workers must run on nodes with Workload Identity enabled.",
        ),
        (
            f"request.operation != 'CREATE' || request.userInfo.username == {quote(actor)}",
            "Only the preparation controller may create these Jobs.",
        ),
        (
            "size(variables.p.containers) == 1 && variables.c.name == 'artifact-preparation'",
            "Use exactly one preparation container.",
        ),
        (
            f"""
            variables.p.serviceAccountName in {quote(accounts)} && variables.c.image in
            {quote(accounts)}[variables.p.serviceAccountName]
        """,
            "Use the installed role and its approved image digest.",
        ),
        (
            """
            (!has(variables.c.command) || size(variables.c.command) == 0) && (!has(variables.c.args) ||
            size(variables.c.args) == 0)
        """,
            "Use the pinned image entrypoint without overrides.",
        ),
        (
            """
            !has(variables.c.envFrom) && size(variables.c.env) == 4 && variables.c.env.all(e,
            variables.c.env.filter(other, other.name == e.name).size() == 1)
        """,
            "Use exactly the four unique worker inputs.",
        ),
        (
            f"""
            variables.c.env.all(e, (e.name in ['PREPARATION_OPERATION_ID','PREPARATION_ATTEMPT_ID'] &&
            has(e.value) && !has(e.valueFrom) && e.value.matches('^{uuid}$')) || (e.name ==
            'PREPARATION_ENDPOINT' && has(e.value) && !has(e.valueFrom) && e.value ==
            {quote(grant.worker_endpoint)}) || (e.name == 'PREPARATION_TOKEN' && !has(e.value) &&
            has(e.valueFrom) && has(e.valueFrom.secretKeyRef) &&
            e.valueFrom.secretKeyRef.name.matches('^artifact-preparation-secrets-[a-f0-9]{{16}}$') &&
            e.valueFrom.secretKeyRef.key == e.name && (!has(e.valueFrom.secretKeyRef.optional) ||
            !e.valueFrom.secretKeyRef.optional)))
        """,
            "Worker identities and endpoint are fixed; the credential must use a per-Job Secret.",
        ),
        (
            f"""
            object.metadata.annotations['shifter.dev/task-identity'].matches('^preparation:{uuid}:{uuid}$') &&
            object.metadata.annotations['shifter.dev/task-image'] == variables.c.image
        """,
            "Bind the canonical task and image identities.",
        ),
        (
            """
            variables.c.env.filter(e,e.name=='PREPARATION_OPERATION_ID').all(e,
            object.metadata.annotations['shifter.dev/task-identity'].startsWith('preparation:' + e.value + ':'))
            && variables.c.env.filter(e,e.name=='PREPARATION_ATTEMPT_ID').all(e,
            object.metadata.annotations['shifter.dev/task-identity'].endsWith(':' + e.value))
        """,
            "Environment identities must match the reserved task.",
        ),
        (
            f"""
            variables.j.backoffLimit == 0 && variables.j.ttlSecondsAfterFinished == 3600 &&
            variables.j.activeDeadlineSeconds == {grant.max_duration_seconds}
        """,
            "Keep the installed retry, cleanup and duration bounds.",
        ),
    ]


def _sandbox_checks(pull_check: str) -> list[tuple[str, str]]:
    """Handle sandbox checks."""
    return [
        (
            """
            (!has(variables.j.parallelism) || variables.j.parallelism == 1) && (!has(variables.j.completions) ||
            variables.j.completions == 1) && (!has(variables.j.completionMode) || variables.j.completionMode ==
            'NonIndexed') && (!has(variables.j.suspend) || !variables.j.suspend) &&
            !has(variables.j.podFailurePolicy) && !has(variables.j.successPolicy) && !has(variables.j.managedBy)
        """,
            "Keep a single ordinary Job execution.",
        ),
        (
            """
            variables.p.restartPolicy == 'Never' && variables.p.automountServiceAccountToken == false &&
            (!has(variables.p.hostNetwork) || !variables.p.hostNetwork) && (!has(variables.p.hostPID) ||
            !variables.p.hostPID) && (!has(variables.p.hostIPC) || !variables.p.hostIPC) &&
            !has(variables.p.initContainers) && !has(variables.p.ephemeralContainers)
        """,
            "Worker pods have no Kubernetes token or host access.",
        ),
        (
            """
            variables.c.securityContext.runAsNonRoot && variables.c.securityContext.runAsUser == 1000 &&
            variables.c.securityContext.runAsGroup == 1000 &&
            !variables.c.securityContext.allowPrivilegeEscalation &&
            variables.c.securityContext.readOnlyRootFilesystem && (!has(variables.c.securityContext.privileged)
            || !variables.c.securityContext.privileged) && variables.c.securityContext.capabilities.drop ==
            ['ALL'] && !has(variables.c.securityContext.capabilities.add) &&
            variables.p.securityContext.seccompProfile.type == 'RuntimeDefault'
            && (!has(variables.c.securityContext.seccompProfile) ||
                variables.c.securityContext.seccompProfile.type == 'RuntimeDefault')
            && (!has(variables.c.securityContext.procMount) || variables.c.securityContext.procMount == 'Default')
            && !has(variables.c.securityContext.seLinuxOptions) && !has(variables.p.securityContext.sysctls)
        """,
            "Keep the non-root read-only worker sandbox.",
        ),
        (
            """
            size(variables.p.volumes) == 1 && variables.p.volumes.all(v, v.name == 'tmp' &&
            has(v.emptyDir) && v.emptyDir.medium == 'Memory' && v.emptyDir.sizeLimit == '64Mi') &&
            size(variables.c.volumeMounts) == 1 && variables.c.volumeMounts.all(v, v.name == 'tmp' &&
            v.mountPath == '/tmp' && !has(v.subPath) && !has(v.subPathExpr) && !has(v.mountPropagation))
        """,
            "Use only the bounded memory scratch volume.",
        ),
        (
            pull_check,
            "Use only installed registry credentials.",
        ),
        (
            """
            variables.c.imagePullPolicy == 'IfNotPresent' && variables.c.resources.requests ==
            {'cpu':'100m','memory':'256Mi'} && variables.c.resources.limits == {'cpu':'1','memory':'512Mi'}
        """,
            "Keep fixed worker resource budgets.",
        ),
        (
            """
            !has(variables.c.lifecycle) && !has(variables.c.livenessProbe) && !has(variables.c.readinessProbe)
            && !has(variables.c.startupProbe) && !has(variables.c.workingDir) && !has(variables.p.hostAliases)
            && !has(variables.p.dnsConfig) && !has(variables.p.runtimeClassName)
        """,
            "No alternate execution hooks or name-resolution overrides are allowed.",
        ),
    ]
