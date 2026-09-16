"""Operator entry point.

On demand only. There is no scheduled or deploy-triggered invocation of this
command anywhere in the repo, and it takes no cloud role: the participant
session is the authority it acts with.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import secrets
import sys

from range_functional_smoke import report
from range_functional_smoke.profile import Deadlines, ProfileError, Protocol, RunProfile
from range_functional_smoke.runner import Runner
from range_functional_smoke.session import Credential, SessionError, load_session_cookie


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="range-functional-smoke",
        description=(
            "Prove the participant journey against a known-up example range: a terminal that "
            "exchanges real data with a range host, and a Guacamole session that reaches a "
            "client-level connection."
        ),
    )
    parser.add_argument("--origin", required=True, help="exact portal origin, e.g. https://portal.example.com")
    parser.add_argument("--environment", required=True, help="operator-facing name of the target deployment")
    parser.add_argument("--target-role", default="attacker", help="authored logical target role (default: attacker)")
    parser.add_argument(
        "--protocol",
        default=Protocol.RDP.value,
        choices=[item.value for item in Protocol],
        help="Guacamole protocol profile (default: rdp, since the terminal check already covers ssh)",
    )
    parser.add_argument(
        "--allow-production",
        action="store_true",
        help="positively acknowledge a production-looking target (refused by default)",
    )
    parser.add_argument(
        "--allow-plaintext-loopback",
        action="store_true",
        help=(
            "permit http/ws for a loopback target only. Plaintext to any other host is always "
            "refused: it would expose the participant session and the Guacamole token"
        ),
    )
    parser.add_argument("--evidence", help="write the rendered report to this path in addition to stdout")

    source = parser.add_argument_group("actor source (exactly one)")
    source.add_argument("--session-file", help="path to a 0600 file holding an operator-captured session key")
    source.add_argument("--email", help="Identity Platform account to log in as")
    source.add_argument(
        "--credential-env",
        action="store_true",
        help=(
            "read the Identity Platform password, TOTP secret, and web API key from "
            "SMOKE_PASSWORD / SMOKE_TOTP_SECRET / SMOKE_API_KEY (never passed on argv)"
        ),
    )

    bounds = parser.add_argument_group("deadlines (seconds)")
    bounds.add_argument("--terminal-exchange-timeout", type=float, default=45.0)
    bounds.add_argument("--guacamole-bootstrap-timeout", type=float, default=90.0)
    bounds.add_argument("--run-timeout", type=float, default=600.0)
    return parser


def _credential(args: argparse.Namespace) -> Credential:
    """Build the login credential from the environment, never from argv."""
    return Credential(
        email=args.email or "",
        password=os.environ.get("SMOKE_PASSWORD", ""),
        totp_secret=os.environ.get("SMOKE_TOTP_SECRET", ""),
        api_key=os.environ.get("SMOKE_API_KEY", ""),
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if bool(args.session_file) == bool(args.credential_env):
        print("error: choose exactly one actor source (--session-file or --credential-env)", file=sys.stderr)
        return 2

    try:
        profile = RunProfile(
            origin=args.origin,
            environment=args.environment,
            target_role=args.target_role,
            protocol=Protocol(args.protocol),
            allow_production=args.allow_production,
            allow_plaintext_loopback=args.allow_plaintext_loopback,
            evidence_path=args.evidence,
            deadlines=Deadlines(
                terminal_exchange_seconds=args.terminal_exchange_timeout,
                guacamole_bootstrap_seconds=args.guacamole_bootstrap_timeout,
                run_seconds=args.run_timeout,
            ),
        )
        cookie = load_session_cookie(args.session_file) if args.session_file else None
        credential = _credential(args) if args.credential_env else None
    except (ProfileError, SessionError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    run_id = secrets.token_hex(6)
    runner = Runner(profile, credential=credential, session_cookie=cookie)
    results = asyncio.run(runner.run())
    rendered = report.render(results, profile, run_id=run_id)

    print(rendered)
    if profile.evidence_path:
        with open(profile.evidence_path, "w", encoding="utf-8") as handle:
            handle.write(rendered)

    return 0 if results.passed else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
