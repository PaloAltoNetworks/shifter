"""Argument-parser construction for the ``shifter-config`` CLI.

Split out of :mod:`installation.cli` (Sonar S104) so the CLI module stays within
its size budget and the parser wiring lives on its own seam. Each subcommand is
wired by a focused ``_add_*_parser`` helper so :func:`build_parser` itself stays
small; :mod:`installation.cli` owns the command implementations and dispatch.
"""

from __future__ import annotations

import argparse

from .doctor import CheckScope

DEFAULT_CONFIG_FILENAME = "shifter.yaml"


def _add_config_path_argument(parser: argparse.ArgumentParser) -> None:
    """Add the standard optional ``path`` positional pointing at the config file."""
    parser.add_argument(
        "path",
        nargs="?",
        default=DEFAULT_CONFIG_FILENAME,
        help=f"Path to the config file (default: ./{DEFAULT_CONFIG_FILENAME}).",
    )


def _add_output_argument(parser: argparse.ArgumentParser, what: str) -> None:
    """Add the standard ``--output/-o`` argument writing ``what`` to a file or stdout."""
    parser.add_argument(
        "--output",
        "-o",
        metavar="FILE",
        default=None,
        help=f"Write the rendered {what} to FILE (default: stdout).",
    )


def _add_validate_parser(subcommands: argparse._SubParsersAction) -> None:
    """Wire the ``validate`` subcommand: check the shape of a root installation config."""
    validate = subcommands.add_parser(
        "validate",
        help=f"Validate the shape of a root installation config (default: ./{DEFAULT_CONFIG_FILENAME}).",
        description=(
            f"Validate the shape of a root installation config (default: ./{DEFAULT_CONFIG_FILENAME}): "
            "the backend selector, deployment identity, secret references, and that backend-specific "
            "settings is a mapping. The contents of settings are validated by the selected backend bundle."
        ),
    )
    _add_config_path_argument(validate)


def _add_render_parsers(subcommands: argparse._SubParsersAction) -> None:
    """Wire the installation-owned render subcommands."""
    render = subcommands.add_parser(
        "render",
        help="Render the range egress policy into provider Terraform bridge .tfvars.",
        description=(
            "Render the validated settings.range_egress policy into the provider-specific "
            "Terraform bridge variables for the config's backend (AWS: victim_allowed_cidrs; "
            "GCP: range_egress_mode + range_egress_allowed_cidrs). The rendered file is the "
            "single source for the deployed allowlist, generated from shifter.yaml so the "
            "configured policy and deployed firewall rules cannot diverge."
        ),
    )
    _add_config_path_argument(render)
    _add_output_argument(render, ".tfvars")
    render_runtime = subcommands.add_parser(
        "render-runtime",
        help="Render the selected backend into a renderer-owned cloud_provider Terraform tfvar.",
        description=(
            "Render the validated backend selection from shifter.yaml into the renderer-owned "
            "cloud_provider Terraform tfvar, so the runtime cloud-provider identity is derived "
            "from the installation config rather than hardcoded or inferred from a branch name."
        ),
    )
    _add_config_path_argument(render_runtime)
    _add_output_argument(render_runtime, "tfvar")
    render_warm_pool = subcommands.add_parser(
        "render-warm-pool-env",
        help="Render settings.warm_pool into the WARM_POOL_POLICY_JSON runtime env line (#28).",
        description=(
            "Render the validated settings.warm_pool policy from shifter.yaml into the "
            "WARM_POOL_POLICY_JSON runtime env line the deploy pipeline injects into the "
            "platform-runtime ConfigMap, so a configured warm pool reaches the portal and "
            "reconciler rather than booting disabled."
        ),
    )
    _add_config_path_argument(render_warm_pool)
    _add_output_argument(render_warm_pool, "env line")
    render_mission_control_lease = subcommands.add_parser(
        "render-mission-control-lease-env",
        help="Render settings.mission_control_leases into the MISSION_CONTROL_LEASE_POLICY_JSON env line (#27).",
        description=(
            "Render the validated settings.mission_control_leases policy from shifter.yaml into the "
            "MISSION_CONTROL_LEASE_POLICY_JSON runtime env line the deploy pipeline injects into the "
            "platform-runtime ConfigMap, so a configured lease policy reaches Mission Control rather "
            "than booting the canonical 30/30/365 defaults."
        ),
    )
    _add_config_path_argument(render_mission_control_lease)
    _add_output_argument(render_mission_control_lease, "env line")
    render_model_catalog = subcommands.add_parser(
        "render-model-access-catalog",
        help="Render settings.model_access.catalog as a dedicated mounted JSON artifact.",
    )
    _add_config_path_argument(render_model_catalog)
    _add_output_argument(render_model_catalog, "catalog JSON")
    render_model_env = subcommands.add_parser(
        "render-model-access-env",
        help="Render model-access activation, mounted path, and expected digest env lines.",
    )
    _add_config_path_argument(render_model_env)
    _add_output_argument(render_model_env, "model-access env lines")


def _add_inventory_parser(subcommands: argparse._SubParsersAction) -> None:
    """Wire the ``runtime-inventory`` subcommand: list/check runtime config surfaces."""
    inventory = subcommands.add_parser(
        "runtime-inventory",
        help="List or check the repo runtime configuration inventory.",
        description=(
            "List or check runtime configuration surfaces by file path and key name only. "
            "The checker never prints env values."
        ),
    )
    inventory.add_argument(
        "--repo-root",
        default=".",
        help="Repository root to check (default: current directory).",
    )
    inventory.add_argument(
        "--check",
        action="store_true",
        help="Validate tracked runtime env files against the inventory.",
    )


def _add_init_parser(subcommands: argparse._SubParsersAction) -> None:
    """Wire the ``init`` subcommand: scaffold a starting shifter.yaml from a checked example."""
    init = subcommands.add_parser(
        "init",
        help="Scaffold a starting shifter.yaml from a checked backend example.",
        description=(
            "Copy the checked example config for the selected backend to a shifter.yaml so you "
            f"start from a valid, backend-shaped config (default: ./{DEFAULT_CONFIG_FILENAME}). "
            "Local-only: it authenticates to nothing, writes no secrets, and touches no cloud "
            "API. Omit --backend to list the available backends."
        ),
    )
    init.add_argument(
        "--backend",
        default=None,
        help="Backend to scaffold (for example aws or gcp). Omit to list the available backends.",
    )
    init.add_argument(
        "--output",
        "-o",
        metavar="FILE",
        default=None,
        help=f"Destination path for the scaffolded config (default: ./{DEFAULT_CONFIG_FILENAME}).",
    )
    init.add_argument(
        "--force",
        action="store_true",
        help="Overwrite the destination if it already exists.",
    )


def _add_doctor_parser(subcommands: argparse._SubParsersAction) -> None:
    """Wire the ``doctor`` subcommand: validate the selected backend before deploy."""
    doctor = subcommands.add_parser(
        "doctor",
        help="Validate the selected backend before applying infrastructure.",
        description=(
            "Validate the backend selected by a root installation config (default: "
            f"./{DEFAULT_CONFIG_FILENAME}) before infrastructure is applied. Runs the checks the "
            "selected backend bundle declares — required tools, secret references, generated "
            "outputs, owned repo paths, validation checks, and (opt-in) read-only health probes — "
            "and labels each by side-effect tier. Non-mutating by default."
        ),
    )
    _add_config_path_argument(doctor)
    doctor.add_argument(
        "--repo-root",
        default=".",
        help="Repository root the owned-path and validation checks run against (default: current directory).",
    )
    doctor.add_argument(
        "--checks",
        choices=[scope.value for scope in CheckScope],
        default=CheckScope.LOCAL.value,
        help=(
            "Which check tiers to run: 'local' (default, non-network) validates config, tools, and "
            "owned paths; 'cloud-read-only' adds non-mutating cloud probes; 'all' runs every "
            "declared check."
        ),
    )
    doctor.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Emit the report as JSON instead of human-readable text.",
    )


def _add_contract_parser(subcommands: argparse._SubParsersAction) -> None:
    """Wire the ``contract export`` / ``contract check`` subcommands."""
    contract = subcommands.add_parser(
        "contract",
        help="Export or check the published, versioned backend-bundle contract artifact.",
        description=(
            "Publish the backend-bundle contract as a committed, versioned artifact generated "
            "from the Pydantic contract and registry, and check it for drift, unversioned "
            "breaking changes, and registry conformance."
        ),
    )
    contract_sub = contract.add_subparsers(dest="contract_command", metavar="<subcommand>")
    export = contract_sub.add_parser(
        "export",
        help="Regenerate the published contract artifact from the code.",
        description=(
            "Generate the canonical backend-bundle contract artifact from the Pydantic contract "
            "and registry and write it to the committed artifact path (or --output)."
        ),
    )
    export.add_argument(
        "--output",
        "-o",
        metavar="FILE",
        default=None,
        help="Write the artifact to FILE (default: the committed contract artifact path).",
    )
    contract_sub.add_parser(
        "check",
        help="Check the published contract for drift, breaking changes, and registry conformance.",
        description=(
            "Fail (exit 1) when the committed artifact is out of date with the code, when the "
            "contract changed incompatibly without a version bump and migration note, or when a "
            "registered backend does not validate against the published version."
        ),
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the ``shifter-config`` argument parser with every subcommand wired."""
    parser = argparse.ArgumentParser(
        prog="shifter-config",
        description="Inspect and validate the root Shifter installation config.",
    )
    subcommands = parser.add_subparsers(dest="command", metavar="<command>")
    _add_validate_parser(subcommands)
    _add_render_parsers(subcommands)
    _add_inventory_parser(subcommands)
    _add_init_parser(subcommands)
    _add_doctor_parser(subcommands)
    _add_contract_parser(subcommands)
    return parser
