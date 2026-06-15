"""CLI entry point: ``python3 -m scenario_smoketest``.

Operator-run, on-demand, against a real staged range. Not wired to CI.

The CLI keeps every parameter at the edge: board paths, the runner-container
hostnames, challenge filters, and the optional read-only CTFd readback.

CTFd admin tokens are never accepted as a command-line argument (process argv
is world-readable). The token is read from the ``CTFD_TOKEN`` environment
variable or from a permission-restricted file via ``--ctfd-token-file``.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import ctfd_check, report, run
from .board import load_board
from .runner import Runner

_DEFAULT_BUILD = Path(__file__).resolve().parents[2] / "build"
_DEFAULT_CHALLENGES = _DEFAULT_BUILD / "ctfd-challenges.json"

# Default asset hostnames as resolved inside the range runner containers.
_DEFAULT_HOSTS = {
    "a0": "boreas-systems.ctf",
    "a3": "intranet.boreas.local",
}


def _parse_host_overrides(pairs: list[str]) -> dict[str, str]:
    hosts = dict(_DEFAULT_HOSTS)
    for pair in pairs:
        if "=" not in pair:
            raise SystemExit(f"--host expects key=value, got {pair!r}")
        key, _, value = pair.partition("=")
        hosts[key.strip()] = value.strip()
    return hosts


def _read_ctfd_token(token_file: str | None) -> str | None:
    if token_file:
        return Path(token_file).read_text(encoding="utf-8").strip()
    return os.environ.get("CTFD_TOKEN")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scenario_smoketest",
        description="Pre-event Polaris scenario-content smoketest (issue #617).",
    )
    parser.add_argument(
        "--challenges",
        default=str(_DEFAULT_CHALLENGES),
        help="Path to ctfd-challenges.json (default: repo build artifact).",
    )
    parser.add_argument(
        "--onboarding",
        default=None,
        help="Optional path to ctfd-onboarding.json to merge into the universe.",
    )
    parser.add_argument(
        "--only",
        default=None,
        help="Comma-separated challenge ids to run (default: all).",
    )
    parser.add_argument(
        "--host",
        action="append",
        default=[],
        metavar="KEY=HOSTNAME",
        help="Override an asset hostname (e.g. a0=boreas-systems.ctf).",
    )
    parser.add_argument(
        "--dns", default="172.20.0.2", help="DNS sidecar address used by adapters."
    )
    parser.add_argument(
        "--docker", default="docker", help="Path to the docker CLI."
    )
    parser.add_argument(
        "--json-report",
        default=None,
        help="Optional path for a redacted JSON result report.",
    )
    parser.add_argument(
        "--ctfd-url",
        default=None,
        help="Base URL of a deployed CTFd for the read-only flag-row readback.",
    )
    parser.add_argument(
        "--ctfd-token-file",
        default=None,
        help="File holding the CTFd admin token (else read from CTFD_TOKEN).",
    )
    parser.add_argument(
        "--skip-range",
        action="store_true",
        help="Skip the range sweep and run only the CTFd readback.",
    )
    return parser


def _run_ctfd_readback(ctfd_url: str, token: str | None) -> int:
    if not token:
        print(
            "[ctfd] no token (set CTFD_TOKEN or --ctfd-token-file); skipping readback",
            file=sys.stderr,
        )
        return 0
    # Imported lazily: the workshop client lives outside this package.
    sys.path.insert(
        0, str(Path(__file__).resolve().parents[4] / "scripts" / "ctfd-workshop")
    )
    from common import CtfdClient  # noqa: PLC0415

    client = CtfdClient(ctfd_url, token)
    results = ctfd_check.check_flags(client)
    print(ctfd_check.build_report(results))
    return ctfd_check.exit_code(results)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    range_code = 0
    if not args.skip_range:
        challenges = load_board(args.challenges, args.onboarding)
        only_ids = None
        if args.only:
            only_ids = {int(x) for x in args.only.split(",") if x.strip()}
        results = run.run_smoketest(
            challenges,
            Runner(docker=args.docker),
            hosts=_parse_host_overrides(args.host),
            dns=args.dns,
            only_ids=only_ids,
        )
        print(report.build_report(results))
        if args.json_report:
            report.write_json_report(results, args.json_report)
        range_code = report.aggregate_exit_code(results)

    ctfd_code = 0
    if args.ctfd_url:
        ctfd_code = _run_ctfd_readback(
            args.ctfd_url, _read_ctfd_token(args.ctfd_token_file)
        )

    return 1 if (range_code or ctfd_code) else 0


if __name__ == "__main__":
    sys.exit(main())
