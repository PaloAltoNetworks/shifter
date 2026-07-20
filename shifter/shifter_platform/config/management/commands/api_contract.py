"""Regenerate or drift-check the committed ``/api/v1/`` OpenAPI contract (#1329)."""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from shared.api.contract import (
    API_MAJOR,
    artifact_path,
    check_breaking_against,
    check_drift,
    write_artifact,
)


class Command(BaseCommand):
    """Write the committed OpenAPI artifact, or verify it against the DRF surface."""

    help = "Regenerate openapi/<major>.json, --check for drift, or --breaking-against a base ref."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--check",
            action="store_true",
            help="Fail if the committed artifact differs from a fresh generation (CI drift gate).",
        )
        parser.add_argument(
            "--breaking-against",
            default=None,
            metavar="REF",
            help="Fail if the committed artifact makes consumer-breaking changes vs this base git ref.",
        )
        parser.add_argument(
            "--major",
            default=API_MAJOR,
            help=f"API major to operate on (default: {API_MAJOR}).",
        )

    def handle(
        self,
        *args: Any,
        check: bool = False,
        breaking_against: str | None = None,
        major: str = API_MAJOR,
        **options: Any,
    ) -> None:
        if check:
            is_current, detail = check_drift(major)
            if not is_current:
                raise CommandError(
                    "OpenAPI contract drift: the committed artifact does not match the DRF surface. "
                    "Run `manage.py api_contract` and commit the result.\n\n" + detail
                )
            self.stdout.write(self.style.SUCCESS(f"OpenAPI contract {artifact_path(major)} is up to date."))

        if breaking_against is not None:
            ok, detail = check_breaking_against(breaking_against, major)
            if not ok:
                raise CommandError(
                    f"Breaking API change vs {breaking_against}: {major} must stay backward-compatible. "
                    "Ship consumer-breaking changes as a parallel /api/v2/ with a migration note (ADR-040).\n\n"
                    + detail
                )
            self.stdout.write(self.style.SUCCESS(f"No breaking changes vs {breaking_against}. {detail}".strip()))

        if not check and breaking_against is None:
            path = write_artifact(major)
            self.stdout.write(self.style.SUCCESS(f"Wrote {path}"))
