"""Render the pinned authorization model for the separate deployment-admin workload."""

from django.core.management.base import BaseCommand

from shared.authorization.model import MODEL_DSL


class Command(BaseCommand):
    """Render the pinned authorization model without contacting an evaluator."""

    help = "Write the pinned OpenFGA model DSL to standard output."

    def handle(self, *args: object, **options: object) -> None:
        self.stdout.write(MODEL_DSL)
