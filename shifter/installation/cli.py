"""``shifter-config`` — inspect and validate the root Shifter installation config.

Today it exposes one subcommand, ``validate``, which checks the *shape* of
``shifter.yaml`` — the backend selector, deployment identity, secret references, and
that backend-specific ``settings`` is a mapping — so CI, deploy scripts, and operators
catch a malformed root config before Terraform, Helm, Django, workers, or deployment
scripts run. The *contents* of ``settings`` (and which settings a backend requires) are
validated by the selected backend bundle's contract (#1113); the backend-aware
setup/doctor UX is #1115. This command deliberately stays small: parse a path, read a
file, print sanitized results.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .errors import InstallationConfigError
from .loader import load_root_config

DEFAULT_CONFIG_FILENAME = "shifter.yaml"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="shifter-config",
        description="Inspect and validate the root Shifter installation config.",
    )
    subcommands = parser.add_subparsers(dest="command", metavar="<command>")
    validate = subcommands.add_parser(
        "validate",
        help=f"Validate the shape of a root installation config (default: ./{DEFAULT_CONFIG_FILENAME}).",
        description=(
            f"Validate the shape of a root installation config (default: ./{DEFAULT_CONFIG_FILENAME}): "
            "the backend selector, deployment identity, secret references, and that backend-specific "
            "settings is a mapping. The contents of settings are validated by the selected backend bundle."
        ),
    )
    validate.add_argument(
        "path",
        nargs="?",
        default=DEFAULT_CONFIG_FILENAME,
        help=f"Path to the config file (default: ./{DEFAULT_CONFIG_FILENAME}).",
    )
    return parser


def _cmd_validate(path_str: str) -> int:
    config_path = Path(path_str)
    try:
        config = load_root_config(config_path)
    except InstallationConfigError as exc:
        print(f"{config_path}: invalid", file=sys.stderr)
        for issue in exc.issues:
            print(f"  - {issue.render()}", file=sys.stderr)
        return 1
    print(
        f"{config_path}: OK — root config shape is valid "
        f"(backend={config.backend}, profile={config.deployment.profile})"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help(sys.stderr)
        return 2
    if args.command == "validate":
        return _cmd_validate(args.path)
    parser.print_help(sys.stderr)  # pragma: no cover - argparse rejects unknown subcommands first
    return 2


if __name__ == "__main__":  # pragma: no cover - exercised via ``python -m installation``
    sys.exit(main())
