"""External inventory commands on the existing bootstrap CLI."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from installation.deployment_inventory import MAX_RECORD_BYTES, parse_record, validate_ownership
from installation.deployment_inventory_types import DeploymentRecord
from installation.errors import InstallationConfigError

from bootstrap_core import get_repo_root
from inventory_bootstrap import authorize_record, invalid, plan_identity, private_command, write_private
from inventory_cloud import bootstrap_lock, ensure_services, ensure_state_buckets, operator_environment, verify_projects
from inventory_github import publish_execution_bindings, reconcile_environments, reconcile_subject, verify_github_actor


def _safe_output_path(raw: Path, option: str) -> Path:
    """Resolve a CLI output path, confined to the current working directory.

    The value is an untrusted CLI argument (SonarCloud S8707: path traversal via
    agent-supplied CLI arguments). Resolving and confining it to the working tree
    stops ``--plan-output ../../etc`` (or an absolute path outside it) from
    creating files beyond the directory the bootstrap is run from.
    """
    base = Path.cwd().resolve()
    candidate = (base / raw).resolve()
    if candidate != base and base not in candidate.parents:
        raise invalid(f"{option} must stay within {base}")
    return candidate


def add_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register inventory validation, planning and bootstrap commands."""
    parser = subparsers.add_parser(
        "inventory", help="Validate or bootstrap a deployment from private external inventory"
    )
    parser.add_argument("action", choices=["validate", "scaffold", "plan", "bootstrap", "resolve-secret"])
    parser.add_argument("--inventory-root", type=Path, required=True)
    parser.add_argument("--record", required=True, help="Relative deployment record under deployments/")
    parser.add_argument("--inventory-repository", required=True)
    parser.add_argument("--inventory-revision", required=True, help="Exact reviewed inventory commit SHA")
    parser.add_argument("--execution-repository")
    parser.add_argument("--project")
    parser.add_argument("--plan-output", type=Path, help="New private directory for identity and runner plan evidence")
    parser.add_argument("--operator", help="Expected active gcloud account")
    parser.add_argument("--github-actor", help="Expected GitHub bootstrap administrator")
    parser.add_argument("--apply", action="store_true", help="Activate the reviewed bootstrap changes")
    parser.add_argument("--output", type=Path, help="New directory for private execution checks")
    parser.add_argument("--secret-name", help="Logical common secret binding to resolve")
    parser.add_argument("--secret-output", type=Path, help="New private output file for the consumer")
    parser.add_argument("--execution-environment", help="Exact consumer execution Environment")


def verified_inventory(args: argparse.Namespace) -> DeploymentRecord:
    """Load reviewed regular Git blobs and validate ownership across the inventory."""
    root = args.inventory_root.resolve()
    revision = args.inventory_revision
    if len(revision) != 40 or any(character not in "0123456789abcdef" for character in revision):
        raise invalid("inventory revision must be an immutable commit SHA")
    actual = private_command(["git", "rev-parse", "HEAD"], cwd=root).strip()
    origin = private_command(["git", "config", "--get", "remote.origin.url"], cwd=root).strip()
    expected = {
        f"https://github.com/{args.inventory_repository}.git",
        f"https://github.com/{args.inventory_repository}",
        f"git@github.com:{args.inventory_repository}.git",
    }
    if actual != revision or origin not in expected:
        raise invalid("inventory checkout does not match the explicit repository and revision")
    private_command(["git", "diff", "--exit-code", "HEAD", "--", "deployments"], cwd=root)
    paths = private_command(["git", "ls-files", "--", "deployments"], cwd=root).splitlines()
    paths = [path for path in paths if Path(path).suffix in {".json", ".yaml", ".yml"}]
    if args.record not in paths or len(paths) > 1000:
        raise invalid("record must belong to the bounded, committed deployment inventory")
    records = {}
    for path in paths:
        records[path] = _read_record(root, revision, path)
    validate_ownership(list(records.values()))
    return records[args.record]


def _read_record(root: Path, revision: str, path: str) -> DeploymentRecord:
    """Bound and parse one regular file from the immutable inventory commit."""
    entry = private_command(["git", "ls-tree", revision, "--", path], cwd=root).split()
    if len(entry) < 3 or entry[0] not in {"100644", "100755"} or entry[1] != "blob":
        raise invalid("inventory records must be committed regular files")
    size = private_command(["git", "cat-file", "-s", entry[2]], cwd=root).strip()
    if not size.isdecimal() or int(size) > MAX_RECORD_BYTES:
        raise invalid("inventory record exceeds the input bound")
    payload = private_command(["git", "cat-file", "blob", entry[2]], cwd=root)
    return parse_record(payload.encode("utf-8"))


def stage_product(product_root: Path, revision: str, destination: Path) -> Path:
    """Stage only tracked reusable Terraform from a pinned product revision.

    Local overrides, state, caches, credentials and tenant tfvars are never
    copied. Relative module paths stay intact in this temporary execution tree.
    """
    if private_command(["git", "rev-parse", "HEAD"], cwd=product_root).strip() != revision:
        raise invalid("bootstrap tooling must execute from the selected immutable product revision")
    private_command(["git", "diff", "--exit-code", "HEAD"], cwd=product_root)
    roots = [
        "platform/terraform/gcp/global/cicd-oidc",
        "platform/terraform/gcp/modules/cicd-oidc-identity",
        "platform/terraform/gcp/global/github-runner",
        "platform/terraform/gcp/modules/github-runner-network",
    ]
    paths = private_command(
        ["git", "ls-tree", "-r", "--name-only", revision, "--", *roots], cwd=product_root
    ).splitlines()
    for relative in paths:
        path = Path(relative)
        if path.suffix not in {".tf", ".tftpl"} and path.name not in {
            ".terraform.lock.hcl",
            "runner-release.auto.tfvars.json",
        }:
            continue
        target = destination / path
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        write_private(target, private_command(["git", "show", f"{revision}:{relative}"], cwd=product_root))
    return destination / roots[0]


def _resolve_secret(record: DeploymentRecord, args: argparse.Namespace) -> None:
    """Resolve one explicitly scoped binding into a new private output file."""
    from inventory_secrets import resolve_secret

    if (
        args.secret_name not in record.secrets
        or not args.secret_output
        or args.execution_repository != record.execution.repository
        or not args.execution_environment
    ):
        raise invalid("secret resolution requires a binding, output file and exact execution scope")
    output = _safe_output_path(args.secret_output, "--secret-output")
    value = resolve_secret(
        record.secrets[args.secret_name],
        repository=args.execution_repository,
        environment=args.execution_environment,
    )
    write_private(output, value)


def _authorize_bootstrap(record: DeploymentRecord, args: argparse.Namespace) -> None:
    """Require explicit matching targets, activation intent and installed tools."""
    if not all((args.operator, args.github_actor, args.execution_repository, args.project, args.plan_output)):
        raise invalid(
            "plan/bootstrap require operator, GitHub actor, repository, project and a new --plan-output directory"
        )
    if args.action == "bootstrap" and not args.apply:
        raise invalid("bootstrap activation requires the explicit --apply flag")
    if args.action == "plan" and args.apply:
        raise invalid("plan cannot activate bootstrap changes")
    authorize_record(record, execution_repository=args.execution_repository, project_id=args.project)
    import shutil

    from preflight import CheckResult, PreflightReport, Status

    checks = []
    for tool in ("git", "gh", "gcloud", "terraform", "uv"):
        available = bool(shutil.which(tool))
        checks.append(
            CheckResult(
                tool,
                Status.OK if available else Status.FAIL,
                "available" if available else "install this CLI before bootstrap",
            )
        )
    report = PreflightReport("gcp", "local", record.installation.deployment.name, checks)
    if not report.ok:
        raise invalid(report.render())


def _bootstrap(record: DeploymentRecord, args: argparse.Namespace) -> None:
    """Stage the pinned product and execute both stacks under verified authority."""
    from inventory_plan import create_plan_directory
    from inventory_runner import bootstrap_runner

    _authorize_bootstrap(record, args)
    product_root = get_repo_root()
    plan_output = create_plan_directory(_safe_output_path(args.plan_output, "--plan-output"))
    write_private(
        plan_output / "provenance.json",
        json.dumps(
            {
                "inventory_repository": args.inventory_repository,
                "inventory_revision": args.inventory_revision,
                "product_repository": record.product.repository,
                "product_revision": record.product.revision,
                "deployment": record.installation.deployment.name,
                "project": args.project,
            },
            sort_keys=True,
            indent=2,
        ),
    )
    with tempfile.TemporaryDirectory(prefix="shifter-inventory-") as temporary:
        directory = Path(temporary)
        tf_root = stage_product(product_root, record.product.revision, directory)
        env = operator_environment(args.operator)
        project_number = verify_projects(record, env)
        verify_github_actor(record, args.github_actor, inventory_repository=args.inventory_repository)
        ensure_services(record, env, apply=args.apply)
        ensure_state_buckets(record, env, apply=args.apply)
        with bootstrap_lock(record, directory, env):
            reconcile_environments(record, apply=args.apply)
            reconcile_subject(record, apply=args.apply)
            result = plan_identity(
                record,
                directory=tf_root,
                product_root=product_root,
                project_number=project_number,
                env=env,
                plan_output=plan_output,
                apply=args.apply,
            )
            result["runner_plan"] = bootstrap_runner(
                record,
                directory / "platform/terraform/gcp/global/github-runner",
                env,
                apply=args.apply,
                plan_output=plan_output,
            )
            if args.apply:
                from inventory_readback import verify_installed_identity

                verify_installed_identity(record, project_number, env, product_root)
                publish_execution_bindings(record, project_number)
            result["inventory_revision"] = args.inventory_revision
            result["plan_output"] = str(plan_output)
            print(json.dumps(result, sort_keys=True))


def handle(args: argparse.Namespace) -> None:
    """Validate all records, then operate only on the explicitly authorized one."""
    try:
        record = verified_inventory(args)
        if args.action == "validate":
            print(json.dumps({"deployment": record.installation.deployment.name, "valid": True}))
        elif args.action == "scaffold":
            from inventory_scaffold import scaffold_checks

            if not args.output:
                raise invalid("scaffold requires a new output directory")
            scaffold_checks(record, _safe_output_path(args.output, "--output"))
        elif args.action == "resolve-secret":
            _resolve_secret(record, args)
        else:
            _bootstrap(record, args)
    except InstallationConfigError as exc:
        raise SystemExit(str(exc)) from None
