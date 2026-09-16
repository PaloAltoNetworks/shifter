"""Ordered, safety-contracted AWS environment teardown for the destroy workflow.

Issue #1287. Encodes the validated manual sequence from
``docs/dev/aws-teardown-runbook.md`` as testable code that
``.github/workflows/aws-env-destroy.yml`` invokes, instead of a large
inline-bash workflow.

Reverse-dependency destroy order (verified against the repository — Portal reads
both Core and Range remote state and owns resources in the Range VPC, so it must
go before Range, not after):

    eks (only when its state is non-empty) -> portal -> range -> core
    -> global/github-runner -> global/iam

``global/iam`` is destroyed LAST because it owns the ``github-actions-shifter-<env>``
OIDC role this run authenticates as; the job runs on GitHub-hosted compute
outside the target account, so no post-destroy step depends on the runner fleet
(``global/github-runner``) surviving.

Pre-destroy handling (per the runbook):

- Lift deletion protection on the Portal RDS surfaces by writing a
  ``teardown-*.auto.tfvars`` override (protection off) that lexically overrides
  the rendered ``local.auto.tfvars``, then a targeted ``terraform apply`` on the
  protection-bearing resources before the Portal destroy. dev/proof already ship
  these ``false`` (secure default ``true`` is prod-only), so the lift is a
  no-op there but defends any env that enabled them.
- Empty S3 buckets the stack owns (discovered from its Terraform state, then
  ownership-verified against the live Project=shifter / Environment=<env> tags
  before any deletion) — current objects, all versions, delete markers, and
  incomplete multipart uploads. Runs before the Portal destroy and again before
  the Core destroy (log writers refill their buckets during teardown). The
  bootstrap ``{uuid}`` state bucket is excluded by name and is never emptied.
- Empty the Core-owned ECR repos (also derived from state, not synthesized
  names) only AFTER the Portal and Range destroys: the guacamole module resolves
  image digests through ``data "aws_ecr_image"`` sources evaluated during the
  Portal destroy plan, which fail on an empty repo. Deletes in <=100-id batches
  and fails closed on any list/delete error except a missing repository.
- KMS: AWS keys converge through scheduled deletion (unlike GCP key rings), so
  ``terraform destroy`` handles them and they do not normally block. A genuine
  KMS block is NOT auto-removed from state here (that could mask a still-enabled
  key behind a false success); it fails closed to the documented manual
  state-rm fallback in the runbook.

Post-destroy: reuse ``scripts/bootstrap/account_recovery.py``'s opt-in sweep for
the #1472 replaceable residue, then fail closed if any tagged env resource in
the issue's verify set still remains.

Scope boundary (#1287): this tears down Terraform layers + residue only. It does
NOT delete the bootstrap ``{uuid}`` state bucket, the GitHub Environment, or the
deploy secrets (runbook sections 5-7 stay out of scope).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess  # nosec B404 - imported only for the run_cmd return type; this module never executes subprocess.
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import terraform_backend as tb
from account_recovery import account_recovery
from bootstrap_core import error, info, run_cmd, subheader, success, warn

AWS_REGION = "us-east-2"

# `dev` and `proof` are the only teardown targets. `prod` is deliberately not a
# dispatch choice for this workflow; a production teardown is a separate,
# higher-ceremony decision (see the runbook).
ALLOWED_ENVS = ("dev", "proof")

_LOCK_TIMEOUT = "-lock-timeout=5m"
_NONINTERACTIVE = "-input=false"

# Attributes parsed from `terraform state show` output.
_BUCKET_ATTR_RE = re.compile(r'^\s*bucket\s*=\s*"([^"]+)"', re.MULTILINE)
_NAME_ATTR_RE = re.compile(r'^\s*name\s*=\s*"([^"]+)"', re.MULTILINE)
_ARN_ATTR_RE = re.compile(r'^\s*arn\s*=\s*"([^"]+)"', re.MULTILINE)

# ECR accepts at most 100 image ids per batch-delete-image call.
_ECR_BATCH_SIZE = 100

# Runner placement is resolved from positive evidence in the runner root's own
# state, never inferred from absence (ADR-004-R20, #1437). A state address under
# the managed module means create_runner_network=true was applied. The
# default-subnet discovery data source exists in state only when the
# allow_default_vpc opt-in was applied without an explicit subnet. With neither,
# an explicit vpc_id/subnet_id was applied, and the IDs are read back from the
# security group and instance attributes. That VPC is the default-VPC exception
# (applied with an explicit subnet_id) exactly when it appears in the default VPC
# IDs recorded by the unconditional data.aws_vpcs.default lookup, because the
# root's precondition admits the default VPC only under allow_default_vpc.
# Destroy must reproduce the applied topology so the runner root's config graph
# evaluates.
_RUNNER_NETWORK_MARKER = "module.runner_network"
_RUNNER_DEFAULT_SUBNETS_MARKER = "data.aws_subnets.default"
_RUNNER_DEFAULT_VPCS_ADDRESS = "data.aws_vpcs.default"
_RUNNER_SG_ADDRESS = "aws_security_group.runner"
_RUNNER_INSTANCE_ADDRESS = "aws_instance.runner"
_VPC_ID_ATTR_RE = re.compile(r'^\s*vpc_id\s*=\s*"(vpc-[0-9a-z]+)"', re.MULTILINE)
_SUBNET_ID_ATTR_RE = re.compile(r'^\s*subnet_id\s*=\s*"(subnet-[0-9a-z]+)"', re.MULTILINE)
_IDS_LIST_ATTR_RE = re.compile(r"^\s*ids\s*=\s*\[(.*?)\]", re.MULTILINE | re.DOTALL)
_QUOTED_VPC_ID_RE = re.compile(r'"(vpc-[0-9a-z]+)"')

# The teardown override sorts lexically AFTER `local.auto.tfvars`, so Terraform
# (which loads `*.auto.tfvars` in filename order and lets the last value win)
# overrides the rendered protection flags without a duplicate-key error. The
# name is gitignored so a runner-written override can never be committed.
_PROTECTION_OVERRIDE_FILE = "teardown-protection-override.auto.tfvars"

# Portal root deletion-protection inputs, all declared in
# environments/<env>/portal/variables.tf. ALB and Cognito protection are
# hardcoded false for dev/proof, so only the RDS surfaces are var-driven.
_PORTAL_PROTECTION_TFVARS = (
    "db_deletion_protection            = false",
    "db_skip_final_snapshot            = true",
    "guacamole_db_deletion_protection  = false",
    "guacamole_db_skip_final_snapshot  = true",
    "portal_inspection_delete_protection = false",
)

# Terraform resource-type prefixes whose live protection is lifted before the
# Portal destroy (targeted apply only these addresses; a no-op when off).
_PROTECTION_ADDRESS_MARKERS = (
    "aws_db_instance",
    "aws_networkfirewall_firewall",
)

# resourcegroupstaggingapi resource-type filters for the protection-bearing
# resources the Portal lift targets; used to confirm live ownership before
# disabling protection.
_PROTECTION_RESOURCE_TYPES = ("rds:db", "network-firewall:firewall")

# resourcegroupstaggingapi resource-type filters for the issue's post-destroy
# verify set. AMIs/snapshots and SSM `/shifter/ami/*` are deliberately excluded
# so preserved range base images are not flagged; KMS keys pending scheduled
# deletion are not a teardown failure.
_VERIFY_RESOURCE_TYPES = (
    "ec2:instance",
    "ec2:natgateway",
    "ec2:elastic-ip",
    "ec2:network-interface",
    "rds:db",
    "elasticloadbalancing:loadbalancer",
    "secretsmanager:secret",
    "logs:log-group",
    "s3",
)


def _address_has_type(addr: str, types: tuple[str, ...]) -> bool:
    """True when a Terraform address names one of ``types``.

    Addresses are module-qualified (``module.rds.aws_db_instance.portal``) or
    top-level (``aws_kms_key.ecr``), so the resource type appears either as a
    ``.<type>.`` segment or as the address prefix ``<type>.``.
    """
    return any(f".{t}." in addr or addr.startswith(f"{t}.") for t in types)


class TeardownError(RuntimeError):
    """A teardown step failed in a way that must fail the run closed."""


@dataclass(frozen=True)
class Layer:
    """One Terraform stack in the ordered teardown."""

    name: str
    # Path under platform/terraform, with an `{env}` placeholder for env stacks.
    stack_template: str
    lift_portal: bool = False  # lift Portal deletion protection before destroy
    empty_s3: bool = False  # empty state-owned S3 buckets before this destroy
    empty_ecr: bool = False  # empty state-owned ECR repos before this destroy
    topology_from_state: bool = False  # resolve runner network vars from state
    # `terraform destroy` -var flags this stack requires beyond its tfvars.
    var_flags: tuple[str, ...] = ()

    def stack_dir(self, env: str) -> str:
        """Return the stack path for a concrete environment."""
        return self.stack_template.format(env=env)


def _layers(env: str, state_bucket: str) -> tuple[Layer, ...]:
    """Return the ordered teardown layers for one environment."""
    return (
        # EKS is parked (#1324); like every layer it is skipped when its state is
        # empty (the universal already-destroyed check in destroy_layer).
        Layer("eks", "environments/{env}/eks"),
        Layer(
            "portal",
            "environments/{env}/portal",
            lift_portal=True,
            empty_s3=True,
            var_flags=(f"-var=terraform_state_bucket={state_bucket}",),
        ),
        Layer("range", "environments/{env}/range"),
        Layer("core", "environments/{env}", empty_s3=True, empty_ecr=True),
        # The runner root's network vars are resolved from its own state at
        # destroy time (managed, default opt-in, or explicit external), so
        # destroy reproduces the applied topology rather than a fixed guess.
        Layer("github-runner", "global/github-runner", topology_from_state=True),
        Layer("iam", "global/iam", var_flags=(f"-var=environment={env}",)),
    )


@dataclass(frozen=True)
class TeardownContext:
    """Immutable inputs for one teardown run."""

    env: str
    region: str
    repo_root: Path
    backend_dir: Path
    state_bucket: str
    # AWS CLI profile for the account_recovery sweep. In CI this names a
    # `credential_source = Environment` profile so the sweep uses the assumed
    # OIDC role; empty falls back to the default credential chain.
    profile: str = ""
    dry_run: bool = False


# --------------------------------------------------------------------------- #
# Terraform primitives
# --------------------------------------------------------------------------- #


def _platform_terraform_dir(repo_root: Path) -> Path:
    """Return the platform/terraform root under the checkout."""
    return repo_root / "platform" / "terraform"


def _tf_dir(ctx: TeardownContext, stack_dir: str) -> Path:
    """Return the absolute directory of a Terraform stack."""
    return _platform_terraform_dir(ctx.repo_root) / stack_dir


def _backend_config(ctx: TeardownContext, stack_dir: str) -> Path:
    """Return the rendered per-instance backend config path for a stack."""
    return tb.backend_config_for_stack(ctx.backend_dir, stack_dir, ctx.env)


def _terraform(
    ctx: TeardownContext,
    stack_dir: str,
    *args: str,
    check: bool = True,
    capture: bool = False,
) -> subprocess.CompletedProcess | None:
    """Run a `terraform -chdir=<stack>` command via run_cmd (None in dry-run)."""
    cmd = ["terraform", f"-chdir={_tf_dir(ctx, stack_dir)}", *args]
    return run_cmd(cmd, dry_run=ctx.dry_run, check=check, capture=capture)


def terraform_init(ctx: TeardownContext, stack_dir: str) -> None:
    """Initialize a stack against its rendered per-instance backend config."""
    _terraform(
        ctx,
        stack_dir,
        "init",
        _NONINTERACTIVE,
        "-reconfigure",
        f"-backend-config={_backend_config(ctx, stack_dir)}",
        f"-backend-config=bucket={ctx.state_bucket}",
    )


def state_addresses(ctx: TeardownContext, stack_dir: str) -> list[str]:
    """Return the Terraform state resource addresses for a stack.

    Fails closed: a missing/non-zero result (backend, auth, or transient error)
    raises rather than reading as an empty state, so an unknown state can never
    be mistaken for "nothing to destroy" or a clean post-destroy check. Only a
    successful command with empty stdout is an empty state. In dry-run, run_cmd
    returns None by design, so an empty list is returned.
    """
    result = _terraform(ctx, stack_dir, "state", "list", check=False, capture=True)
    if result is None:
        return []  # dry-run no-op
    if result.returncode != 0:
        raise TeardownError(f"`terraform state list` failed for {stack_dir} (exit {result.returncode})")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


# --------------------------------------------------------------------------- #
# Pre-destroy handling
# --------------------------------------------------------------------------- #


def lift_portal_protection(ctx: TeardownContext, stack_dir: str, var_flags: tuple[str, ...] = ()) -> None:
    """Drop live deletion protection on the Portal RDS/NFW surfaces before destroy.

    State is discovery only: a target is included in the lift apply only when its
    live resource ARN is independently confirmed env-owned (tagged Project=shifter
    + Environment=<env>). A poisoned state entry pointing at another environment's
    protected resource is skipped, so the deploy role never disables protection on
    a resource this teardown does not own.
    """
    override = _tf_dir(ctx, stack_dir) / _PROTECTION_OVERRIDE_FILE
    body = "# Auto-generated by aws_env_destroy.py; do not commit.\n" + "\n".join(_PORTAL_PROTECTION_TFVARS) + "\n"
    if ctx.dry_run:
        info(f"[DRY-RUN] Would write {override} and targeted-apply protection lift")
        return
    override.parent.mkdir(parents=True, exist_ok=True)
    override.write_text(body)
    owned_arns = set(env_tagged_arns(ctx, _PROTECTION_RESOURCE_TYPES))
    targets: list[str] = []
    for addr in state_addresses(ctx, stack_dir):
        if not _address_has_type(addr, _PROTECTION_ADDRESS_MARKERS):
            continue
        arn = _state_show_arn(ctx, stack_dir, addr)
        if arn and arn in owned_arns:
            targets.append(f"-target={addr}")
        else:
            warn(f"Protection target {addr} not ownership-verified (live Project/Environment tags); not lifting.")
    if not targets:
        info("No ownership-verified protection-bearing Portal resources in state; skipping lift apply.")
        return
    info(f"Lifting deletion protection on {len(targets)} Portal resource(s) before destroy.")
    # Carry the layer's -var flags (e.g. terraform_state_bucket, a required root
    # input) so the apply evaluates the full config non-interactively; without
    # them Terraform would prompt or fail before protection is lifted.
    _terraform(ctx, stack_dir, "apply", "-auto-approve", _NONINTERACTIVE, _LOCK_TIMEOUT, *var_flags, *targets)


def _state_show_arn(ctx: TeardownContext, stack_dir: str, addr: str) -> str:
    """Return the ``arn`` attribute of a state resource, or "" if unavailable."""
    shown = _terraform(ctx, stack_dir, "state", "show", "-no-color", addr, check=False, capture=True)
    if shown is None or shown.returncode != 0:
        return ""
    match = _ARN_ATTR_RE.search(shown.stdout)
    return match.group(1) if match else ""


def _s3(
    ctx: TeardownContext, *args: str, check: bool = True, capture: bool = False
) -> subprocess.CompletedProcess | None:
    """Run an `aws --region <region> ...` command via run_cmd (None in dry-run)."""
    cmd = ["aws", "--region", ctx.region, *args]
    return run_cmd(cmd, dry_run=ctx.dry_run, check=check, capture=capture, profile=ctx.profile or None)


def _aws_json(ctx: TeardownContext, *args: str) -> dict | list:
    """Run a read-only ``aws ... --output json`` query; raise on failure."""
    cmd = ["aws", "--region", ctx.region, *args, "--output", "json"]
    result = run_cmd(cmd, capture=True, check=False, profile=ctx.profile or None)
    if result is None or result.returncode != 0:
        rc = getattr(result, "returncode", "n/a")
        raise TeardownError(f"`aws {' '.join(args)}` failed (exit {rc})")
    if not result.stdout.strip():
        raise TeardownError(f"`aws {' '.join(args)}` returned no output")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise TeardownError(f"`aws {' '.join(args)}` returned unparseable JSON") from exc


def env_tagged_arns(ctx: TeardownContext, resource_types: tuple[str, ...]) -> list[str]:
    """Return ARNs tagged Project=shifter + Environment=<env> for the given types."""
    # `--resource-type-filters` is a single list option: emit it once with every
    # value. Repeating the option would leave only the last value effective,
    # silently narrowing the verify set to one resource type.
    args = [
        "resourcegroupstaggingapi",
        "get-resources",
        "--tag-filters",
        "Key=Project,Values=shifter",
        f"Key=Environment,Values={ctx.env}",
        "--resource-type-filters",
        *resource_types,
    ]
    data = _aws_json(ctx, *args)
    if not isinstance(data, dict):
        raise TeardownError("resourcegroupstaggingapi returned an unexpected shape")
    return [m["ResourceARN"] for m in data.get("ResourceTagMappingList", []) if m.get("ResourceARN")]


def _bucket_name_from_arn(arn: str) -> str:
    """Return the bucket name from an S3 ARN (``arn:aws:s3:::bucket-name``)."""
    return arn.rsplit(":", 1)[-1]


def _bucket_names_from_state(ctx: TeardownContext, stack_dir: str) -> list[str]:
    """Resolve aws_s3_bucket names owned by a stack from its Terraform state.

    State is authoritative (the runbook): the portal/range providers set no
    ``default_tags``, so a tag query is not a reliable bucket inventory. Each
    ``aws_s3_bucket`` address' ``bucket`` attribute is the real bucket name.
    """
    names: list[str] = []
    for addr in state_addresses(ctx, stack_dir):
        if not _address_has_type(addr, ("aws_s3_bucket",)):
            continue
        shown = _terraform(ctx, stack_dir, "state", "show", "-no-color", addr, check=False, capture=True)
        if shown is None or shown.returncode != 0:
            continue
        match = _BUCKET_ATTR_RE.search(shown.stdout)
        if match:
            names.append(match.group(1))
    return names


def _bucket_is_owned(ctx: TeardownContext, bucket: str) -> bool:
    """True only when the live bucket carries this env's ownership tags.

    State membership is discovery, not deletion authority (a poisoned/stale/
    cross-account state entry could name a foreign bucket). Before irreversibly
    emptying, confirm the live bucket in this account is tagged
    Project=shifter + Environment=<env>. get-bucket-tagging fails for a bucket
    not in the active account, so this also pins the live account identity.
    Fail closed: any error or tag mismatch means "not proven owned".
    """
    result = _s3(ctx, "s3api", "get-bucket-tagging", "--bucket", bucket, check=False, capture=True)
    if result is None or result.returncode != 0 or not result.stdout.strip():
        return False
    try:
        tags = {t["Key"]: t.get("Value", "") for t in json.loads(result.stdout).get("TagSet", [])}
    except (json.JSONDecodeError, TypeError):
        return False
    return tags.get("Project") == "shifter" and tags.get("Environment") == ctx.env


def empty_stack_s3_buckets(ctx: TeardownContext, stack_dir: str) -> None:
    """Empty each state-owned, ownership-verified S3 bucket (never the state bucket)."""
    for bucket in _bucket_names_from_state(ctx, stack_dir):
        if bucket == ctx.state_bucket:
            continue
        if ctx.dry_run:
            _empty_bucket(ctx, bucket)  # dry-run: log intent, mutate nothing
            continue
        if not _bucket_is_owned(ctx, bucket):
            warn(f"S3 bucket {bucket} is in state but not ownership-verified (Project/Environment tags); not emptying.")
            continue
        _empty_bucket(ctx, bucket)


def _empty_bucket(ctx: TeardownContext, bucket: str) -> None:
    """Delete all objects, versions, delete markers, and multipart uploads."""
    info(f"Emptying S3 bucket {bucket}")
    if ctx.dry_run:
        info(f"[DRY-RUN] Would empty s3://{bucket}")
        return
    versions = _aws_json(ctx, "s3api", "list-object-versions", "--bucket", bucket)
    objects = []
    if isinstance(versions, dict):
        for entry in versions.get("Versions", []) + versions.get("DeleteMarkers", []):
            objects.append({"Key": entry["Key"], "VersionId": entry["VersionId"]})
    for batch in _chunked(objects, 1000):
        payload = json.dumps({"Objects": batch, "Quiet": True})
        _s3(ctx, "s3api", "delete-objects", "--bucket", bucket, "--delete", payload)
    uploads = _aws_json(ctx, "s3api", "list-multipart-uploads", "--bucket", bucket)
    if isinstance(uploads, dict):
        for up in uploads.get("Uploads", []):
            _s3(
                ctx,
                "s3api",
                "abort-multipart-upload",
                "--bucket",
                bucket,
                "--key",
                up["Key"],
                "--upload-id",
                up["UploadId"],
            )


def _chunked(items: list[dict[str, str]], size: int) -> Iterator[list[dict[str, str]]]:
    """Yield successive ``size``-length slices of ``items``."""
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _ecr_repo_names_from_state(ctx: TeardownContext, stack_dir: str) -> list[str]:
    """Resolve aws_ecr_repository names owned by a stack from its state.

    Derived from state (not synthesized `shifter-<env>-*` names) so teardown
    cannot become a destructive deputy for a name-colliding, non-state-managed
    repository in the account.
    """
    names: list[str] = []
    for addr in state_addresses(ctx, stack_dir):
        if not _address_has_type(addr, ("aws_ecr_repository",)):
            continue
        shown = _terraform(ctx, stack_dir, "state", "show", "-no-color", addr, check=False, capture=True)
        if shown is None or shown.returncode != 0:
            continue
        match = _NAME_ATTR_RE.search(shown.stdout)
        if match:
            names.append(match.group(1))
    return names


def empty_stack_ecr_repos(ctx: TeardownContext, stack_dir: str) -> None:
    """Empty each state-owned, ownership-verified ECR repo before its destroy."""
    for repo in _ecr_repo_names_from_state(ctx, stack_dir):
        _empty_ecr_repo(ctx, repo)


def _ecr_repo_is_owned(ctx: TeardownContext, repo: str) -> bool:
    """True only when the live ECR repo carries this env's ownership tags.

    State names the repo (discovery); this confirms the live repo in the active
    account is tagged Project=shifter + Environment=<env> before any image
    deletion. Fail closed: absent repo, query error, or tag mismatch => not owned.
    """
    desc = _s3(
        ctx,
        "ecr",
        "describe-repositories",
        "--repository-names",
        repo,
        "--query",
        "repositories[0].repositoryArn",
        "--output",
        "text",
        check=False,
        capture=True,
    )
    if desc is None or desc.returncode != 0 or not desc.stdout.strip():
        return False
    arn = desc.stdout.strip()
    tagged = _s3(
        ctx, "ecr", "list-tags-for-resource", "--resource-arn", arn, "--output", "json", check=False, capture=True
    )
    if tagged is None or tagged.returncode != 0 or not tagged.stdout.strip():
        return False
    try:
        tags = {t["Key"]: t.get("Value", "") for t in json.loads(tagged.stdout).get("tags", [])}
    except (json.JSONDecodeError, TypeError):
        return False
    return tags.get("Project") == "shifter" and tags.get("Environment") == ctx.env


def _ecr_image_ids(ctx: TeardownContext, repo: str) -> list[dict[str, str]]:
    """Return the image ids in an ECR repo; [] if absent, raise on other error."""
    listed = _s3(
        ctx,
        "ecr",
        "list-images",
        "--repository-name",
        repo,
        "--query",
        "imageIds[*]",
        "--output",
        "json",
        check=False,
        capture=True,
    )
    if listed is None:
        return []
    if listed.returncode != 0:
        if "RepositoryNotFoundException" in (getattr(listed, "stderr", "") or ""):
            info(f"ECR repo {repo} absent; skipping.")
            return []
        raise TeardownError(f"`aws ecr list-images` failed for {repo} (exit {listed.returncode})")
    return json.loads(listed.stdout) if listed.stdout.strip() else []


def _empty_ecr_repo(ctx: TeardownContext, repo: str) -> None:
    """Delete every image in an ECR repo in bounded batches; fail closed."""
    if ctx.dry_run:
        info(f"[DRY-RUN] Would empty ECR repo {repo}")
        return
    if not _ecr_repo_is_owned(ctx, repo):
        warn(f"ECR repo {repo} absent or not ownership-verified (live Project/Environment tags); not emptying.")
        return
    for batch in _chunked(_ecr_image_ids(ctx, repo), _ECR_BATCH_SIZE):
        result = _s3(
            ctx,
            "ecr",
            "batch-delete-image",
            "--repository-name",
            repo,
            "--image-ids",
            json.dumps(batch),
            check=False,
            capture=True,
        )
        if result is not None and result.returncode != 0:
            raise TeardownError(f"`aws ecr batch-delete-image` failed for {repo} (exit {result.returncode})")


# --------------------------------------------------------------------------- #
# Destroy
# --------------------------------------------------------------------------- #


def _runner_var_flags(ctx: TeardownContext, stack_dir: str) -> tuple[str, ...]:
    """Resolve the runner root's network vars from its applied state.

    Each applied topology is resolved from positive state evidence (see
    _RUNNER_NETWORK_MARKER): managed network, default-VPC opt-in with discovery,
    or an explicit vpc_id/subnet_id read back from state, which retains the
    default-VPC opt-in when that VPC is the recorded default VPC. Reproducing the
    applied topology keeps the runner destroy graph evaluable; an explicit network
    that cannot be resolved unambiguously fails closed.
    """
    if ctx.dry_run:
        info("github-runner: network vars are resolved from applied state at execution time.")
        flags: list[str] = []
    else:
        flags = _applied_runner_network_flags(ctx, stack_dir, state_addresses(ctx, stack_dir))
    return tuple(flags)


def _applied_runner_network_flags(ctx: TeardownContext, stack_dir: str, addresses: list[str]) -> list[str]:
    """Return the destroy -var flags reproducing the runner network in ``addresses``."""
    if any(addr.startswith(_RUNNER_NETWORK_MARKER) for addr in addresses):
        return ["-var=create_runner_network=true"]
    if any(addr.startswith(_RUNNER_DEFAULT_SUBNETS_MARKER) for addr in addresses):
        return ["-var=allow_default_vpc=true"]
    vpc_id = _single_state_attr(ctx, stack_dir, addresses, _RUNNER_SG_ADDRESS, _VPC_ID_ATTR_RE, "vpc_id")
    subnet_id = _single_state_attr(ctx, stack_dir, addresses, _RUNNER_INSTANCE_ADDRESS, _SUBNET_ID_ATTR_RE, "subnet_id")
    flags = [f"-var=vpc_id={vpc_id}", f"-var=subnet_id={subnet_id}"]
    if vpc_id in _state_default_vpc_ids(ctx, stack_dir, addresses):
        flags.insert(0, "-var=allow_default_vpc=true")
    return flags


def _state_default_vpc_ids(ctx: TeardownContext, stack_dir: str, addresses: list[str]) -> set[str]:
    """Return the account default VPC IDs recorded by the runner root at apply.

    Fails closed when the lookup is absent or unreadable: without it, default-VPC
    placement with an explicit subnet cannot be distinguished from an external
    network.
    """
    shown = None
    if _RUNNER_DEFAULT_VPCS_ADDRESS in addresses:
        shown = _terraform(
            ctx, stack_dir, "state", "show", "-no-color", _RUNNER_DEFAULT_VPCS_ADDRESS, check=False, capture=True
        )
    match = _IDS_LIST_ATTR_RE.search(shown.stdout) if shown is not None and shown.returncode == 0 else None
    if match is None:
        raise TeardownError(
            f"github-runner: cannot read the recorded default VPC IDs from {_RUNNER_DEFAULT_VPCS_ADDRESS} in state, "
            "so default VPC placement cannot be ruled out; destroy the runner root manually with the applied "
            "-var=vpc_id=... -var=subnet_id=... (and -var=allow_default_vpc=true if it is the default VPC)"
        )
    return set(_QUOTED_VPC_ID_RE.findall(match.group(1)))


def _single_state_attr(
    ctx: TeardownContext,
    stack_dir: str,
    addresses: list[str],
    resource: str,
    pattern: re.Pattern[str],
    attr: str,
) -> str:
    """Return the one value of ``attr`` across every state instance of ``resource``.

    Fails closed when no instance is in state, any instance lacks the attribute,
    or instances disagree: an external runner network is never guessed.
    """
    instances = [a for a in addresses if a == resource or a.startswith(f"{resource}[")]
    values: set[str] = set()
    for addr in instances:
        shown = _terraform(ctx, stack_dir, "state", "show", "-no-color", addr, check=False, capture=True)
        found = pattern.findall(shown.stdout) if shown is not None and shown.returncode == 0 else []
        if not found:
            values.clear()
            break
        values.update(found)
    if len(values) != 1:
        raise TeardownError(
            f"github-runner: cannot resolve the applied external network {attr} from {resource} in state "
            "(missing, unreadable, or ambiguous); destroy the runner root manually with explicit "
            "-var=vpc_id=... -var=subnet_id=..."
        )
    return values.pop()


def _run_pre_destroy(ctx: TeardownContext, layer: Layer, stack_dir: str, var_flags: tuple[str, ...]) -> None:
    """Run a layer's configured pre-destroy handling (protection lift, S3/ECR empty)."""
    if layer.lift_portal:
        lift_portal_protection(ctx, stack_dir, var_flags)
    if layer.empty_s3:
        empty_stack_s3_buckets(ctx, stack_dir)
    if layer.empty_ecr:
        empty_stack_ecr_repos(ctx, stack_dir)


def destroy_layer(ctx: TeardownContext, layer: Layer) -> str:
    """Destroy one layer with pre-destroy handling; return an outcome string."""
    stack_dir = layer.stack_dir(ctx.env)
    subheader(f"Layer: {layer.name} ({stack_dir})")
    terraform_init(ctx, stack_dir)

    # Every layer is skipped when its state is empty (never applied, or already
    # destroyed by an earlier attempt). This makes a re-dispatch after a partial
    # run idempotent: a cleared Portal/Range/Core is not re-entered, so Portal's
    # remote-state references to a destroyed Range/Core cannot fail on retry.
    if not ctx.dry_run and not state_addresses(ctx, stack_dir):
        info(f"{layer.name}: state is empty; already destroyed, skipping.")
        return "skipped"

    var_flags = _runner_var_flags(ctx, stack_dir) if layer.topology_from_state else layer.var_flags
    _run_pre_destroy(ctx, layer, stack_dir, var_flags)

    destroy_args = ["destroy", "-auto-approve", _LOCK_TIMEOUT, *var_flags]
    result = _terraform(ctx, stack_dir, *destroy_args, check=False)
    if ctx.dry_run:
        return "dry-run"

    if result is None or result.returncode != 0:
        _remediate_and_retry(ctx, layer, stack_dir, destroy_args)

    remaining = state_addresses(ctx, stack_dir)
    if remaining:
        raise TeardownError(f"{layer.name}: state still has {len(remaining)} resource(s) after destroy")
    success(f"{layer.name}: destroyed.")
    return "destroyed"


def _remediate_and_retry(ctx: TeardownContext, layer: Layer, stack_dir: str, destroy_args: list[str]) -> None:
    """Apply bounded, safe remediation for a failed destroy and retry once.

    The only automatic remediation is re-emptying the stack's S3 buckets: log
    writers refill them during teardown, so a `BucketNotEmpty` failure clears on
    a re-empty + retry. AWS KMS keys converge through scheduled deletion, so they
    do not normally block destroy; a genuine KMS block is NOT auto-`state rm`'d
    here (that could hide a still-enabled key/alias behind a false success and is
    excluded from the tag verify). It fails closed to the documented manual KMS
    state-rm fallback in docs/dev/aws-teardown-runbook.md.
    """
    warn(f"{layer.name}: destroy failed; re-emptying S3 and retrying once.")
    if layer.empty_s3:
        empty_stack_s3_buckets(ctx, stack_dir)
    retry = _terraform(ctx, stack_dir, *destroy_args, check=False)
    if retry is None or retry.returncode != 0:
        raise TeardownError(f"{layer.name}: destroy failed after remediation and retry")


# --------------------------------------------------------------------------- #
# Post-destroy verify + sweep
# --------------------------------------------------------------------------- #


def run_account_recovery_sweep(ctx: TeardownContext) -> None:
    """Sweep the #1472 replaceable residue via the safety-contracted tool."""
    subheader("Post-destroy leftover sweep (account_recovery)")
    if ctx.dry_run:
        info("[DRY-RUN] Would run account_recovery sweep.")
        return
    report = account_recovery(ctx.env, ctx.profile, sweep=True, dry_run=False)
    info(report.render())
    if report.failures:
        raise TeardownError(f"account_recovery reported {len(report.failures)} failed check(s)")


def verify_env_empty(ctx: TeardownContext) -> None:
    """Fail closed if any tagged env resource in the verify set still remains."""
    subheader("Post-destroy verification")
    if ctx.dry_run:
        info("[DRY-RUN] Would verify the environment is empty.")
        return
    arns = [
        arn for arn in env_tagged_arns(ctx, _VERIFY_RESOURCE_TYPES) if _bucket_name_from_arn(arn) != ctx.state_bucket
    ]
    if arns:
        for arn in arns:
            error(f"::error::residual resource remains: {arn}")
        raise TeardownError(f"{len(arns)} tagged {ctx.env} resource(s) remain after teardown")
    success(f"Environment {ctx.env} is empty (verify set clean).")


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #


# Phases split the run at a credential-lifetime boundary (#1287): the `stacks`
# phase runs the long env-stack destroys; the caller re-authenticates a fresh STS
# session; the `finalize` phase then destroys the runner, runs the fallible sweep
# + verify, and destroys global/iam LAST. So no single STS session must span the
# whole multi-hour run, and — because IAM (which owns this run's deploy role) is
# the terminal operation — a failed sweep or verify leaves the role intact for a
# resumable re-dispatch; only the never-failing-after IAM delete removes it.
_STACKS_LAYERS = ("eks", "portal", "range", "core")


def _destroy_named(ctx: TeardownContext, name: str) -> None:
    """Destroy the single layer with the given name."""
    for layer in _layers(ctx.env, ctx.state_bucket):
        if layer.name == name:
            destroy_layer(ctx, layer)
            return


def teardown(ctx: TeardownContext, phase: str = "all") -> None:
    """Destroy layers for the requested phase; sweep and verify in finalize/all."""
    subheader(f"AWS teardown: env={ctx.env} phase={phase} region={ctx.region} bucket={ctx.state_bucket}")
    if phase in ("stacks", "all"):
        for name in _STACKS_LAYERS:
            _destroy_named(ctx, name)
    if phase in ("finalize", "all"):
        _destroy_named(ctx, "github-runner")
        # Fallible cleanup + evidence run while the deploy role still exists, so a
        # failure here is recoverable by re-dispatch.
        run_account_recovery_sweep(ctx)
        verify_env_empty(ctx)
        # Terminal: destroying global/iam removes this run's own deploy role, so
        # nothing fallible may follow it.
        _destroy_named(ctx, "iam")
        success(f"Teardown complete for {ctx.env}.")


def _validate_env(env: str) -> str:
    """Return the env if it is a permitted teardown target, else exit."""
    if env not in ALLOWED_ENVS:
        raise SystemExit(f"::error::unsupported teardown environment {env!r}; allowed: {', '.join(ALLOWED_ENVS)}")
    return env


def _backend_dir_from_args(args: argparse.Namespace, env: str, bucket: str) -> Path:
    """Resolve the rendered backend-config directory from CLI args."""
    if args.backend_dir:
        return Path(args.backend_dir)
    instance_dir = Path(args.instance_dir) if args.instance_dir else None
    return tb.resolve_instance_backend_dir(env=env, bucket=bucket, instance_dir=instance_dir)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: parse args, build the context, and run the teardown."""
    parser = argparse.ArgumentParser(description="Tear down an AWS Shifter environment (issue #1287).")
    parser.add_argument("--env", required=True, help="Target environment (dev or proof)")
    parser.add_argument("--state-bucket", required=True, help="Pinned Terraform state bucket for the environment")
    parser.add_argument("--region", default=AWS_REGION, help="AWS region (default us-east-2)")
    parser.add_argument("--repo-root", default="", help="Repository root (defaults to this checkout)")
    parser.add_argument("--backend-dir", default="", help="Rendered per-instance backend-config directory")
    parser.add_argument("--instance-dir", default="", help="Instance dir used to derive the backend dir when unset")
    parser.add_argument("--profile", default="", help="AWS CLI profile for the sweep (empty = default chain)")
    parser.add_argument(
        "--phase",
        choices=("stacks", "finalize", "all"),
        default="all",
        help="stacks: env-stack destroys; finalize: runner+iam+sweep+verify (re-auth between); all: both",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print actions without mutating anything")
    args = parser.parse_args(argv)

    env = _validate_env(args.env.strip())
    bucket = args.state_bucket.strip()
    if not bucket:
        raise SystemExit("::error::--state-bucket is required")
    repo_root = Path(args.repo_root) if args.repo_root else Path(__file__).resolve().parents[2]
    ctx = TeardownContext(
        env=env,
        region=args.region.strip() or AWS_REGION,
        repo_root=repo_root,
        backend_dir=_backend_dir_from_args(args, env, bucket),
        state_bucket=bucket,
        profile=args.profile.strip(),
        dry_run=args.dry_run,
    )
    try:
        teardown(ctx, phase=args.phase)
    except TeardownError as exc:
        error(f"::error::{exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
