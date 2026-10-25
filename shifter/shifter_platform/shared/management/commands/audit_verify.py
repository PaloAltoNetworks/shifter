"""Verify the complete shared audit hash chain without mutating it."""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from shared.audit.integrity import AuditIntegrityError, verify_audit_chain


class Command(BaseCommand):
    """Verify the stored audit chain and report its terminal digest."""

    help = "Verify audit sequence and digest continuity without repairing evidence"

    def handle(self, *args, **options) -> None:
        try:
            result = verify_audit_chain()
        except AuditIntegrityError as exc:
            raise CommandError(f"Audit integrity verification failed: {exc}") from exc

        noun = "record" if result.record_count == 1 else "records"
        self.stdout.write(
            self.style.SUCCESS(
                "Audit chain verified: "
                f"{result.record_count} {noun}; "
                f"scope={result.deployment_scope}; "
                f"generation={result.chain_generation}; "
                f"canonicalization=v{result.canonicalization_version}; "
                f"terminal_digest={result.terminal_digest or 'genesis'}"
            )
        )
