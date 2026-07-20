"""Contract enums: backend maturity, output classification, and capability vocab.

Split out of the former monolithic ``installation.contract`` module (#561) with
definitions unchanged; re-exported by :mod:`installation.contract` so the public
import surface stays identical.
"""

from __future__ import annotations

from enum import StrEnum


class BackendMaturity(StrEnum):
    """How production-ready a backend bundle is."""

    EXPERIMENTAL = "experimental"
    BETA = "beta"
    STABLE = "stable"
    DEPRECATED = "deprecated"


class OutputSensitivity(StrEnum):
    """How a generated output must be handled.

    ``PUBLIC`` values may appear in ConfigMaps, generated docs, and dry-run output;
    ``SECRET_REFERENCE`` values are pointers (a provider secret name, a GitHub Actions
    secret name, an env var, or ``prompt``); ``SECRET_VALUE`` is the secret material
    itself and must stay in a secret store or Kubernetes Secret — never a ConfigMap,
    log, dry-run, or plan comment.
    """

    PUBLIC = "public"
    # These are classification labels for *how an output is handled*, not credentials —
    # silence the "hardcoded password" heuristics that fire on the SECRET_ prefix.
    SECRET_REFERENCE = "secret-reference"  # noqa: S105 # nosec B105
    SECRET_VALUE = "secret-value"  # noqa: S105 # nosec B105


class ProcessRole(StrEnum):
    """Which Shifter process a generated runtime output is for."""

    PORTAL = "portal"
    WORKER = "worker"
    PROVISIONER = "provisioner"
    RANGE_TASK = "range-task"


class BackendCapability(StrEnum):
    """A cloud-neutral capability protocol a backend can satisfy.

    These name the seams under ``shared.cloud`` and ``engine/provisioner/cloud`` that
    domain code already calls; a backend bundle *declares* which it provides, but it
    does not let domain code import provider packages directly.
    """

    STORAGE = "storage"
    QUEUE_CONSUMER = "queue-consumer"
    QUEUE_PUBLISHER = "queue-publisher"
    TASK_RUNNER = "task-runner"
    SECRETS = "secrets"
    CONFIG_STORE = "config-store"
    EVENT_BUS = "event-bus"
    DATABASE_AUTH = "database-auth"
    NETWORK_INVENTORY = "network-inventory"


class OutputKind(StrEnum):
    """The shape of a generated output."""

    RUNTIME_ENV = "runtime-env"
    TERRAFORM_VAR = "terraform-var"
    TERRAFORM_OUTPUT = "terraform-output"
    HELM_VALUE = "helm-value"
    K8S_ARTIFACT = "k8s-artifact"
    COMPAT_ALIAS = "compat-alias"


class OutputDestination(StrEnum):
    """Where a generated output is placed.

    Used together with :class:`OutputSensitivity` to keep secret *values* out of
    non-secret destinations: a ``SECRET_VALUE`` output may only land in a secret store.
    """

    RUNTIME_ENV = "runtime-env"  # process environment / Kubernetes ConfigMap / ECS task definition env
    # Placement labels — the SECRET_ prefix names *where* a value lands, not a credential.
    KUBERNETES_SECRET = "kubernetes-secret"  # noqa: S105 # nosec B105
    PROVIDER_SECRET_STORE = "provider-secret-store"  # noqa: S105 # nosec B105
    TERRAFORM_VARIABLES = "terraform-variables"
    HELM_VALUES = "helm-values"
    GENERATED_FILE = "generated-file"


#: Destinations a ``SECRET_VALUE`` output is allowed to be placed in.
_SECRET_VALUE_DESTINATIONS: frozenset[OutputDestination] = frozenset(
    {OutputDestination.KUBERNETES_SECRET, OutputDestination.PROVIDER_SECRET_STORE}
)
