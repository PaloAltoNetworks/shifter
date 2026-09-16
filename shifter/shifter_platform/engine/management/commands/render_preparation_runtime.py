"""Render the optional preparation add-on after the platform tenant exists."""

import json
from argparse import ArgumentParser
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from shared.cloud.preparation_installation import PreparationInstallation, render_preparation_installation


class Command(BaseCommand):
    """Render closed operator configuration; rendering never activates a cloud grant."""

    help = "Render preparation Kubernetes resources as a JSON List for kubectl."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--configuration", type=Path, required=True)
        parser.add_argument("--format", choices=("kubernetes", "terraform"), default="kubernetes")

    def handle(self, *args: Any, **options: Any) -> None:
        path = options["configuration"]
        try:
            if path.stat().st_size > 262144:
                raise ValueError("configuration exceeds the size limit")
            configuration = PreparationInstallation.model_validate_json(path.read_bytes())
        except (OSError, ValueError) as exc:
            raise CommandError("Invalid preparation installation configuration") from exc
        if options["format"] == "terraform":
            from shared.cloud.preparation_cloud_installation import render_preparation_terraform

            document = render_preparation_terraform(configuration)
        else:
            document = {"apiVersion": "v1", "kind": "List", "items": render_preparation_installation(configuration)}
        self.stdout.write(json.dumps(document, indent=2))
