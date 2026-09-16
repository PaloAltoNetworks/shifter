"""Activate a verified post-setup installation, or revoke its application authority."""

import json
from argparse import ArgumentParser
from pathlib import Path
from typing import Any
from uuid import UUID

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from engine.services import activate_preparation_grant, revoke_preparation_grant
from shared.exceptions import ValidationError


class Command(BaseCommand):
    """Provide Command."""

    help = "Verify deployed preparation IAM/Kubernetes resources and activate their immutable grant."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "--actor", required=True, help="Application operator username with manage_preparation_grants"
        )
        operation = parser.add_mutually_exclusive_group(required=True)
        operation.add_argument("--configuration", type=Path)
        operation.add_argument("--revoke", type=UUID)

    def handle(self, *args: Any, **options: Any) -> None:
        user = get_user_model().objects.filter(username=options["actor"]).first()
        if user is None:
            raise CommandError("Preparation grant installation failed")
        try:
            if options["revoke"]:
                revoke_preparation_grant(user, options["revoke"])
                self.stdout.write("Preparation grant revoked; pending cleanup retains its pinned runtime.")
                return
            path = options["configuration"]
            if path.stat().st_size > 262144:
                raise ValueError("configuration exceeds its bound")
            identity = activate_preparation_grant(user, json.loads(path.read_bytes()))
        except (OSError, ValueError, ValidationError) as exc:
            raise CommandError("Preparation grant installation failed") from exc
        self.stdout.write(str(identity))
